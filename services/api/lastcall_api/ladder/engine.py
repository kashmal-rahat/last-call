"""Pure decision engine for produce clearance (Module 3).

Gemini knows, code decides:
- Produce knowledge comes from ProduceProfile.
- Pricing rules come from MartRules.
- The decision engine is pure code: no Gemini calls, no I/O, no randomness.
- Never branches on produce names.
"""

import math
import re
from datetime import datetime, timedelta
from typing import get_args
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
    QuantityEstimate,
    ScoutStep,
    ShelfLifeBand,
    StaffAction,
    StageLevel,
    Unit,
)

# "Sells for" calculation (D44):
# The profile's sellable_for band estimates how long produce remains marketable
# from the start of a freshness stage. The Inspector's stage_level (early/mid/late)
# indicates how far into that stage the produce already is.
# LEVEL_FACTOR scales the nominal band hours to estimate remaining marketable time:
# - early (1.0): just entered stage, full band remaining
# - mid (0.7): typical middle of stage, most of band remaining
# - late (0.4): near transition to next stage, minority of band remaining
# Spoiled and unsafe produce have life = 0 / sellable_hours = None (never kept or discounted).
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
        return ["keep", "discount"]  # D44: ripe produce is still good to sell; never leaves shelf
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


def step_prices(step: str, shelf_price: int, rules: MartRules) -> tuple[int, int]:
    """Computes (opening_price, floor_price) for a ladder step."""
    if step == "bulk_sale":
        floor = max(rules.price_round_to, ceil_to(shelf_price * rules.bulk_floor_pct / 100.0, rules.price_round_to))
        opening = max(floor, round_to(shelf_price * rules.bulk_open_pct / 100.0, rules.price_round_to))
        return opening, floor
    if step == "animal_feed":
        floor = max(rules.price_round_to, ceil_to(shelf_price * rules.feed_floor_pct / 100.0, rules.price_round_to))
        opening = max(floor, round_to(shelf_price * rules.feed_open_pct / 100.0, rules.price_round_to))
        return opening, floor
    return 0, 0


# Words that describe produce without changing what it is: "white radish" is radish, "small red onion" is onion.
# Only these are removed, so a name with any other extra word stays unpriced rather than priced as the wrong
# produce (D66). Deliberately absent: "sweet" (sweet potato, sweet lime) and "black" (black plum is jamun).
DESCRIPTIVE_WORDS = frozenset(
    ("white", "red", "green", "yellow", "purple")  # colour
    + ("baby", "small", "large", "desi", "local", "hybrid", "organic", "fresh", "raw")  # size, origin, kind
)


def base_name(name: str) -> str:
    """The name without descriptive words ("baby-spinach" -> "spinach"); empty if nothing else is left."""
    return " ".join(w for w in re.split(r"[\s-]+", name.lower()) if w and w not in DESCRIPTIVE_WORDS)


def _listed_price(rules: MartRules, name: str, unit: Unit) -> int | None:
    for entry in rules.prices:
        if unit in entry.prices and any(names_match(name, alias) for alias in entry.names):
            return entry.prices[unit]
    return None


def find_price(rules: MartRules, name: str, unit: Unit) -> int | None:
    """The shelf price from the mart's list, in the item's unit (never converted, D4).

    The full name is tried against the whole list first, so a listed name ("green onion", "sweet potato")
    always wins; only then the name without descriptive words (D66).
    """
    price = _listed_price(rules, name, unit)
    if price is None:
        base = base_name(name)
        if base:
            price = _listed_price(rules, base, unit)
    return price


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


def selling_time(hours: float) -> str:
    """How long produce still sells, in words: "about 34 h". A duration, not a clock time, so it reads the same
    whichever time the page simulates, and lines up with the "4 h to closing" chip. Rounded because the
    estimate is approximate on purpose (bands × level)."""
    if hours < 1:
        return "under an hour"
    if hours < 10:
        half_hours = math.floor(hours * 2 + 0.5) / 2  # nearest half hour, halves rounded up
        return f"about {half_hours:g}\u00a0h"
    whole_hours = math.floor(hours + 0.5)
    if whole_hours < 48:  # decided on the rounded value, so 47.6 h reads "about 2 days", not "about 48 h"
        return f"about {whole_hours}\u00a0h"
    return f"about {math.floor(hours / 24 + 0.5)}\u00a0days"


def round_estimate(quantity: float) -> float:
    """A photo estimate as people say it, rounded down so the offer never grows (D71).

    Below 10 to the half (2.1 → 2, 3.6 → 3.5), from 10 to the whole number (23.7 → 23). An amount that
    would round to 0 is kept as it is.
    """
    step = 1.0 if quantity >= 10 else 0.5
    rounded = math.floor(quantity / step) * step
    return rounded if rounded > 0 else quantity


