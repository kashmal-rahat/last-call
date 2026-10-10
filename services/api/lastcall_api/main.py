"""Last Call API service (Milestone 2B Step 11)."""

import asyncio
import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lastcall_api.inspector.images import ImageError
from lastcall_api.inspector.inspector import InspectorError, inspect_photo
from lastcall_api.ladder.ladder import decide_inspection
from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.scenarios.loader import build_call, list_scenarios, load_scenario
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import CallStore

SERVICE_NAME = "api"
VERSION = "0.1.0"
COMMIT = os.getenv("GIT_COMMIT", "dev")
PKT = ZoneInfo("Asia/Karachi")

logger = setup_structured_logging(service_name=SERVICE_NAME)

STATIC_DIR = Path(__file__).parent / "static"

# Concurrency limiting: max 2 simultaneous inspections per instance
_INSPECT_SEMAPHORE = asyncio.Semaphore(2)

# Per-IP rate limiting: history keyed by (bucket, client_ip)
_IP_LIMITER_LOCK = asyncio.Lock()
_IP_REQUEST_HISTORY: dict[tuple[str, str], list[float]] = {}


async def _check_ip_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_s: float = 3600.0,
    detail: str | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
    now_ts = time.time()
    key = (bucket, client_ip)

    async with _IP_LIMITER_LOCK:
        history = _IP_REQUEST_HISTORY.get(key, [])
        valid_history = [t for t in history if now_ts - t < window_s]
        if len(valid_history) >= limit:
            logger.warning("ip_rate_limit_exceeded", extra={"client_ip": client_ip, "bucket": bucket, "limit": limit})
            msg = detail or f"Hourly IP limit reached (max {limit} requests per hour)"
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=msg,
            )
        valid_history.append(now_ts)
        _IP_REQUEST_HISTORY[key] = valid_history


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


@lru_cache
def _default_store() -> CallStore:
    return FirestoreStore()


def _get_store() -> CallStore:
    return getattr(app.state, "store", None) or _default_store()


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
    await _check_ip_limit(
        request,
        bucket="session",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} sessions per hour)",
    )

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


@app.get("/demo/samples")
async def get_demo_samples():
    """Returns available sample shelf photos for testing (Milestone 1B Step 9)."""
    samples_file = STATIC_DIR / "samples" / "samples.json"
    if not samples_file.exists():
        return []
    try:
        with open(samples_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("failed_loading_samples", extra={"error": str(exc)})
        return []


@app.post("/demo/inspect")
async def demo_inspect(
    request: Request,
    photo: UploadFile = File(...),
    shelf_id: str = Form(""),
    bin_capacity_kg: float | None = Form(None),
    x_demo_access_code: str | None = Header(default=None),
):
    """Inspects a shelf photo for produce freshness (Milestone 1B Step 9)."""
    # 1. Access code check
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    # 2. Parameter validation
    if not re.match(r"^[a-z0-9_-]{1,40}$", shelf_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid shelf_id: must match ^[a-z0-9_-]{1,40}$",
        )
    if bin_capacity_kg is not None and not (0 < bin_capacity_kg <= 500):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid bin_capacity_kg: must be > 0 and <= 500",
        )

    # 3. IP limit
    settings = get_settings()
    ip_limit = int(os.getenv("IP_RATE_LIMIT_PER_HOUR", str(settings.IP_RATE_LIMIT_PER_HOUR)))
    await _check_ip_limit(
        request,
        bucket="inspect",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} inspections per hour)",
    )

    # 4. Content type check
    if photo.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Please upload a JPEG or PNG photo",
        )

    # 5. File size check (read at most MAX_UPLOAD_MB + 1 byte)
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    contents = await photo.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image exceeds maximum upload size of {settings.MAX_UPLOAD_MB} MB",
        )

    # 6. Daily cap check
    now_pkt = datetime.now(PKT)
    date_str = now_pkt.strftime("%Y-%m-%d")
    daily_cap = int(os.getenv("DEMO_DAILY_INSPECT_CAP", str(settings.DEMO_DAILY_INSPECT_CAP)))
    store = _get_store()
    allowed = await store.incr_daily_sessions(f"inspect-{date_str}", daily_cap)
    if not allowed:
        logger.warning("daily_inspect_cap_exceeded", extra={"date": date_str, "cap": daily_cap})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily demo inspection cap reached",
        )

    # 7. Get previous inspection for the shelf
    previous = await store.get_latest_inspection("demo_mart", shelf_id)

    # 8. Call inspection function with concurrency limit
    inspect_fn = getattr(app.state, "inspect_fn", inspect_photo)
    try:
        async with _INSPECT_SEMAPHORE:
            result = await inspect_fn(
                contents,
                mart_id="demo_mart",
                shelf_id=shelf_id,
                previous=previous,
                now=now_pkt,
                bin_capacity_kg=bin_capacity_kg,
            )
    except ImageError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a readable image",
        )
    except InspectorError as exc:
        logger.error("inspector_call_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Inspection failed, please try again",
        )

    # 9. Save and return result
    await store.save_inspection(result)
    return result.model_dump(mode="json")


