"""Pure orchestration loop (Milestone 6A Step 4).

next_action determines the next action for a batch based on current stock,
lock status, scout results, and past call attempts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from lastcall_shared.models import (
    BatchRecord,
    MartRules,
    ScoutCandidate,
    ScoutResult,
    ScoutStep,
)


@dataclass(frozen=True)
class NextAction:
    kind: Literal[
        "call",
        "busy",
        "needs_search",
        "next_step",
        "compost_approval",
        "no_buyer",
        "sold",
    ]
    step: ScoutStep | None = None
    buyer: ScoutCandidate | None = None


def next_action(
    batch: BatchRecord,
    scout: ScoutResult | None,
    call_status: dict[str, str],
    rules: MartRules,
    now: datetime,
) -> NextAction:
    """Evaluates batch state and returns the next action in priority order."""
    # 1. remaining_quantity <= 0 → sold
    if batch.remaining_quantity <= 0:
        return NextAction(kind="sold")

    # 2. Locked with locked_until > now → busy
    if batch.locked_until:
        now_cmp = now if now.tzinfo else now.replace(tzinfo=batch.locked_until.tzinfo)
        if batch.locked_until > now_cmp:
            return NextAction(kind="busy")

    # If steps are already out of range
    if batch.step_index >= len(batch.plans):
        if batch.then_compost:
            return NextAction(kind="compost_approval")
        return NextAction(kind="no_buyer")

    # 3. plan = plans[step_index]. called = buyer IDs of in_progress/completed calls in this step
    plan = batch.plans[batch.step_index]
    called: set[str] = set()
    for attempt in batch.attempts:
        if attempt.step == plan.step:
            status = call_status.get(attempt.call_id)
            if status in ("in_progress", "completed"):
                called.add(attempt.buyer_id)

    def _steps_used_up() -> NextAction:
        # Rule 7: if another step exists → next_step; else if then_compost → compost_approval; else no_buyer
        if batch.step_index + 1 < len(batch.plans):
            next_plan = batch.plans[batch.step_index + 1]
            return NextAction(kind="next_step", step=next_plan.step)
        if batch.then_compost:
            return NextAction(kind="compost_approval")
        return NextAction(kind="no_buyer")

    # 4. If len(called) >= scout_max_buyers, go to rule 7
    if len(called) >= rules.scout_max_buyers:
        return _steps_used_up()

    # 5. If scout is None, or scout.step != plan.step, or its buyer_types differ → needs_search
    if scout is None or scout.step != plan.step or set(scout.buyer_types) != set(plan.buyer_types):
        return NextAction(kind="needs_search", step=plan.step)

    # 6. The first buyer in rank order who isn't in called → call. If none, go to rule 7
    for buyer in scout.buyers:
        if buyer.buyer_id not in called:
            return NextAction(kind="call", step=plan.step, buyer=buyer)

    # If there is none (including an empty list) → go to rule 7
    return _steps_used_up()
