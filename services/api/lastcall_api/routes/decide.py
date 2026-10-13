"""POST /demo/decide: the Ladder's decision for every item of an inspection."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from lastcall_api.deps import (
    DEMO_MART_ID,
    check_ip_limit,
    consume_daily_cap,
    demo_rules,
    get_store,
    require_access_code,
)
from lastcall_api.ladder.ladder import decide_inspection
from lastcall_shared import ids
from lastcall_shared.clock import now_pkt
from lastcall_shared.config import get_settings
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.decide")

MAX_PRICE_OVERRIDES = 12

router = APIRouter(dependencies=[Depends(require_access_code)])


class DecideRequest(BaseModel):
    inspection_id: str
    hours_until_closing: float | None = None
    price_overrides: dict[str, int] | None = None


def _validate(body: DecideRequest) -> None:
    if not body.inspection_id or not body.inspection_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="inspection_id is required")
    if not ids.INSPECTION_ID.match(body.inspection_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection_id format '{body.inspection_id}', must match {ids.INSPECTION_ID.pattern}",
        )
    if body.hours_until_closing is not None and not (0.5 <= body.hours_until_closing <= 16.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="hours_until_closing must be between 0.5 and 16.0"
        )
    if body.price_overrides is not None:
        if len(body.price_overrides) > MAX_PRICE_OVERRIDES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"At most {MAX_PRICE_OVERRIDES} price overrides allowed",
            )
        for key, price in body.price_overrides.items():
            if not ids.ITEM_KEY.match(key):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid key in price_overrides: '{key}', must match {ids.ITEM_KEY.pattern}",
                )
            if not (1 <= price <= 100_000):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Price override for '{key}' must be between 1 and 100,000",
                )


@router.post("/demo/decide")
async def demo_decide(request: Request, body: DecideRequest, store: CallStore = Depends(get_store)) -> dict:
    """Runs the Ladder decision engine for an inspection."""
    _validate(body)

    settings = get_settings()
    limit = settings.DECIDE_IP_LIMIT_PER_HOUR
    await check_ip_limit(request, "decide", limit, detail=f"Hourly IP limit reached (max {limit} decisions per hour)")
    now = now_pkt()
    await consume_daily_cap(
        store, f"decide-{now:%Y-%m-%d}", settings.DEMO_DAILY_DECIDE_CAP, "Daily demo decide cap reached"
    )

    inspection = await store.get_inspection(body.inspection_id)
    if not inspection or inspection.mart_id != DEMO_MART_ID:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspection '{body.inspection_id}' not found for {DEMO_MART_ID}",
        )

    decide_fn = getattr(request.app.state, "decide_fn", decide_inspection)
    try:
        result = await decide_fn(
            inspection,
            rules=demo_rules(),
            store=store,
            now=now,
            hours_override=body.hours_until_closing,
            price_overrides=body.price_overrides,
        )
    except Exception as exc:
        logger.error("decide_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Decision failed") from exc

    await store.save_decisions(result)
    return result.model_dump(mode="json")
