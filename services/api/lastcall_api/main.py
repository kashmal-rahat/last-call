"""Last Call API service (Milestone 2B Step 11)."""

import asyncio
import hmac
import inspect
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lastcall_api.inspector.images import ImageError
from lastcall_api.inspector.inspector import InspectorError, inspect_photo
from lastcall_api.item_photos import (
    PhotoStore,
    default_photo_store,
    save_shelf_photo,
)
from lastcall_api.item_photos import (
    build_router as build_item_photo_router,
)
from lastcall_api.ladder.ladder import decide_inspection
from lastcall_api.orchestration.handoff import (
    NeedsPrice,
    build_call_record,
    build_step_plans,
    initial_quantity,
)
from lastcall_api.orchestration.loop import next_action
from lastcall_api.scout.scout import (
    ScoutCapReached,
    ScoutNotApplicable,
    ScoutTarget,
    run_scout,
)
from lastcall_shared import ids
from lastcall_shared.clock import PKT
from lastcall_shared.firestore_store import default_store
from lastcall_shared.logging_utils import setup_structured_logging
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import BatchAttempt, BatchRecord, MartRules
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import CallStore

SERVICE_NAME = "api"
VERSION = "0.1.0"

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
    client_ip = (
        forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
    )
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

    demo_code_present = bool((settings.DEMO_ACCESS_CODE or "").strip())
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


@app.middleware("http")
async def add_cache_control_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/demo" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Mount static files directory
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _get_store() -> CallStore:
    return getattr(app.state, "store", None) or default_store()


@lru_cache
def _default_photo_store() -> PhotoStore | None:
    return default_photo_store()


def _get_photo_store() -> PhotoStore | None:
    return getattr(app.state, "photo_store", None) or _default_photo_store()


def _verify_access_code(provided_code: str | None) -> bool:
    expected_code = get_settings().DEMO_ACCESS_CODE or ""
    if not expected_code or not provided_code:
        return False
    return hmac.compare_digest(provided_code.strip(), expected_code.strip())


@app.get("/health")
@app.get("/healthz")
async def healthz():
    return {
        "service": SERVICE_NAME,
        "version": VERSION,
        "commit": get_settings().GIT_COMMIT,
        "status": "healthy",
    }


