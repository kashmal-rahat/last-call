"""Handoff helpers: step plans, pickup window, and CallRecord creation (Milestone 6A Step 3).

Pure functions converting ladder decisions and scout candidates into batch step plans
and role-play call records.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from lastcall_api.ladder.engine import offer_quantity, step_prices
from lastcall_api.scout.rank import sanitise_name
from lastcall_api.scout.scout import ScoutNotApplicable
from lastcall_shared import ids
from lastcall_shared.buyer_keys import mask_phone
from lastcall_shared.clock import time_words
from lastcall_shared.models import (
    BatchRecord,
    Branch,
    BuyerInfo,
    BuyerType,
    CallRecord,
    DealBrief,
    ItemAssessment,
    LadderDecision,
    MartInfo,
    MartRules,
    NegotiationPolicy,
    ScoutCandidate,
    ScoutStep,
    StepPlan,
    init_negotiation,
)

PICKUP_HOURS = 4.0


class NeedsPrice(Exception):
    """Raised when an item needs a shelf price before calling buyers."""


def build_step_plans(decision: LadderDecision, rules: MartRules) -> tuple[list[StepPlan], bool]:
    """Builds step plans and determines if compost follows.

    Returns:
        (plans, then_compost)
    """
    scout_steps = {"bulk_sale", "donate", "animal_feed"}
    if decision.step not in scout_steps:
        raise ScoutNotApplicable(f"Decision step '{decision.step}' is not a scout step")

    if decision.needs_price:
        raise NeedsPrice(f"Shelf price needed for item '{decision.name}'")

    steps_to_plan: list[ScoutStep] = [decision.step]  # type: ignore[list-item]
    for s in decision.next_steps:
        if s in scout_steps:
            steps_to_plan.append(s)  # type: ignore[arg-type]

    then_compost = "compost" in decision.next_steps

    plans: list[StepPlan] = []
    for s in steps_to_plan:
        if s == "bulk_sale":
            buyer_types: list[BuyerType] = list(decision.buyer_types)
            opening, floor = step_prices("bulk_sale", decision.shelf_price, rules)
        elif s == "donate":
            buyer_types = ["charity"]
            opening, floor = 0, 0
        elif s == "animal_feed":
            buyer_types = ["dairy_farm"]
            opening, floor = step_prices("animal_feed", decision.shelf_price, rules)
        else:
            buyer_types = []
            opening, floor = 0, 0

        plans.append(
            StepPlan(
                step=s,
                buyer_types=buyer_types,
                opening_price=opening,
                floor_price=floor,
            )
        )

    return plans, then_compost


def initial_quantity(item: ItemAssessment) -> float | None:
    """The quantity a new batch offers when staff haven't entered one: the Ladder's rule (`offer_quantity`,
    D71), the same amount the decision shows on the page."""
    return offer_quantity(item.quantity)


def pickup_window(rules: MartRules, now: datetime) -> tuple[datetime, datetime]:
    """Calculates pickup window (start, deadline) in the mart timezone (D56).

    If the mart is open with at least bulk_pickup_hours left, pickup runs from now
    to min(now + 4 h, closing); otherwise from the next opening to opening + 4 h.
    """
    tz = ZoneInfo(rules.timezone)
    now_local = now.astimezone(tz)

    today_open = now_local.replace(
        hour=rules.opening_time.hour,
        minute=rules.opening_time.minute,
        second=0,
        microsecond=0,
    )
    today_close = now_local.replace(
        hour=rules.closing_time.hour,
        minute=rules.closing_time.minute,
        second=0,
        microsecond=0,
    )

    if today_open <= now_local < today_close:
        hours_left = (today_close - now_local).total_seconds() / 3600.0
        if hours_left >= rules.bulk_pickup_hours:
            start = now_local
            deadline = min(now_local + timedelta(hours=PICKUP_HOURS), today_close)
            return start, deadline

        # Less than bulk_pickup_hours remaining before closing -> tomorrow opening
        next_open = today_open + timedelta(days=1)
        deadline = next_open + timedelta(hours=PICKUP_HOURS)
        return next_open, deadline
    elif now_local < today_open:
        # Before opening today -> today opening
        next_open = today_open
        deadline = next_open + timedelta(hours=PICKUP_HOURS)
        return next_open, deadline
    else:
        # After closing today -> tomorrow opening
        next_open = today_open + timedelta(days=1)
        deadline = next_open + timedelta(hours=PICKUP_HOURS)
        return next_open, deadline


def build_call_record(
    *,
    batch: BatchRecord,
    plan: StepPlan,
    candidate: ScoutCandidate,
    decision: LadderDecision,
    rules: MartRules,
    branch: Branch,
    now: datetime,
) -> CallRecord:
    """Constructs a CallRecord for a browser role-play call."""
    call_id = ids.new_call_id()
    nonce = uuid.uuid4().hex

    start, deadline = pickup_window(rules, now)
    window_str = f"{time_words(start)} to {time_words(deadline)}"

    raw_buyer = candidate.to_buyer_info()
    buyer = BuyerInfo(
        buyer_id=raw_buyer.buyer_id,
        name=sanitise_name(raw_buyer.name),
        type=raw_buyer.type,
        phone=mask_phone(raw_buyer.phone),
    )

    deal_type = "donation" if plan.step == "donate" else "sale"

    brief = DealBrief(
        mart_id=batch.mart_id,
        batch_id=batch.batch_id,
        call_id=call_id,
        deal_type=deal_type,
        item=decision.name,
        condition=decision.buyer_condition,
        quantity=batch.remaining_quantity,
        quantity_unit=decision.unit,
        quantity_confirmed_by_staff=batch.quantity_confirmed,
        buyer=buyer,
        opening_price_per_unit=plan.opening_price,
        opening_price_unit=decision.unit,
        floor_price_per_unit=plan.floor_price,
        floor_price_unit=decision.unit,
        market_rate_per_unit=decision.shelf_price,
        currency="PKR",
        pickup_window=window_str,
        pickup_deadline=deadline,
        mart=MartInfo(name=branch.name, location=branch.location),
        payment_terms=rules.payment_terms,
        language="ur",
        calling_hours=rules.calling_hours,
    )

    policy = NegotiationPolicy()
    negotiation = init_negotiation(brief, policy)

    now_utc = now if now.tzinfo else now.replace(tzinfo=ZoneInfo("UTC"))
    if candidate.buyer_id.startswith("places:"):
        expire_at = now_utc + timedelta(hours=24)
    else:
        expire_at = now_utc + timedelta(days=30)

    return CallRecord(
        call_id=call_id,
        mart_id=batch.mart_id,
        batch_id=batch.batch_id,
        brief=brief,
        policy=policy,
        negotiation=negotiation,
        status="pending",
        session_nonce=nonce,
        created_at=now_utc,
        expire_at=expire_at,
        channel="browser",
        city_style=rules.city_style,
    )
