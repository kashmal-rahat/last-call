"""Last Call API service (Milestone 2B Step 11)."""

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.scenarios.loader import build_call, list_scenarios, load_scenario
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import CallStore

SERVICE_NAME = "api"
VERSION = "0.1.0"
COMMIT = os.getenv("GIT_COMMIT", "dev")
PKT = ZoneInfo("Asia/Karachi")

logger = setup_structured_logging(service_name=SERVICE_NAME)

STATIC_DIR = Path(__file__).parent / "static"

# Per-IP rate limiting: max 5 sessions per hour
_IP_LIMITER_LOCK = asyncio.Lock()
_IP_REQUEST_HISTORY: dict[str, list[float]] = {}


from lastcall_shared.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Security requirement: check APP_SIGNING_KEY presence and valid length (>= 32 chars)
    settings = get_settings()
    key_val = settings.APP_SIGNING_KEY.get_secret_value() if settings.APP_SIGNING_KEY else ""
    if len(key_val.strip()) < 32:
        raise RuntimeError("APP_SIGNING_KEY must be configured with at least 32 characters")

    demo_code_present = bool(os.getenv("DEMO_ACCESS_CODE", "").strip())
    logger.info(
        "API service starting up",
        extra={
            "extra_fields": {
                "app_signing_key_present": True,
                "demo_access_code_present": demo_code_present,
                "version": VERSION,
            }
        },
    )
    yield
    logger.info("API service shutting down")


app = FastAPI(title="Last Call API", version=VERSION, lifespan=lifespan)

# Mount static files directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _get_store() -> CallStore:
    return getattr(app.state, "store", None) or FirestoreStore()


def _verify_access_code(provided_code: str | None) -> bool:
    expected_code = os.getenv("DEMO_ACCESS_CODE", "")
    if not expected_code or not provided_code:
        return False
    return hmac.compare_digest(provided_code.strip(), expected_code.strip())


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "commit": COMMIT,
        "status": "healthy",
    }


@app.get("/demo")
async def get_demo_page():
    """Serves the static judge demo page."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Demo page not found")
    return FileResponse(html_path)


@app.get("/demo/scenarios")
async def get_demo_scenarios(x_demo_access_code: str | None = Header(default=None)):
    """Returns available bargaining scenarios for the human tester, protected by access code."""
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    scenario_slugs = list_scenarios()
    scenarios_data = []
    for slug in scenario_slugs:
        try:
            data = load_scenario(slug)
            scenarios_data.append(data)
        except Exception:
            pass
    return {"scenarios": scenarios_data}


class CreateSessionRequest(BaseModel):
    scenario_id: str


@app.post("/demo/sessions")
async def create_demo_session(
    req: CreateSessionRequest,
    request: Request,
    x_demo_access_code: str | None = Header(default=None),
):
    """Initializes a new demo bargaining session, enforcing access code, per-IP limit, and daily cap."""
    # 1. Access code check
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    # 2. Per-IP rate limiting (configurable via IP_RATE_LIMIT_PER_HOUR, default 20 sessions per hour)
    settings = get_settings()
    ip_limit = int(os.getenv("IP_RATE_LIMIT_PER_HOUR", str(settings.IP_RATE_LIMIT_PER_HOUR)))
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
    now_ts = time.time()

    async with _IP_LIMITER_LOCK:
        history = _IP_REQUEST_HISTORY.get(client_ip, [])
        valid_history = [t for t in history if now_ts - t < 3600.0]
        if len(valid_history) >= ip_limit:
            logger.warning("ip_rate_limit_exceeded", extra={"client_ip": client_ip, "limit": ip_limit})
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Hourly IP limit reached (max {ip_limit} sessions per hour)",
            )
        valid_history.append(now_ts)
        _IP_REQUEST_HISTORY[client_ip] = valid_history

    # 3. Build and validate scenario call first (L3)
    now_pkt = datetime.now(PKT)
    try:
        call, batch = build_call(req.scenario_id, now=now_pkt)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scenario: {str(exc)}",
        )

    # 4. Daily session cap check (only incremented if scenario is valid)
    store = _get_store()
    date_str = now_pkt.strftime("%Y-%m-%d")
    daily_cap = int(os.getenv("DEMO_DAILY_SESSION_CAP", "50"))
    allowed = await store.incr_daily_sessions(date_str, daily_cap)
    if not allowed:
        logger.warning("daily_demo_cap_exceeded", extra={"date": date_str, "cap": daily_cap})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily demo session cap reached",
        )

    await store.create_call(call, batch)

    # 5. Mint short-lived session token (120s)
    settings = get_settings()
    signing_key = settings.APP_SIGNING_KEY.get_secret_value() if settings.APP_SIGNING_KEY else ""
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=signing_key, ttl=120, now=now_pkt)

    voice_ws_url = os.getenv("VOICE_WS_URL", "wss://lastcall-voice-dev.run.app/ws/call")
    logger.info("demo_session_created", extra={"call_id": call.call_id, "scenario": req.scenario_id})

    return {
        "call_id": call.call_id,
        "ws_url": voice_ws_url,
        "token": token,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
