"""The call handoff (Module 6): start a call with the next buyer, and read or advance a batch.

`POST /demo/calls` checks, in order: access code, request format, voice configured, per-IP
limit, lookups, batch rules, next buyer, and only then the daily cap, so a refused request
never uses up the cap. The browser then opens the voice WebSocket with the returned token.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from lastcall_api.deps import (
    DEMO_MART_ID,
    batch_calls,
    check_ip_limit,
    consume_daily_cap,
    decision_in,
    demo_rules,
    get_demo_batch,
    get_ladder_result,
    get_store,
    require_access_code,
)
from lastcall_api.orchestration.handoff import NeedsPrice, build_call_record, build_step_plans, initial_quantity
from lastcall_api.orchestration.loop import NextAction, next_action, outside_calling_hours
from lastcall_api.scout.scout import ScoutNotApplicable
from lastcall_shared import ids
from lastcall_shared.clock import mart_now, now_pkt, pickup_by_words
from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    BatchAttempt,
    BatchRecord,
    Branch,
    ItemAssessment,
    LadderDecision,
    MartRules,
    ScoutCandidate,
    ScoutResult,
)
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import CallStore

logger = logging.getLogger("lastcall_api.calls")

CALL_TOKEN_TTL_S = 120
MAX_QUANTITY = 1000

NO_CALL_REASONS = {
    "sold": "This item is sold out",
    "busy": "A call is already in progress for this item",
    "needs_search": "Buyer search needed for this step",
    "next_step": "Calls exhausted for this step; proceed to next step",
    "compost_approval": "No buyers found; manager approval needed for compost",
    "no_buyer": "No buyers found for this item",
}

router = APIRouter(dependencies=[Depends(require_access_code)])


class CreateCallRequest(BaseModel):
    inspection_id: str
    item_key: str
    branch_id: str | None = None
    buyer_id: str | None = None
    quantity: float | None = None
    staff_checked: bool = False


# --- POST /demo/calls ------------------------------------------------------------------------


def _validate(body: CreateCallRequest) -> None:
    def bad(detail: str) -> HTTPException:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if not body.inspection_id or not ids.INSPECTION_ID.match(body.inspection_id.strip()):
        raise bad("Invalid inspection_id")
    if not body.item_key or not ids.ITEM_KEY.match(body.item_key.strip()):
        raise bad("Invalid item_key")
    if body.branch_id is not None and not ids.BRANCH_ID.match(body.branch_id.strip()):
        raise bad("Invalid branch_id")
    if body.buyer_id is not None and not ids.PLACES_BUYER_ID.match(body.buyer_id.strip()):
        raise bad("Invalid buyer_id")
    if body.quantity is not None and not (0 < body.quantity <= MAX_QUANTITY):
        raise bad(f"quantity must be > 0 and <= {MAX_QUANTITY}")


async def _get_item(store: CallStore, inspection_id: str, item_key: str) -> ItemAssessment:
    inspection = await store.get_inspection(inspection_id)
    if not inspection or inspection.mart_id != DEMO_MART_ID:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection not found")
    item = next((it for it in inspection.items if it.item_key == item_key), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inspection item not found")
    return item


def _branch(rules: MartRules, branch_id: str | None) -> Branch:
    try:
        return rules.branch(branch_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown branch_id '{branch_id}'"
        ) from None


async def _get_or_create_batch(
    store: CallStore,
    body: CreateCallRequest,
    decision: LadderDecision,
    clock_offset_s: float,
    item: ItemAssessment,
    rules: MartRules,
    branch: Branch,
    now: datetime,
) -> BatchRecord:
    """An existing batch keeps its plans, quantity and mart time (D54, D74); a new one snapshots them now."""
    inspection_id, item_key = body.inspection_id.strip(), body.item_key.strip()
    batch_id = ids.make_batch_id(inspection_id, item_key, branch.branch_id)
    batch = await store.get_batch(batch_id)
    if batch is not None:
        return batch

    try:
        plans, then_compost = build_step_plans(decision, rules)
    except ScoutNotApplicable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This item stays in store") from None
    except NeedsPrice:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enter the shelf price first") from None
    if decision.on_hold and not body.staff_checked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Waiting for staff check")

    if body.quantity is not None:
        quantity, confirmed = float(body.quantity), True
    else:
        estimate = initial_quantity(item)
        if estimate is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enter the quantity")
        quantity, confirmed = float(estimate), False

    return await store.create_batch(
        BatchRecord(
            batch_id=batch_id,
            mart_id=DEMO_MART_ID,
            inspection_id=inspection_id,
            item_key=item_key,
            item=decision.name,
            unit=decision.unit,
            total_quantity=quantity,
            remaining_quantity=quantity,
            branch_id=branch.branch_id,
            plans=plans,
            then_compost=then_compost,
            quantity_confirmed=confirmed,
            created_at=now,
            clock_offset_s=clock_offset_s,
        )
    )


def _choose_buyer(
    body: CreateCallRequest,
    action: NextAction,
    batch: BatchRecord,
    scout: ScoutResult | None,
    call_statuses: dict[str, str],
) -> ScoutCandidate:
    """The next buyer in rank order, or the one the judge picked ("Play this buyer")."""
    if action.kind != "call":
        reason = NO_CALL_REASONS.get(action.kind, f"No call available ({action.kind})")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)
    if body.buyer_id is None:
        if action.buyer is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No buyer available")
        return action.buyer

    buyer_id = body.buyer_id.strip()
    candidate = next((c for c in (scout.buyers if scout else []) if c.buyer_id == buyer_id), None)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Buyer not on search list")
    step = batch.plans[batch.step_index].step
    called_in_step = {
        a.buyer_id
        for a in batch.attempts
        if a.step == step and call_statuses.get(a.call_id) in ("in_progress", "completed")
    }
    if buyer_id in called_in_step:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Buyer already called in this step")
    return candidate


@router.post("/demo/calls")
async def demo_create_call(request: Request, body: CreateCallRequest, store: CallStore = Depends(get_store)) -> dict:
    _validate(body)
    settings = get_settings()
    if not settings.VOICE_WS_URL:  # before anything is created or counted
        logger.error("voice_ws_url_not_configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Voice service is not configured")
    limit = settings.IP_RATE_LIMIT_PER_HOUR
    await check_ip_limit(request, "call", limit, detail=f"Hourly IP limit reached (max {limit} calls per hour)")

    inspection_id, item_key = body.inspection_id.strip(), body.item_key.strip()
    ladder = await get_ladder_result(store, inspection_id)
    decision = decision_in(ladder, item_key)
    item = await _get_item(store, inspection_id, item_key)
    rules = demo_rules()
    branch = _branch(rules, body.branch_id.strip() if body.branch_id else None)

    now = now_pkt()
    batch = await _get_or_create_batch(store, body, decision, ladder.clock_offset_s, item, rules, branch, now)
    scout = await store.get_scout_result(batch.batch_id)
    _, call_statuses = await batch_calls(store, batch)
    candidate = _choose_buyer(body, next_action(batch, scout, call_statuses, rules, now), batch, scout, call_statuses)

    await consume_daily_cap(store, f"{now:%Y-%m-%d}", settings.DEMO_DAILY_SESSION_CAP, "Daily demo session cap reached")

    plan = batch.plans[batch.step_index]
    call = build_call_record(
        batch=batch, plan=plan, candidate=candidate, decision=decision, rules=rules, branch=branch, now=now
    )
    await store.create_call(call, batch)
    await store.add_batch_attempt(
        batch.batch_id,
        BatchAttempt(
            call_id=call.call_id,
            buyer_id=candidate.buyer_id,
            rank=candidate.rank,
            buyer_type=candidate.buyer_type,
            step=plan.step,
            created_at=now,
        ),
    )
    token = mint(
        call_id=call.call_id,
        nonce=call.session_nonce,
        key=settings.APP_SIGNING_KEY.get_secret_value(),
        ttl=CALL_TOKEN_TTL_S,
        now=now,
    )
    logger.info(
        "demo_call_created",
        extra={"call_id": call.call_id, "batch_id": batch.batch_id, "step": plan.step, "rank": candidate.rank},
    )

    brief = call.brief
    return {
        "call_id": call.call_id,
        "ws_url": settings.VOICE_WS_URL,
        "token": token,
        "batch_id": batch.batch_id,
        "buyer": candidate.public_view(),
        "deal": {
            "item": brief.item,
            "quantity": brief.quantity,
            "unit": brief.quantity_unit,
            "deal_type": brief.deal_type,
            "opening": brief.opening_price_per_unit,
            "floor": brief.floor_price_per_unit,  # shown to the judge; never given to the agent
            # Pickup is by the deadline (D76), worded as the agent and WhatsApp say it: "today, 4:30 PM"
            "pickup_by": pickup_by_words(brief.pickup_deadline, mart_now(batch.clock_offset_s, now)),
            "pickup_deadline": brief.pickup_deadline.isoformat(),
            "mart_name": brief.mart.name,
        },
        "notes": {
            "buyer_closed_now": candidate.open_now is False,
            "outside_calling_hours": outside_calling_hours(rules, mart_now(batch.clock_offset_s, now)),
        },
    }


# --- Batches ------------------------------------------------------------------------------------


async def _batch_view(store: CallStore, batch: BatchRecord, rules: MartRules, now: datetime) -> dict:
    """The batch as the page shows it: stock, plans, every attempt and what happens next. No phones.

    `now` is the real time (locks); the calling-hours note is on the batch's mart time (D74)."""
    scout = await store.get_scout_result(batch.batch_id)
    names = {b.buyer_id: b.name for b in scout.buyers} if scout else {}
    calls, call_statuses = await batch_calls(store, batch)
    action = next_action(batch, scout, call_statuses, rules, now)
    mart_time = mart_now(batch.clock_offset_s, now)

    attempts = []
    for a in batch.attempts:
        call = calls.get(a.call_id)
        result = call.result if call else None
        attempts.append(
            {
                "call_id": a.call_id,
                "buyer_id": a.buyer_id,
                "name": names.get(a.buyer_id, f"Buyer #{a.rank}"),
                "rank": a.rank,
                "type": a.buyer_type,
                "step": a.step,
                "call_status": call.status if call else "pending",
                "outcome": result.outcome if result else None,
                "agreed_price": result.agreed_price_per_unit if result else None,
                "agreed_quantity": result.agreed_quantity if result else None,
                "pickup_time": result.pickup_time.isoformat() if (result and result.pickup_time) else None,
                # The words the call panel and WhatsApp use: "today, 4:30 PM" (D76)
                "pickup_by": pickup_by_words(result.pickup_time, mart_time)
                if (result and result.pickup_time)
                else None,
                "callback_at": result.callback_at.isoformat() if (result and result.callback_at) else None,
                # The call ended mid-conversation with no answer (the voice service then plans a retry,
                # outcome call_back), as opposed to a buyer who asked to be called back
                "dropped": bool(result and "dropped" in result.flags),
            }
        )

    return {
        "batch_id": batch.batch_id,
        "remaining_quantity": batch.remaining_quantity,
        "total_quantity": batch.total_quantity,
        "unit": batch.unit,
        "step_index": batch.step_index,
        "current_step": batch.plans[batch.step_index].step if batch.step_index < len(batch.plans) else None,
        "plans": [p.model_dump() for p in batch.plans],
        "attempts": attempts,
        "next_action": {
            "kind": action.kind,
            "step": action.step,
            "buyer_rank": action.buyer.rank if action.buyer else None,
            # The page matches on the ID; the rank is for display and older pages
            "buyer_id": action.buyer.buyer_id if action.buyer else None,
        },
        "outside_calling_hours": outside_calling_hours(rules, mart_time),
    }


def _valid_batch_id(batch_id: str) -> str:
    batch_id = batch_id.strip()
    if not ids.BATCH_ID.match(batch_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid batch_id format")
    return batch_id


@router.get("/demo/batches/{batch_id}")
async def get_batch(batch_id: str, store: CallStore = Depends(get_store)) -> dict:
    batch = await get_demo_batch(store, _valid_batch_id(batch_id))
    return await _batch_view(store, batch, demo_rules(), now_pkt())


@router.post("/demo/batches/{batch_id}/next-step")
async def advance_batch(batch_id: str, store: CallStore = Depends(get_store)) -> dict:
    """Moves to the next ladder step (e.g. donate) once this step's buyers are used up."""
    batch = await get_demo_batch(store, _valid_batch_id(batch_id))
    rules, now = demo_rules(), now_pkt()
    _, call_statuses = await batch_calls(store, batch)
    action = next_action(batch, await store.get_scout_result(batch.batch_id), call_statuses, rules, now)
    if action.kind != "next_step":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Cannot advance step: next action is '{action.kind}'"
        )
    if not await store.advance_batch_step(batch.batch_id, from_index=batch.step_index):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not advance step; concurrent update")
    return await _batch_view(store, await get_demo_batch(store, batch.batch_id), rules, now)
