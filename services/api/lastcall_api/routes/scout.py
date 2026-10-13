"""POST /demo/scout: the Scout's ranked nearby buyers for one item's current ladder step."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from lastcall_api.deps import check_ip_limit, demo_rules, get_decision, get_store, require_access_code
from lastcall_api.scout.scout import ScoutCapReached, ScoutNotApplicable, ScoutTarget, run_scout
from lastcall_shared import ids
from lastcall_shared.config import get_settings
from lastcall_shared.models import Branch, LadderDecision, MartRules
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.scout")

# Google counts Places quota per Pacific-time day (D49), so the daily cap does too.
PLACES_QUOTA_TZ = ZoneInfo("America/Los_Angeles")

router = APIRouter(dependencies=[Depends(require_access_code)])


class ScoutRequest(BaseModel):
    inspection_id: str
    item_key: str
    branch_id: str | None = None
    refresh: bool = False


def _validate(body: ScoutRequest, rules: MartRules) -> None:
    if not body.inspection_id or not body.inspection_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="inspection_id is required")
    if not ids.INSPECTION_ID.match(body.inspection_id.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid inspection_id format '{body.inspection_id}', must match {ids.INSPECTION_ID.pattern}",
        )
    if not body.item_key or not body.item_key.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="item_key is required")
    if not ids.ITEM_KEY.match(body.item_key.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid item_key format '{body.item_key}', must match {ids.ITEM_KEY.pattern}",
        )
    if body.branch_id is not None:
        if not ids.BRANCH_ID.match(body.branch_id.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid branch_id format '{body.branch_id}', must match {ids.BRANCH_ID.pattern}",
            )
        if body.branch_id not in {b.branch_id for b in rules.branches}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown branch_id '{body.branch_id}'")


async def _target(store: CallStore, body: ScoutRequest, decision: LadderDecision, branch: Branch) -> ScoutTarget:
    """Once calling has started, the batch's current step decides who to look for (D54)."""
    batch = await store.get_batch(ids.make_batch_id(body.inspection_id, body.item_key, branch.branch_id))
    if batch is not None and batch.step_index < len(batch.plans):
        plan = batch.plans[batch.step_index]
        return ScoutTarget(
            inspection_id=body.inspection_id,
            item_key=body.item_key,
            item=decision.name,
            condition=decision.buyer_condition or "",
            step=plan.step,
            buyer_types=tuple(plan.buyer_types),
        )
    try:
        return ScoutTarget.from_decision(decision, body.inspection_id)
    except ScoutNotApplicable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This item stays in store; no buyers needed"
        ) from None


@router.post("/demo/scout")
async def demo_scout(request: Request, body: ScoutRequest, store: CallStore = Depends(get_store)) -> dict:
    """Finds, screens and ranks nearby buyers for a decision item (reused for 1 h unless `refresh`)."""
    rules = demo_rules()
    _validate(body, rules)

    settings = get_settings()
    limit = settings.SCOUT_IP_LIMIT_PER_HOUR
    await check_ip_limit(
        request, "scout", limit, detail=f"Hourly IP limit reached (max {limit} buyer searches per hour)"
    )

    decision = await get_decision(store, body.inspection_id, body.item_key)
    try:
        branch = rules.branch(body.branch_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Buyer search isn't set up for this mart"
        ) from None
    target = await _target(store, body, decision, branch)

    if not body.refresh:
        existing = await store.get_scout_result(ids.make_batch_id(body.inspection_id, body.item_key, branch.branch_id))
        if (
            existing is not None
            and existing.step == target.step
            and list(existing.buyer_types) == list(target.buyer_types)
        ):
            existing.meta.reused = True
            return existing.public_view()

    now = datetime.now(UTC)
    places_counter = f"places-{now.astimezone(PLACES_QUOTA_TZ):%Y-%m-%d}"

    async def reserve_places(amount: int) -> bool:
        return await store.incr_daily_sessions(places_counter, settings.DEMO_DAILY_PLACES_CAP, amount=amount)

    scout_fn = getattr(request.app.state, "scout_fn", run_scout)
    try:
        result = await scout_fn(target, rules=rules, branch=branch, store=store, now=now, reserve_places=reserve_places)
    except ScoutCapReached:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Daily buyer-search limit reached"
        ) from None
    except ScoutNotApplicable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This item stays in store; no buyers needed"
        ) from None
    except Exception as exc:
        logger.error("scout_failed", extra={"error_class": exc.__class__.__name__})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Buyer search failed, please try again"
        ) from exc

    return result.public_view()  # run_scout has saved it