class DecideRequest(BaseModel):
    inspection_id: str
    hours_until_closing: float | None = None
    price_overrides: dict[str, int] | None = None


@app.post("/demo/decide")
async def demo_decide(
    request: Request,
    body: DecideRequest,
    x_demo_access_code: str | None = Header(default=None),
):
    """Executes Ladder decision engine for an inspection (Step 8)."""
    # 1. Access code check
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    # 2. Validation
    if not body.inspection_id or not body.inspection_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="inspection_id is required",
        )
    if not re.match(r"^insp_[a-z0-9_]{1,80}$", body.inspection_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection_id format '{body.inspection_id}', must match ^insp_[a-z0-9_]{{1,80}}$",
        )
    if body.hours_until_closing is not None:
        if not (0.5 <= body.hours_until_closing <= 16.0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hours_until_closing must be between 0.5 and 16.0",
            )
    if body.price_overrides is not None:
        if len(body.price_overrides) > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At most 12 price overrides allowed",
            )
        for key, price in body.price_overrides.items():
            if not re.match(r"^[a-z0-9_]{1,60}$", key):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid key in price_overrides: '{key}', must match ^[a-z0-9_]{{1,60}}$",
                )
            if not (1 <= price <= 100_000):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Price override for '{key}' must be between 1 and 100,000",
                )

    # 3. IP limit bucket 'decide' and daily cap 'decide-{date}'
    settings = get_settings()
    ip_limit = int(os.getenv("DECIDE_IP_LIMIT_PER_HOUR", str(settings.DECIDE_IP_LIMIT_PER_HOUR)))
    await _check_ip_limit(
        request,
        bucket="decide",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} decisions per hour)",
    )

    now_pkt = datetime.now(PKT)
    date_str = now_pkt.strftime("%Y-%m-%d")
    daily_cap = int(os.getenv("DEMO_DAILY_DECIDE_CAP", str(settings.DEMO_DAILY_DECIDE_CAP)))
    store = _get_store()
    allowed = await store.incr_daily_sessions(f"decide-{date_str}", daily_cap)
    if not allowed:
        logger.warning("daily_decide_cap_exceeded", extra={"date": date_str, "cap": daily_cap})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily demo decide cap reached",
        )

    # 4. Inspection lookup
    inspection = await store.get_inspection(body.inspection_id)
    if not inspection or inspection.mart_id != "demo_mart":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspection '{body.inspection_id}' not found for demo_mart",
        )

    # 5. Call decision function
    decide_fn = getattr(app.state, "decide_fn", decide_inspection)
    rules = load_mart_rules("demo_mart")
    try:
        ladder_result = await decide_fn(
            inspection,
            rules=rules,
            store=store,
            now=now_pkt,
            hours_override=body.hours_until_closing,
            price_overrides=body.price_overrides,
        )
    except Exception as exc:
        logger.error("decide_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Decision failed",
        )

    # 6. Save decisions and return
    await store.save_decisions(ladder_result)
    return ladder_result.model_dump(mode="json")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
