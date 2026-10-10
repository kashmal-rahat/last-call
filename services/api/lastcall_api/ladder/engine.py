"""Pure decision engine for produce clearance (Module 3).

Gemini knows, code decides:
- Produce knowledge comes from ProduceProfile.
- Pricing rules come from MartRules.
- The decision engine is pure code: no Gemini calls, no I/O, no randomness.
- Never branches on produce names.
"""

from datetime import datetime, timedelta
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

from lastcall_api.inspector.guardrails import names_match
from lastcall_api.ladder.keys import produce_key
from lastcall_shared.models import (
    BuyerType,
    ItemAssessment,
    LadderDecision,
    LadderStep,
    MartRules,
    ProduceProfile,
    ProduceStage,
    ShelfLifeBand,
    StaffAction,
    StageLevel,
    Unit,
)

BAND_HOURS: dict[ShelfLifeBand, float] = {
    "under_6h": 4.0,
    "6_to_24h": 15.0,
    "1_to_3_days": 48.0,
    "over_3_days": 96.0,
}

LEVEL_FACTOR: dict[StageLevel, float] = {
    "early": 1.0,
    "mid": 0.7,
    "late": 0.4,
}

LADDER_ORDER: list[LadderStep] = [
    "keep",
    "discount",
    "bulk_sale",
    "donate",
    "animal_feed",
    "compost",
]

SEVERE_ISSUES = {"mould", "slime", "rot", "leaking", "pest_damage"}


def allowed_steps(item: ItemAssessment) -> list[LadderStep]:
    """Returns permitted ladder steps based strictly on typical stage and issues."""
    stage = item.stage
    if stage == "fresh":
        return ["keep", "discount"]
    if stage == "ripening":
        return ["keep", "discount", "bulk_sale"]
    if stage == "overripe":
        return ["discount", "bulk_sale", "donate", "animal_feed"]
    if stage == "spoiled":
        if "mould" in item.issues or "slime" in item.issues:
            return ["compost"]
        return ["animal_feed", "compost"]
    if stage == "unsafe":
        return ["compost"]
    return ["compost"]


def round_to(x: float, base: int = 5) -> int:
    """Rounds to nearest multiple of base (half-up)."""
    return int(math.floor((x / base) + 0.5)) * base


def ceil_to(x: float, base: int = 5) -> int:
    """Rounds up to next multiple of base."""
    return int(math.ceil(x / base)) * base


def find_price(rules: MartRules, name: str, unit: Unit) -> int | None:
    """Finds shelf price in rules.prices matching aliases using names_match."""
    for entry in rules.prices:
        for alias in entry.names:
            if names_match(name, alias):
                if unit in entry.prices:
                    return entry.prices[unit]
    return None


def hours_until_closing(rules: MartRules, now: datetime, override: float | None = None) -> float:
    """Calculates hours from now to next closing time in mart timezone."""
    if override is not None:
        return float(override)

    tz = ZoneInfo(rules.timezone)
    now_local = now.astimezone(tz)
    closing_dt = now_local.replace(
        hour=rules.closing_time.hour,
        minute=rules.closing_time.minute,
        second=rules.closing_time.second,
        microsecond=0,
    )
    if now_local >= closing_dt:
        closing_dt += timedelta(days=1)

    diff_s = (closing_dt - now_local).total_seconds()
    hours = diff_s / 3600.0
    return max(0.1, min(24.0, hours))


def compute_sellable_hours(item: ItemAssessment, profile: ProduceProfile) -> float | None:
    """Computes expected sellable shelf-life hours for the item's stage and level."""
    if item.stage in ("spoiled", "unsafe"):
        return None

    stage_profile = getattr(profile, item.stage, None)
    if stage_profile is None:
        return None

    band = stage_profile.sellable_for
    factor = LEVEL_FACTOR.get(item.stage_level, 0.7)
    return BAND_HOURS.get(band, 15.0) * factor