@app.get("/demo")
async def get_demo_page():
    """Serves the static judge demo page."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Demo page not found")
    return FileResponse(html_path)


class CreateCallRequest(BaseModel):
    inspection_id: str
    item_key: str
    branch_id: str | None = None
    buyer_id: str | None = None
    quantity: float | None = None
    staff_checked: bool = False


async def _build_batch_response(
    batch: BatchRecord,
    store: CallStore,
    rules: MartRules,
    now_pkt: datetime,
) -> dict:
    scout = await store.get_scout_result(batch.batch_id)
    scout_buyers = {b.buyer_id: b for b in scout.buyers} if scout else {}

    attempt_call_ids = [a.call_id for a in batch.attempts]
    calls = await store.get_calls(attempt_call_ids) if attempt_call_ids else {}
    call_statuses = {cid: c.status for cid, c in calls.items()}

    act = next_action(batch, scout, call_statuses, rules, now_pkt)

    attempts_data = []
    for a in batch.attempts:
        call = calls.get(a.call_id)
        candidate = scout_buyers.get(a.buyer_id)
        name = candidate.name if candidate else f"Buyer #{a.rank}"
        call_status = call.status if call else "pending"
        res = call.result if call else None
        attempts_data.append(
            {
                "call_id": a.call_id,
                "buyer_id": a.buyer_id,
                "name": name,
                "rank": a.rank,
                "type": a.buyer_type,
                "step": a.step,
                "call_status": call_status,
                "outcome": res.outcome if res else None,
                "agreed_price": res.agreed_price_per_unit if res else None,
                "agreed_quantity": res.agreed_quantity if res else None,
                "pickup_time": res.pickup_time.isoformat() if (res and res.pickup_time) else None,
                "callback_at": res.callback_at.isoformat() if (res and res.callback_at) else None,
            }
        )

    outside = False
    if rules.calling_hours:
        ch_tz = ZoneInfo(rules.calling_hours.timezone)
        now_ch_time = now_pkt.astimezone(ch_tz).time()
        outside = not (rules.calling_hours.start <= now_ch_time < rules.calling_hours.end)

    current_step = batch.plans[batch.step_index].step if batch.step_index < len(batch.plans) else None

    return {
        "batch_id": batch.batch_id,
        "remaining_quantity": batch.remaining_quantity,
        "total_quantity": batch.total_quantity,
        "unit": batch.unit,
        "step_index": batch.step_index,
        "current_step": current_step,
        "plans": [p.model_dump() for p in batch.plans],
        "attempts": attempts_data,
        "next_action": {
            "kind": act.kind,
            "step": act.step,
            "buyer_rank": act.buyer.rank if act.buyer else None,
        },
        "outside_calling_hours": outside,
    }


@app.post("/demo/calls")
async def demo_create_call(
    body: CreateCallRequest,
    request: Request,
    x_demo_access_code: str | None = Header(default=None),
):
    # 1. Access code
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    # 2. Validation
    if not body.inspection_id or not ids.INSPECTION_ID.match(body.inspection_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid inspection_id")
    if not body.item_key or not ids.ITEM_KEY.match(body.item_key.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid item_key")
    if body.branch_id is not None and not ids.BRANCH_ID.match(body.branch_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid branch_id")
    if body.buyer_id is not None and not ids.PLACES_BUYER_ID.match(body.buyer_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid buyer_id")
    if body.quantity is not None and not (0 < body.quantity <= 1000):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="quantity must be > 0 and <= 1000")

    # 3. IP bucket "call"
    settings = get_settings()
    if not settings.VOICE_WS_URL:  # checked before anything is created or counted
        logger.error("voice_ws_url_not_configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice service is not configured")
    ip_limit = settings.IP_RATE_LIMIT_PER_HOUR
    await _check_ip_limit(
        request,
        bucket="call",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} calls per hour)",
    )

    # 4. Lookups
    store = _get_store()
    ladder_result = await store.get_decisions(body.inspection_id.strip())
    if not ladder_result or ladder_result.mart_id != "demo_mart":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decisions not found")
    decision = next((d for d in ladder_result.decisions if d.item_key == body.item_key.strip()), None)
    if not decision:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decision not found")

    inspection = await store.get_inspection(body.inspection_id.strip())
    if not inspection or inspection.mart_id != "demo_mart":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    item = next((it for it in inspection.items if it.item_key == body.item_key.strip()), None)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection item not found")

    # 5. Branch & batch_id
    rules = load_mart_rules("demo_mart")
    try:
        branch = rules.branch(body.branch_id.strip() if body.branch_id else None)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown branch_id '{body.branch_id}'"
        ) from None

    batch_id = ids.make_batch_id(body.inspection_id.strip(), body.item_key.strip(), branch.branch_id)

    # 6. Batch handling
    now_pkt = datetime.now(PKT)
    batch = await store.get_batch(batch_id)
    if batch is None:
        try:
            plans, then_compost = build_step_plans(decision, rules)
        except ScoutNotApplicable:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This item stays in store") from None
        except NeedsPrice:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enter the shelf price first") from None

        if decision.on_hold and not body.staff_checked:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Waiting for staff check")

        if body.quantity is not None:
            qty = float(body.quantity)
            qty_confirmed = True
        else:
            init_qty = initial_quantity(item)
            if init_qty is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enter the quantity")
            qty = float(init_qty)
            qty_confirmed = False

        batch = BatchRecord(
            batch_id=batch_id,
            mart_id="demo_mart",
            inspection_id=body.inspection_id.strip(),
            item_key=body.item_key.strip(),
            item=decision.name,
            unit=decision.unit,
            total_quantity=qty,
            remaining_quantity=qty,
            branch_id=branch.branch_id,
            plans=plans,
            then_compost=then_compost,
            quantity_confirmed=qty_confirmed,
            created_at=now_pkt,
        )
        batch = await store.create_batch(batch)

    # 7. Scout result, attempts calls, next_action
    scout = await store.get_scout_result(batch_id)
    attempt_call_ids = [a.call_id for a in batch.attempts]
    calls = await store.get_calls(attempt_call_ids) if attempt_call_ids else {}
    call_statuses = {cid: c.status for cid, c in calls.items()}

    action = next_action(batch, scout, call_statuses, rules, now_pkt)
    if action.kind != "call":
        detail_msgs = {
            "sold": "This item is sold out",
            "busy": "A call is already in progress for this item",
            "needs_search": "Buyer search needed for this step",
            "next_step": "Calls exhausted for this step; proceed to next step",
            "compost_approval": "No buyers found; manager approval needed for compost",
            "no_buyer": "No buyers found for this item",
        }
        msg = detail_msgs.get(action.kind, f"No call available ({action.kind})")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)

    # Determine candidate
    if body.buyer_id is not None:
        candidates = scout.buyers if scout else []
        candidate = next((c for c in candidates if c.buyer_id == body.buyer_id.strip()), None)
        if not candidate:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Buyer not on search list")
        current_plan = batch.plans[batch.step_index]
        called_in_step = {
            a.buyer_id
            for a in batch.attempts
            if a.step == current_plan.step and call_statuses.get(a.call_id) in ("in_progress", "completed")
        }
        if body.buyer_id.strip() in called_in_step:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Buyer already called in this step")
    else:
        candidate = action.buyer
        if not candidate:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No buyer available")

    # 8. Daily session cap check
    date_str = now_pkt.strftime("%Y-%m-%d")
    daily_cap = settings.DEMO_DAILY_SESSION_CAP
    allowed = await store.incr_daily_sessions(date_str, daily_cap)
    if not allowed:
        logger.warning("daily_demo_cap_exceeded", extra={"date": date_str, "cap": daily_cap})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily demo session cap reached",
        )

    # 9. Build record, create call, add attempt, mint token
    plan = batch.plans[batch.step_index]
    call_rec = build_call_record(
        batch=batch,
        plan=plan,
        candidate=candidate,
        decision=decision,
        rules=rules,
        branch=branch,
        now=now_pkt,
    )
    await store.create_call(call_rec, batch)

    attempt = BatchAttempt(
        call_id=call_rec.call_id,
        buyer_id=candidate.buyer_id,
        rank=candidate.rank,
        buyer_type=candidate.buyer_type,
        step=plan.step,
        created_at=now_pkt,
    )
    await store.add_batch_attempt(batch.batch_id, attempt)

    signing_key = settings.APP_SIGNING_KEY.get_secret_value() if settings.APP_SIGNING_KEY else ""
    token = mint(call_id=call_rec.call_id, nonce=call_rec.session_nonce, key=signing_key, ttl=120, now=now_pkt)
    voice_ws_url = settings.VOICE_WS_URL

    outside = False
    if rules.calling_hours:
        ch_tz = ZoneInfo(rules.calling_hours.timezone)
        now_ch_time = now_pkt.astimezone(ch_tz).time()
        outside = not (rules.calling_hours.start <= now_ch_time < rules.calling_hours.end)

    logger.info(
        "demo_call_created",
        extra={
            "call_id": call_rec.call_id,
            "batch_id": batch.batch_id,
            "step": plan.step,
            "rank": candidate.rank,
        },
    )

    return {
        "call_id": call_rec.call_id,
        "ws_url": voice_ws_url,
        "token": token,
        "batch_id": batch.batch_id,
        "buyer": candidate.public_view(),
        "deal": {
            "item": call_rec.brief.item,
            "quantity": call_rec.brief.quantity,
            "unit": call_rec.brief.quantity_unit,
            "deal_type": call_rec.brief.deal_type,
            "opening": call_rec.brief.opening_price_per_unit,
            "floor": call_rec.brief.floor_price_per_unit,
            "pickup_window": call_rec.brief.pickup_window,
            "pickup_deadline": call_rec.brief.pickup_deadline.isoformat(),
            "mart_name": call_rec.brief.mart.name,
        },
        "notes": {
            "buyer_closed_now": bool(candidate.open_now is False),
            "outside_calling_hours": outside,
        },
    }


@app.get("/demo/batches/{batch_id}")
async def get_demo_batch(
    batch_id: str,
    x_demo_access_code: str | None = Header(default=None),
):
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    if not ids.BATCH_ID.match(batch_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid batch_id format")

    store = _get_store()
    batch = await store.get_batch(batch_id.strip())
    if not batch or batch.mart_id != "demo_mart":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    rules = load_mart_rules("demo_mart")
    now_pkt = datetime.now(PKT)
    return await _build_batch_response(batch, store, rules, now_pkt)


@app.post("/demo/batches/{batch_id}/next-step")
async def demo_batch_next_step(
    batch_id: str,
    x_demo_access_code: str | None = Header(default=None),
):
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    if not ids.BATCH_ID.match(batch_id.strip()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid batch_id format")

    store = _get_store()
    batch = await store.get_batch(batch_id.strip())
    if not batch or batch.mart_id != "demo_mart":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    scout = await store.get_scout_result(batch_id.strip())
    attempt_call_ids = [a.call_id for a in batch.attempts]
    calls = await store.get_calls(attempt_call_ids) if attempt_call_ids else {}
    call_statuses = {cid: c.status for cid, c in calls.items()}

    now_pkt = datetime.now(PKT)
    rules = load_mart_rules("demo_mart")
    act = next_action(batch, scout, call_statuses, rules, now_pkt)

    if act.kind != "next_step":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot advance step: next action is '{act.kind}'",
        )

    advanced = await store.advance_batch_step(batch_id.strip(), from_index=batch.step_index)
    if not advanced:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not advance step; concurrent update",
        )

    updated_batch = await store.get_batch(batch_id.strip())
    if not updated_batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    return await _build_batch_response(updated_batch, store, rules, now_pkt)


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
    if not ids.SHELF_ID.match(shelf_id):
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
    ip_limit = settings.IP_RATE_LIMIT_PER_HOUR
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
    daily_cap = settings.DEMO_DAILY_INSPECT_CAP
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
    inspect_kwargs: dict[str, object] = {
        "mart_id": "demo_mart",
        "shelf_id": shelf_id,
        "previous": previous,
        "now": now_pkt,
        "bin_capacity_kg": bin_capacity_kg,
    }
    sig = inspect.signature(inspect_fn)
    if "reading_cache" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    ):
        inspect_kwargs["reading_cache"] = store

    try:
        async with _INSPECT_SEMAPHORE:
            result = await inspect_fn(contents, **inspect_kwargs)
    except ImageError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a readable image",
        ) from None
    except InspectorError as exc:
        logger.error("inspector_call_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Inspection failed, please try again",
        ) from exc

    # 9. Keep the shelf photo for item photos (D62, best effort), then save and return the result
    if await save_shelf_photo(_get_photo_store(), result.inspection_id, contents):
        result = result.model_copy(update={"photo_stored": True})
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
    if not ids.INSPECTION_ID.match(body.inspection_id.strip()):
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
            if not ids.ITEM_KEY.match(key):
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
    ip_limit = settings.DECIDE_IP_LIMIT_PER_HOUR
    await _check_ip_limit(
        request,
        bucket="decide",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} decisions per hour)",
    )

    now_pkt = datetime.now(PKT)
    date_str = now_pkt.strftime("%Y-%m-%d")
    daily_cap = settings.DEMO_DAILY_DECIDE_CAP
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
        ) from exc

    # 6. Save decisions and return
    await store.save_decisions(ladder_result)
    return ladder_result.model_dump(mode="json")


class ScoutRequest(BaseModel):
    inspection_id: str
    item_key: str
    branch_id: str | None = None
    refresh: bool = False


@app.get("/demo/branches")
async def get_demo_branches():
    """Returns available branches for demo_mart without coordinates (Step 9)."""
    rules = load_mart_rules("demo_mart")
    return {
        "branches": [
            {
                "branch_id": b.branch_id,
                "name": b.name,
                "location": b.location,
            }
            for b in rules.branches
        ],
        "default_branch_id": rules.default_branch_id,
    }


@app.post("/demo/scout")
async def demo_scout(
    request: Request,
    body: ScoutRequest,
    x_demo_access_code: str | None = Header(default=None),
):
    """Executes buyer scout pipeline for a decision item (Step 9)."""
    # 1. Access code check
    if not _verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")

    # 2. Validation
    if not body.inspection_id or not body.inspection_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="inspection_id is required",
        )
    if not ids.INSPECTION_ID.match(body.inspection_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection_id format '{body.inspection_id}', must match ^insp_[a-z0-9_]{{1,80}}$",
        )
    if not body.item_key or not body.item_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="item_key is required",
        )
    if not ids.ITEM_KEY.match(body.item_key.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid item_key format '{body.item_key}', must match ^[a-z0-9_]{{1,60}}$",
        )
    rules = load_mart_rules("demo_mart")
    if body.branch_id is not None:
        if not ids.BRANCH_ID.match(body.branch_id.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid branch_id format '{body.branch_id}', must match ^[a-z0-9_]{{1,30}}$",
            )
        known_branch_ids = {b.branch_id for b in rules.branches}
        if body.branch_id not in known_branch_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown branch_id '{body.branch_id}'",
            )

    # 3. IP limit bucket 'scout'
    settings = get_settings()
    ip_limit = settings.SCOUT_IP_LIMIT_PER_HOUR
    await _check_ip_limit(
        request,
        bucket="scout",
        limit=ip_limit,
        detail=f"Hourly IP limit reached (max {ip_limit} buyer searches per hour)",
    )

    # 4. Decision lookup
    store = _get_store()
    ladder_result = await store.get_decisions(body.inspection_id)
    if not ladder_result or ladder_result.mart_id != "demo_mart":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decisions for inspection '{body.inspection_id}' not found",
        )

    decision = next((d for d in ladder_result.decisions if d.item_key == body.item_key), None)
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision for item_key '{body.item_key}' not found in inspection '{body.inspection_id}'",
        )

    # 5. Target and branch resolution
    try:
        branch = rules.branch(body.branch_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Buyer search isn't set up for this mart",
        ) from None

    batch_id = ids.make_batch_id(body.inspection_id, body.item_key, branch.branch_id)
    batch = await store.get_batch(batch_id)
    if batch is not None and batch.step_index < len(batch.plans):
        current_plan = batch.plans[batch.step_index]
        target = ScoutTarget(
            inspection_id=body.inspection_id,
            item_key=body.item_key,
            item=decision.name,
            condition=decision.buyer_condition or "",
            step=current_plan.step,
            buyer_types=tuple(current_plan.buyer_types),
        )
    else:
        try:
            target = ScoutTarget.from_decision(decision, body.inspection_id)
        except ScoutNotApplicable:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This item stays in store; no buyers needed",
            ) from None

    # 6. Reuse within 1h (freshness check)
    key = f"{body.inspection_id}__{body.item_key}__{branch.branch_id}"
    if not body.refresh:
        existing = await store.get_scout_result(key)
        if (
            existing is not None
            and existing.step == target.step
            and list(existing.buyer_types) == list(target.buyer_types)
        ):
            existing.meta.reused = True
            return existing.public_view()

    # 7. Execute scout pipeline
    scout_fn = getattr(app.state, "scout_fn", run_scout)
    now_utc = datetime.now(timezone.utc)
    pacific_tz = ZoneInfo("America/Los_Angeles")
    pacific_date = now_utc.astimezone(pacific_tz).strftime("%Y-%m-%d")
    daily_cap = settings.DEMO_DAILY_PLACES_CAP

    async def reserve_places(amount: int) -> bool:
        counter_key = f"places-{pacific_date}"
        return await store.incr_daily_sessions(counter_key, daily_cap, amount=amount)

    try:
        scout_result = await scout_fn(
            target,
            rules=rules,
            branch=branch,
            store=store,
            now=now_utc,
            reserve_places=reserve_places,
        )
    except ScoutCapReached:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily buyer-search limit reached",
        ) from None
    except ScoutNotApplicable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item stays in store; no buyers needed",
        ) from None
    except Exception as exc:
        logger.error("scout_failed", extra={"error_class": exc.__class__.__name__})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Buyer search failed, please try again",
        ) from exc

    # 8. Return public view (run_scout already saved to store)
    return scout_result.public_view()


# Item photos (D62): signed crops the agent sends to buyers.
app.include_router(build_item_photo_router(get_store=_get_store, get_photo_store=_get_photo_store))

# Phone demo (Module 9): separate router; every endpoint is 404 unless PHONE_DEMO_ENABLED=true.
from lastcall_api.phone_demo import build_router as build_phone_router
from lastcall_api.phone_demo import dial_twilio

app.include_router(
    build_phone_router(
        verify_access_code=_verify_access_code,
        get_store=_get_store,
        check_ip_limit=_check_ip_limit,
        get_dialer=lambda: getattr(app.state, "phone_dialer", dial_twilio),
    )
)


if __name__ == "__main__":
    import uvicorn

    port = get_settings().PORT
    uvicorn.run(app, host="0.0.0.0", port=port)
