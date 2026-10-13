"""Phone demo (Module 9): ring the presenter's own SIM through Twilio for the demo video.

Every endpoint answers 404 unless PHONE_DEMO_ENABLED=true, so judges only ever get the
browser call. The page creates the call with /demo/calls as usual; /demo/phone/dial then
asks Twilio to ring the fixed number in PHONE_DEMO_CONFIG (a Secret Manager secret). The
number never comes from a request, so this can only ever ring that one SIM.

Privacy: never logs or returns phone numbers, Twilio credentials or Twilio's response body.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Awaitable, Callable
from xml.sax.saxutils import quoteattr

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from lastcall_shared.config import get_settings
from lastcall_shared.session_tokens import verify as verify_session_token
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.phone_demo")

_CALL_ID_RE = re.compile(r"^call_[a-f0-9]{32}$")
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
RING_SECONDS = 30
DIAL_IP_LIMIT_PER_HOUR = 10


class PhoneDemoError(Exception):
    pass


@dataclass(frozen=True)
class PhoneConfig:
    account_sid: str
    api_key_sid: str
    api_key_secret: str
    from_number: str
    to_number: str


class DialRequest(BaseModel):
    call_id: str
    token: str


def phone_demo_enabled() -> bool:
    return os.getenv("PHONE_DEMO_ENABLED", "").strip().lower() == "true"


def load_phone_config() -> PhoneConfig:
    """Reads PHONE_DEMO_CONFIG (JSON) and checks every field."""
    try:
        raw = json.loads(os.getenv("PHONE_DEMO_CONFIG", ""))
        cfg = PhoneConfig(
            account_sid=str(raw["account_sid"]).strip(),
            api_key_sid=str(raw["api_key_sid"]).strip(),
            api_key_secret=str(raw["api_key_secret"]).strip(),
            from_number=str(raw["from_number"]).strip(),
            to_number=str(raw["to_number"]).strip(),
        )
    except Exception as exc:
        raise PhoneDemoError("PHONE_DEMO_CONFIG is missing or not valid JSON") from exc
    if not cfg.account_sid.startswith("AC") or not cfg.api_key_sid.startswith("SK") or not cfg.api_key_secret:
        raise PhoneDemoError("PHONE_DEMO_CONFIG has an invalid Twilio account or API key")
    if not _E164_RE.match(cfg.from_number) or not _E164_RE.match(cfg.to_number):
        raise PhoneDemoError("PHONE_DEMO_CONFIG numbers must be in E.164 format")
    return cfg


def stream_url() -> str:
    """The voice service's /phone/stream, derived from the browser's VOICE_WS_URL."""
    ws_url = os.getenv("VOICE_WS_URL", "")
    if not ws_url.startswith("wss://") or not ws_url.endswith("/ws/call"):
        raise PhoneDemoError("VOICE_WS_URL must be a wss:// URL ending in /ws/call")
    return ws_url[: -len("/ws/call")] + "/phone/stream"


def build_twiml(url: str, token: str) -> str:
    return (
        "<Response><Connect>"
        f"<Stream url={quoteattr(url)}><Parameter name=\"token\" value={quoteattr(token)}/></Stream>"
        "</Connect></Response>"
    )


async def dial_twilio(cfg: PhoneConfig, twiml: str) -> None:
    """Creates the outbound call. Recording stays off (Twilio's default)."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Calls.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            auth=(cfg.api_key_sid, cfg.api_key_secret),
            data={"To": cfg.to_number, "From": cfg.from_number, "Twiml": twiml, "Timeout": str(RING_SECONDS)},
        )
    if resp.status_code >= 300:
        raise PhoneDemoError(f"Twilio returned HTTP {resp.status_code}")


def build_router(
    *,
    verify_access_code: Callable[[str | None], bool],
    get_store: Callable[[], CallStore],
    check_ip_limit: Callable[..., Awaitable[None]],
    get_dialer: Callable[[], Callable[[PhoneConfig, str], Awaitable[None]]],
) -> APIRouter:
    router = APIRouter(prefix="/demo/phone")

    def _require_enabled() -> None:
        if not phone_demo_enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    def _require_code(code: str | None) -> None:
        if not verify_access_code(code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    def _check_call_id(call_id: str) -> None:
        if not _CALL_ID_RE.match(call_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid call_id")

    @router.get("/config")
    async def phone_config():
        _require_enabled()
        return {"enabled": True}

    @router.post("/dial")
    async def phone_dial(
        body: DialRequest,
        request: Request,
        x_demo_access_code: str | None = Header(default=None),
    ):
        _require_enabled()
        _require_code(x_demo_access_code)
        _check_call_id(body.call_id)
        await check_ip_limit(request, "phone", DIAL_IP_LIMIT_PER_HOUR)

        # The token proves this browser just created this call with /demo/calls.
        settings = get_settings()
        key = settings.APP_SIGNING_KEY.get_secret_value() if settings.APP_SIGNING_KEY else ""
        valid, payload, _ = verify_session_token(body.token, key=key)
        if not valid or not payload or payload.get("call_id") != body.call_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Call token is invalid or expired")

        store = get_store()
        call = await store.get_call(body.call_id)
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
        if call.status != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This call has already started")

        try:
            cfg = load_phone_config()
            twiml = build_twiml(stream_url(), body.token)
        except PhoneDemoError as exc:
            logger.error("phone_demo_not_configured", extra={"error": str(exc)})
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Phone demo is not configured")

        try:
            await get_dialer()(cfg, twiml)
        except Exception as exc:
            logger.error("phone_demo_dial_failed", extra={"call_id": body.call_id, "error": str(exc)})
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not ring the phone, please try again")

        await store.add_flag(body.call_id, "phone_demo")
        logger.info("phone_demo_dialed", extra={"call_id": body.call_id})
        return {"ok": True, "ring_seconds": RING_SECONDS}

    @router.get("/calls/{call_id}")
    async def phone_call_status(call_id: str, x_demo_access_code: str | None = Header(default=None)):
        _require_enabled()
        _require_code(x_demo_access_code)
        _check_call_id(call_id)
        store = get_store()
        call = await store.get_call(call_id)
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
        lines = await store.get_live_lines(call_id)
        return {
            "status": call.status,
            "lines": [
                {"i": int(x.get("i", 0)), "speaker": x.get("speaker"), "text": str(x.get("text", ""))}
                for x in sorted(lines, key=lambda x: int(x.get("i", 0)))
                if x.get("speaker") in ("agent", "buyer")
            ],
        }

    return router