def decide_item(
    item: ItemAssessment,
    profile: ProduceProfile,
    rules: MartRules,
    H: float,
    price: int | None,
) -> LadderDecision:
    """Makes a pure deterministic clearance decision for a single assessed produce item."""
    allowed = allowed_steps(item)
    sellable_h = compute_sellable_hours(item, profile)
    life = sellable_h if sellable_h is not None else 0.0

    # Determine stage uses
    if item.stage == "fresh":
        uses = profile.fresh
        cattle_ok = False
    elif item.stage == "ripening":
        uses = profile.ripening
        cattle_ok = False
    elif item.stage == "overripe":
        uses = profile.overripe
        cattle_ok = profile.overripe_ok_for_cattle
    elif item.stage == "spoiled":
        uses = None
        cattle_ok = profile.spoiled_ok_for_cattle
    else:  # unsafe
        uses = None
        cattle_ok = False

    recheck_next_photo = False
    staff_actions: list[StaffAction] = []
    chosen_step: LadderStep
    discount_pct: int | None = None
    reason: str

    # Case A: it still sells after tomorrow's opening
    if life >= H + rules.overnight_hours:
        if "keep" in allowed:
            chosen_step = "keep"
            recheck_next_photo = True
            reason = f"{item.name.capitalize()}, {item.stage}: sells for about {life:.0f} h; lasts past tomorrow opening → keep on shelf"
        else:
            chosen_step = "discount"
            discount_pct = rules.min_discount_pct
            recheck_next_photo = True
            reason = f"{item.name.capitalize()}, {item.stage}: sells for about {life:.0f} h; lasts past opening but overripe → {discount_pct}% off"

    # Case B: it lasts until closing but not through tomorrow
    elif H <= life < H + rules.overnight_hours:
        if "keep" in allowed and H > rules.discount_window_hours:
            chosen_step = "keep"
            recheck_next_photo = True
            reason = f"{item.name.capitalize()}, {item.stage}: sells for about {life:.0f} h; lasts until closing; discount decided closer to closing"
        else:
            chosen_step = "discount"
            recheck_next_photo = True
            raw_pct = rules.max_discount_pct * (1.0 - (life - H) / rules.overnight_hours)
            clamped_pct = max(rules.min_discount_pct, min(rules.max_discount_pct, raw_pct))
            discount_pct = round_to(clamped_pct, 5)
            # Ensure clamped within limits after round_to
            discount_pct = max(rules.min_discount_pct, min(rules.max_discount_pct, discount_pct))
            reason = f"{item.name.capitalize()}, {item.stage} ({item.stage_level}): sells for about {life:.0f} h; {H:.0f} h to closing → {discount_pct}% off"

    # Case C: it won't last until closing
    else:
        # Off the shelf, the first allowed step whose use is true, in ladder order
        off_shelf_candidates: list[LadderStep] = []
        if uses is not None:
            if "bulk_sale" in allowed and (uses.juice_shop or uses.restaurant or uses.bakery):
                off_shelf_candidates.append("bulk_sale")
            if "donate" in allowed and uses.charity:
                off_shelf_candidates.append("donate")
        if "animal_feed" in allowed and cattle_ok:
            off_shelf_candidates.append("animal_feed")
        if "compost" in allowed:
            off_shelf_candidates.append("compost")

        if off_shelf_candidates:
            chosen_step = off_shelf_candidates[0]
            if chosen_step == "bulk_sale":
                buyer_kinds = []
                if uses and uses.juice_shop:
                    buyer_kinds.append("juice shops")
                if uses and uses.restaurant:
                    buyer_kinds.append("restaurants")
                if uses and uses.bakery:
                    buyer_kinds.append("bakeries")
                desc = " and ".join(buyer_kinds) if buyer_kinds else "commercial buyers"
                reason = f"{item.name.capitalize()}, {item.stage}: won't last to closing; {desc} can use it → bulk sale"
            elif chosen_step == "donate":
                reason = f"{item.name.capitalize()}, {item.stage}: won't last to closing; charities can use it → donate"
            elif chosen_step == "animal_feed":
                reason = f"{item.name.capitalize()}, {item.stage}: safe for cattle feed → animal feed"
            else:  # compost
                reason = f"{item.name.capitalize()}, {item.stage}: not suitable for food or feed → compost"
        else:
            # Case C with no allowed, fitting off-shelf step (e.g. fresh produce that won't last)
            if "discount" in allowed:
                chosen_step = "discount"
                discount_pct = rules.max_discount_pct
                recheck_next_photo = True
                reason = f"{item.name.capitalize()}, {item.stage}: won't last to closing; discount to clear quickly"
            else:
                chosen_step = "keep"
                recheck_next_photo = True
                reason = f"{item.name.capitalize()}, {item.stage}: keep on shelf under observation"
            staff_actions.append("check_before_off_shelf")

    # Step 6: next_steps = remaining fitting allowed steps after chosen_step, in ladder order
    fitting_steps: list[LadderStep] = []
    if uses is not None:
        if "bulk_sale" in allowed and (uses.juice_shop or uses.restaurant or uses.bakery):
            fitting_steps.append("bulk_sale")
        if "donate" in allowed and uses.charity:
            fitting_steps.append("donate")
    if "animal_feed" in allowed and cattle_ok:
        fitting_steps.append("animal_feed")
    if "compost" in allowed:
        fitting_steps.append("compost")

    next_steps: list[LadderStep] = []
    if chosen_step in fitting_steps:
        idx = fitting_steps.index(chosen_step)
        next_steps = fitting_steps[idx + 1 :]
    elif chosen_step == "keep":
        if "discount" in allowed:
            next_steps = ["discount"] + [s for s in fitting_steps if s != "discount"]
        else:
            next_steps = fitting_steps
    elif chosen_step == "discount":
        next_steps = fitting_steps

    # Step 7: Pricing
    needs_price = price is None
    shelf_price = price
    discounted_price: int | None = None
    opening_price: int | None = None
    floor_price: int | None = None

    if needs_price:
        staff_actions.append("enter_shelf_price")
    else:
        assert shelf_price is not None
        if chosen_step == "discount":
            assert discount_pct is not None
            discounted_price = round_to(shelf_price * (100 - discount_pct) / 100.0, rules.price_round_to)
        elif chosen_step == "bulk_sale":
            floor = max(rules.price_round_to, ceil_to(shelf_price * rules.bulk_floor_pct / 100.0, rules.price_round_to))
            opening = max(floor, round_to(shelf_price * rules.bulk_open_pct / 100.0, rules.price_round_to))
            floor_price = floor
            opening_price = opening
        elif chosen_step == "animal_feed":
            floor = max(rules.price_round_to, ceil_to(shelf_price * rules.feed_floor_pct / 100.0, rules.price_round_to))
            opening = max(floor, round_to(shelf_price * rules.feed_open_pct / 100.0, rules.price_round_to))
            floor_price = floor
            opening_price = opening

    # Step 8: Buyer types
    buyer_types: list[BuyerType] = []
    if chosen_step == "bulk_sale" and uses is not None:
        if uses.juice_shop:
            buyer_types.append("juice_shop")
        if uses.restaurant:
            buyer_types.append("restaurant")
        if uses.bakery:
            buyer_types.append("bakery")
    elif chosen_step == "donate":
        buyer_types.append("charity")
    elif chosen_step == "animal_feed":
        buyer_types.append("dairy_farm")

    # Step 9: Flags and staff actions
    remove_bad_pieces = item.worst_stage in ("spoiled", "unsafe") and item.stage not in ("spoiled", "unsafe")
    if remove_bad_pieces:
        staff_actions.append("remove_bad_pieces")

    on_hold = False
    flagged_reasons = {
        "low_confidence",
        "unknown_produce",
        "mixed_crate",
        "model_flagged",
        "zoom_disagreement",
    }
    is_off_shelf = chosen_step in ("bulk_sale", "donate", "animal_feed", "compost")
    if is_off_shelf and any(r in flagged_reasons for r in item.staff_check_reasons):
        on_hold = True
        if "check_before_off_shelf" not in staff_actions:
            staff_actions.append("check_before_off_shelf")

    pkey = produce_key(item.name)
    if pkey == "unknown_produce" or "unknown" in item.name.lower():
        if "identify_item" not in staff_actions:
            staff_actions.append("identify_item")

    needs_approval = False
    if chosen_step == "compost":
        needs_approval = True
        if "approve_compost" not in staff_actions:
            staff_actions.append("approve_compost")

    if chosen_step in ("keep", "discount"):
        recheck_next_photo = True

    # Step 10: Buyer condition text
    stage_words_map = {
        "fresh": "Fresh",
        "ripening": "Ripe",
        "overripe": "Very ripe",
        "spoiled": "Past its best, for animal feed",
        "unsafe": "Unsafe",
    }
    stage_word = stage_words_map.get(item.stage, item.stage.capitalize())

    if remove_bad_pieces:
        mild_issues = [iss.replace("_", " ") for iss in item.issues if iss not in SEVERE_ISSUES]
        issue_part = f"; {', '.join(mild_issues)}" if mild_issues else ""
        cond = f"{stage_word}{issue_part}. Sorted; damaged pieces removed."
    else:
        issue_part = f"; {', '.join(iss.replace('_', ' ') for iss in item.issues)}" if item.issues else ""
        evid_part = f". {item.evidence.strip()}" if item.evidence else ""
        cond = f"{stage_word}{issue_part}{evid_part}"

    if len(cond) > 160:
        cond = cond[:157].rstrip() + "..."

    return LadderDecision(
        item_key=item.item_key,
        name=item.name,
        step=chosen_step,
        allowed_steps=allowed,
        next_steps=next_steps,
        unit=item.quantity.unit,
        sellable_hours=sellable_h,
        shelf_price=shelf_price,
        discount_pct=discount_pct,
        discounted_price=discounted_price,
        opening_price=opening_price,
        floor_price=floor_price,
        buyer_types=buyer_types,
        buyer_condition=cond,
        reason=reason,
        staff_actions=staff_actions,
        on_hold=on_hold,
        needs_approval=needs_approval,
        needs_price=needs_price,
        recheck_next_photo=recheck_next_photo,
        profile_key=profile.key,
        profile_source=profile.source,
        profile_votes=profile.votes,
        profile_uncertain_fields=list(profile.uncertain_fields),
    )
