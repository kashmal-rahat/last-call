"""Shared building blocks for the demo routers: store access, the judge access code,
per-IP and daily limits, and the lookups several endpoints repeat."""

import asyncio
import hmac
import logging
import time

from fastapi import FastAPI, Header, HTTPException, Request, status

from lastcall_api.item_photos import PhotoStore, default_photo_store
from lastcall_shared.config import get_settings
from lastcall_shared.firestore_store import default_store
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import BatchRecord, CallRecord, LadderDecision, LadderResult, MartRules
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.deps")

DEMO_MART_ID = "demo_mart"

# --- Stores (tests and the local preview inject their own through app.state) -------------


def store_for(app: FastAPI) -> CallStore:
    return getattr(app.state, "store", None) or default_store()


def photo_store_for(app: FastAPI) -> PhotoStore | None:
    return getattr(app.state, "photo_store", None) or default_photo_store()


def get_store(request: Request) -> CallStore:
    return store_for(request.app)


def demo_rules() -> MartRules:
    return load_mart_rules(DEMO_MART_ID)


# --- Access code ---------------------------------------------------------------------------


def verify_access_code(provided: str | None) -> bool:
    expected = get_settings().DEMO_ACCESS_CODE or ""
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.strip(), expected.strip())


async def require_access_code(x_demo_access_code: str | None = Header(default=None)) -> None:
    """Route dependency: every judge endpoint needs the demo access code (checked first)."""
    if not verify_access_code(x_demo_access_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access code")


# --- Limits --------------------------------------------------------------------------------

_IP_LIMITER_LOCK = asyncio.Lock()
_IP_REQUEST_HISTORY: dict[tuple[str, str], list[float]] = {}  # (bucket, client_ip) -> request times


async def check_ip_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_s: float = 3600.0,
    detail: str | None = None,
) -> None:
    """Sliding one-hour window per client IP and bucket (per instance; the daily caps are global)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = (
        forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
    )
    now_ts = time.time()
    key = (bucket, client_ip)
    async with _IP_LIMITER_LOCK:
        recent = [t for t in _IP_REQUEST_HISTORY.get(key, []) if now_ts - t < window_s]
        if len(recent) >= limit:
            logger.warning("ip_rate_limit_exceeded", extra={"client_ip": client_ip, "bucket": bucket, "limit": limit})
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail or f"Hourly IP limit reached (max {limit} requests per hour)",
            )
        recent.append(now_ts)
        _IP_REQUEST_HISTORY[key] = recent


async def consume_daily_cap(store: CallStore, counter: str, cap: int, detail: str) -> None:
    """Counts one use against a daily cap shared by all instances; refuses with 429 at the cap.

    Call it last, after every other refusal, so refused requests never use up the cap.
    """
    if not await store.incr_daily_sessions(counter, cap):
        logger.warning("daily_cap_reached", extra={"counter": counter, "cap": cap})
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


# --- Lookups -------------------------------------------------------------------------------


async def get_ladder_result(store: CallStore, inspection_id: str) -> LadderResult:
    result = await store.get_decisions(inspection_id)
    if not result or result.mart_id != DEMO_MART_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Decisions for '{inspection_id}' not found")
    return result


def decision_in(result: LadderResult, item_key: str) -> LadderDecision:
    decision = next((d for d in result.decisions if d.item_key == item_key), None)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No decision for item '{item_key}'")
    return decision


async def get_decision(store: CallStore, inspection_id: str, item_key: str) -> LadderDecision:
    return decision_in(await get_ladder_result(store, inspection_id), item_key)


async def get_demo_batch(store: CallStore, batch_id: str) -> BatchRecord:
    batch = await store.get_batch(batch_id)
    if not batch or batch.mart_id != DEMO_MART_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")
    return batch


async def batch_calls(store: CallStore, batch: BatchRecord) -> tuple[dict[str, CallRecord], dict[str, str]]:
    """The batch's calls by id, and their statuses (what `next_action` needs)."""
    call_ids = [a.call_id for a in batch.attempts]
    calls = await store.get_calls(call_ids) if call_ids else {}
    return calls, {call_id: call.status for call_id, call in calls.items()}