def offer_quantity(estimate: QuantityEstimate | None) -> float | None:
    """The amount offered to buyers when staff haven't entered one (D71): the estimate's low end if above 0,
    else its high end, rounded; None when the photo gives no amount. The decision carries it for the page,
    and the call handoff uses the same function, so the rule exists once."""
    if estimate is None:
        return None
    if estimate.low > 0:
        return round_estimate(estimate.low)
    if estimate.high > 0:
        return round_estimate(estimate.high)
    return None


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

    overnight_h = rules.overnight_hours
    window_h = rules.discount_window_hours

    ref_date = datetime(2026, 10, 10)
    close_dt = datetime.combine(ref_date, rules.closing_time)
    open_str = rules.opening_time.strftime("%H:%M")
    close_str = rules.closing_time.strftime("%H:%M")
    window_start_dt = close_dt - timedelta(hours=window_h)
    window_start_str = window_start_dt.strftime("%H:%M")
    sells_for = selling_time(life)

    # Step 4 v2 (D44) decision branches. Reasons are read under the item's name and the chosen step on the page,
    # so they start with the stage and never repeat the name or the step
    stage = item.stage.capitalize()
    if item.stage in ("fresh", "ripening"):
        recheck_next_photo = True
        if life >= H + overnight_h:
            chosen_step = "keep"
            reason = f"{stage}: sells for {sells_for}, still fine when the mart reopens at {open_str}."
        elif H > window_h:
            chosen_step = "keep"
            reason = f"{stage}: sells for {sells_for}. Any discount is decided in the evening, from {window_start_str}."
        else:
            chosen_step = "discount"
            if life < H:
                discount_pct = rules.max_discount_pct
                reason = f"{stage}: sells for {sells_for}, so it stops selling before the {close_str} closing."
            else:
                raw_pct = rules.min_discount_pct + (rules.max_discount_pct - rules.min_discount_pct) * (
                    1.0 - H / window_h
                )
                discount_pct = round_to(raw_pct, 5)
                discount_pct = max(rules.min_discount_pct, min(rules.max_discount_pct, discount_pct))
                reason = f"{stage} ({item.stage_level}): sells for {sells_for}, not fine when the mart reopens at {open_str}."

    elif item.stage == "overripe":
        has_business_buyer = bool(uses and (uses.juice_shop or uses.restaurant or uses.bakery))
        if has_business_buyer and H >= rules.bulk_pickup_hours:
            chosen_step = "bulk_sale"
            buyer_kinds = []
            if uses and uses.juice_shop:
                buyer_kinds.append("juice shops")
            if uses and uses.restaurant:
                buyer_kinds.append("restaurants")
            if uses and uses.bakery:
                buyer_kinds.append("bakeries")
            desc = " and ".join(buyer_kinds) if buyer_kinds else "commercial buyers"
            reason = f"{stage}: {desc} can use it."
        else:
            chosen_step = "discount"
            discount_pct = rules.max_discount_pct
            recheck_next_photo = True
            if not has_business_buyer:
                reason = (
                    f"{stage}: no juice shop, restaurant or bakery can use it, so it stays on the shelf at a discount."
                )
            else:
                reason = f"{stage}: too late for pickup before the {close_str} closing, so it stays on the shelf at a discount."

    elif item.stage == "spoiled":
        if "animal_feed" in allowed and cattle_ok:
            chosen_step = "animal_feed"
            reason = f"{stage}: still safe as cattle feed."
        else:
            chosen_step = "compost"
            if "mould" in item.issues:
                reason = f"{stage}: mould present, not fit for food or feed."
            elif "slime" in item.issues:
                reason = f"{stage}: slime present, not fit for food or feed."
            else:
                reason = f"{stage}: not fit for food or feed."

    else:  # unsafe
        chosen_step = "compost"
        reason = f"{stage}: not safe for food or feed."

    # Step 6: next_steps = remaining fitting allowed steps after chosen_step, in ladder order
    next_steps: list[LadderStep] = []
    if chosen_step == "keep":
        if "discount" in allowed:
            next_steps = ["discount"]
    elif chosen_step == "discount":
        if item.stage == "overripe":
            if "donate" in allowed and (uses and uses.charity):
                next_steps.append("donate")
            if "animal_feed" in allowed and cattle_ok:
                next_steps.append("animal_feed")
    elif chosen_step == "bulk_sale":
        if "donate" in allowed and (uses and uses.charity):
            next_steps.append("donate")
        if "animal_feed" in allowed and cattle_ok:
            next_steps.append("animal_feed")
    elif chosen_step == "donate":
        if "animal_feed" in allowed and cattle_ok:
            next_steps.append("animal_feed")
    elif chosen_step == "animal_feed":
        if "compost" in allowed:
            next_steps.append("compost")

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
        elif chosen_step in ("bulk_sale", "animal_feed"):
            opening_price, floor_price = step_prices(chosen_step, shelf_price, rules)

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
        offer_quantity=offer_quantity(item.quantity) if chosen_step in get_args(ScoutStep) else None,
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
