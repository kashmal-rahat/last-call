"""Phone demo (Module 9, D61): ring the presenter's own SIM through Twilio for the demo video.

Judges only ever get the browser call. Three locks keep it that way:

1. `Settings.PHONE_DEMO_ENABLED` (Terraform `phone_demo_enabled`, default false): every
   endpoint here answers 404 while it is off.
2. The page shows the phone option only with `?phone=1`.
3. The number to ring comes only from `PHONE_DEMO_CONFIG` (Secret Manager), never from a
   request, so this can only ever ring that one SIM.

Flow: the page creates the call through `/demo/calls` exactly as for a browser call, then
`POST /demo/phone/dial` asks Twilio to ring the SIM. When it is answered, Twilio streams the
audio to the voice service's `/phone/stream`, presenting the same single-use call token.

Privacy: phone numbers, Twilio credentials and Twilio responses are never logged or returned.
"""

import logging
import re
from typing import Awaitable, Callable
from xml.sax.saxutils import quoteattr

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from lastcall_shared.config import get_settings
from lastcall_shared.session_tokens import verify as verify_session_token
from lastcall_shared.store import CallStore
from lastcall_shared.twilio import PhoneDemoConfig, TwilioClient, TwilioError, load_phone_demo_config

logger = logging.getLogger("lastcall_api.phone_demo")

RING_SECONDS = 30
DIAL_IP_LIMIT_PER_HOUR = 10

_CALL_ID_RE = re.compile(r"^call_[a-f0-9]{32}$")

Dialer = Callable[[PhoneDemoConfig, str], Awaitable[None]]


class DialRequest(BaseModel):
    call_id: str
    token: str


def stream_url() -> str:
    """The voice service's `/phone/stream`, next to the browser's `/ws/call`."""
    ws_url = get_settings().VOICE_WS_URL or ""
    if not (ws_url.startswith("wss://") and ws_url.endswith("/ws/call")):
        raise TwilioError("VOICE_WS_URL must be a wss:// URL ending in /ws/call")
    return ws_url.removesuffix("/ws/call") + "/phone/stream"


def build_twiml(url: str, token: str) -> str:
    """Answer → open a two-way media stream; the call token rides along as a Stream parameter."""
    return (
        "<Response><Connect>"
        f'<Stream url={quoteattr(url)}><Parameter name="token" value={quoteattr(token)}/></Stream>'
        "</Connect></Response>"
    )


async def dial_twilio(config: PhoneDemoConfig, twiml: str) -> None:
    await TwilioClient(config).create_call(twiml, ring_seconds=RING_SECONDS)


def _is_valid_line(line: dict) -> bool:
    if line.get("kind") == "whatsapp":
        return line.get("whatsapp") in ("photo", "confirmation")
    return line.get("speaker") in ("agent", "buyer")


def _public_line(line: dict) -> dict:
    """A transcript line, or (D62) a WhatsApp message the agent sent during the call."""
    out = {"i": int(line.get("i", 0)), "text": str(line.get("text", ""))}
    if line.get("kind") == "whatsapp":
        out.update(kind="whatsapp", whatsapp=line["whatsapp"], media_url=line.get("media_url"))
    else:
        out["speaker"] = line["speaker"]
    return out


def build_router(
    *,
    verify_access_code: Callable[[str | None], bool],
    get_store: Callable[[], CallStore],
    check_ip_limit: Callable[[Request, str, int], Awaitable[None]],
    get_dialer: Callable[[], Dialer],
) -> APIRouter:
    """The `/demo/phone` endpoints. Dependencies come from `main` so this module stays standalone."""
    router = APIRouter(prefix="/demo/phone", tags=["phone-demo"])

    def require_enabled() -> None:
        if not get_settings().PHONE_DEMO_ENABLED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    def require_access(code: str | None, call_id: str | None = None) -> None:
        if not verify_access_code(code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")
        if call_id is not None and not _CALL_ID_RE.match(call_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid call_id")

    @router.get("/config")
    async def phone_config() -> dict:
        require_enabled()
        return {"enabled": True}

    @router.post("/dial")
    async def phone_dial(
        body: DialRequest,
        request: Request,
        x_demo_access_code: str | None = Header(default=None),
    ) -> dict:
        require_enabled()
        require_access(x_demo_access_code, body.call_id)
        await check_ip_limit(request, "phone", DIAL_IP_LIMIT_PER_HOUR)

        # The token proves this browser has just created this call through /demo/calls.
        key = get_settings().APP_SIGNING_KEY.get_secret_value()
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
            config = load_phone_demo_config(get_settings())
            twiml = build_twiml(stream_url(), body.token)
        except TwilioError as exc:
            logger.error("phone_demo_not_configured", extra={"error": str(exc)})
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Phone demo is not configured")

        try:
            await get_dialer()(config, twiml)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, TwilioError) else type(exc).__name__
            logger.error("phone_demo_dial_failed", extra={"call_id": body.call_id, "error": reason})
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not ring the phone, please try again")

        await store.add_flag(body.call_id, "phone_demo")
        logger.info("phone_demo_dialed", extra={"call_id": body.call_id})
        return {"ok": True, "ring_seconds": RING_SECONDS}

    @router.get("/calls/{call_id}")
    async def phone_call_status(call_id: str, x_demo_access_code: str | None = Header(default=None)) -> dict:
        """Call status and transcript lines so far; the page polls this once a second."""
        require_enabled()
        require_access(x_demo_access_code, call_id)
        store = get_store()
        call = await store.get_call(call_id)
        if call is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
        lines = sorted(await store.get_live_lines(call_id), key=lambda line: int(line.get("i", 0)))
        return {"status": call.status, "lines": [_public_line(line) for line in lines if _is_valid_line(line)]}

    return router
