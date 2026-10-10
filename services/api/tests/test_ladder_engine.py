"""Tests for pure Ladder decision engine (Step 4)."""

from datetime import datetime, time, timezone
import pytest

from lastcall_api.ladder.engine import (
    allowed_steps,
    decide_item,
    find_price,
    hours_until_closing,
)
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import (
    BoundingBox,
    ItemAssessment,
    MartRules,
    ObservedQuantity,
    ProduceProfile,
    QuantityEstimate,
    StageProfile,
)

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _make_item(
    name: str = "banana",
    stage: str = "fresh",
    stage_level: str = "mid",
    worst_stage: str | None = None,
    issues: list[str] | None = None,
    evidence: str = "",
    staff_check_reasons: list[str] | None = None,
    unit: str = "dozen",
) -> ItemAssessment:
    ws = worst_stage if worst_stage is not None else stage
    return ItemAssessment(
        item_key="item_01",
        name=name,
        grid="center",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        stage=stage,
        stage_level=stage_level,
        worst_stage=ws,
        score=85.0,
        confidence=0.9,
        confidence_level="high",
        issues=issues or [],
        evidence=evidence,
        observed=ObservedQuantity(method="count", min=10, max=10),
        quantity=QuantityEstimate(unit=unit, low=1.0, high=1.0),
        needs_staff_check=bool(staff_check_reasons),
        staff_check_reasons=staff_check_reasons or [],
    )


def _make_profile(
    name: str = "banana",
    fresh_band: str = "1_to_3_days",
    rip_band: str = "6_to_24h",
    over_band: str = "under_6h",
    fresh_uses: dict | None = None,
    rip_uses: dict | None = None,
    over_uses: dict | None = None,
    overripe_ok_for_cattle: bool = True,
    spoiled_ok_for_cattle: bool = False,
) -> ProduceProfile:
    def_fresh = {"juice_shop": True, "restaurant": True, "bakery": False, "charity": True}
    def_rip = {"juice_shop": True, "restaurant": True, "bakery": True, "charity": True}
    def_over = {"juice_shop": True, "restaurant": False, "bakery": True, "charity": True}

    return ProduceProfile(
        key=f"{name}__v1",
        name=name,
        note="Test profile",
        fresh=StageProfile(sellable_for=fresh_band, **(fresh_uses or def_fresh)),
        ripening=StageProfile(sellable_for=rip_band, **(rip_uses or def_rip)),
        overripe=StageProfile(sellable_for=over_band, **(over_uses or def_over)),
        overripe_ok_for_cattle=overripe_ok_for_cattle,
        spoiled_ok_for_cattle=spoiled_ok_for_cattle,
        source="gemini",
        prompt_version="1",
        created_at=NOW,
    )


def test_allowed_steps_table():
    assert allowed_steps(_make_item(stage="fresh")) == ["keep", "discount"]
    assert allowed_steps(_make_item(stage="ripening")) == ["keep", "discount", "bulk_sale"]
    assert allowed_steps(_make_item(stage="overripe")) == ["discount", "bulk_sale", "donate", "animal_feed"]
    # Spoiled without mould/slime
    assert allowed_steps(_make_item(stage="spoiled", issues=["rot"])) == ["animal_feed", "compost"]
    # Spoiled with mould
    assert allowed_steps(_make_item(stage="spoiled", issues=["mould"])) == ["compost"]
    # Spoiled with slime
    assert allowed_steps(_make_item(stage="spoiled", issues=["slime"])) == ["compost"]
    # Unsafe
    assert allowed_steps(_make_item(stage="unsafe")) == ["compost"]


def test_find_price():
    rules = load_mart_rules("demo_mart")

    # Match alias
    assert find_price(rules, "bhindi", "kg") == 120
    assert find_price(rules, "okra", "kg") == 120
    # Plural match
    assert find_price(rules, "tomatoes", "kg") == 120
    assert find_price(rules, "bananas", "dozen") == 180
    assert find_price(rules, "banana", "kg") == 150
    # M3 dual units: kinnow, lemon, guava have both dozen and kg
    assert find_price(rules, "kinnow", "dozen") == 280
    assert find_price(rules, "kinnow", "kg") == 140
    assert find_price(rules, "lemon", "dozen") == 120
    assert find_price(rules, "lemon", "kg") == 220
    assert find_price(rules, "guava", "dozen") == 210
    assert find_price(rules, "guava", "kg") == 140
    # Unit mismatch (tomato only kg)
    assert find_price(rules, "tomato", "dozen") is None
    # Unknown produce
    assert find_price(rules, "dragonfruit", "kg") is None


def test_i4_keep_decision_next_steps_starts_with_discount():
    """I4: For a 'keep' decision, next_steps starts with 'discount' when discount is allowed."""
    rules = load_mart_rules("demo_mart")
    prof = _make_profile("banana", fresh_band="over_3_days", rip_band="6_to_24h", over_band="under_6h")
    item = _make_item("banana", stage="fresh", stage_level="early")
    # Fresh has allowed_steps: ["keep", "discount"]
    dec = decide_item(item, prof, rules, H=14.0, price=180)
    assert dec.step == "keep"
    assert "discount" in dec.allowed_steps
    assert len(dec.next_steps) > 0
    assert dec.next_steps[0] == "discount"

    # Ripening banana where life > H (e.g. fresh_band 1_to_3_days, life 36h, H=4) -> keep
    prof_rip = _make_profile("banana", rip_band="1_to_3_days")
    item_rip = _make_item("banana", stage="ripening", stage_level="early")
    # Ripening has allowed_steps: ["keep", "discount", "bulk_sale"]
    dec_rip = decide_item(item_rip, prof_rip, rules, H=4.0, price=180)
    assert dec_rip.step == "keep"
    assert "discount" in dec_rip.allowed_steps
    assert dec_rip.next_steps[0] == "discount"


def test_hours_until_closing():
    rules = load_mart_rules("demo_mart")

    # Override takes precedence
    assert hours_until_closing(rules, NOW, override=4.5) == 4.5

    # Fixed time in PKT: 20:00 PKT with closing 23:00 -> 3.0 hours
    dt = datetime(2026, 10, 10, 20, 0, 0, tzinfo=timezone.utc)  # in PKT this is 01:00 next day
    # Test with timezone-aware Karachi time
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Karachi")
    t1 = datetime(2026, 10, 10, 19, 0, 0, tzinfo=tz)  # 19:00 PKT -> 4 hours until 23:00
    assert abs(hours_until_closing(rules, t1) - 4.0) < 0.01

    # After closing: 23:30 PKT -> counts to tomorrow's 23:00 -> 23.5 hours
    t2 = datetime(2026, 10, 10, 23, 30, 0, tzinfo=tz)
    assert abs(hours_until_closing(rules, t2) - 23.5) < 0.01


def test_worked_examples():
    rules = load_mart_rules("demo_mart")

    # 1. Fresh banana in the morning (H=14) -> keep
    # Banana shelf price: 180 / dozen
    prof_banana = _make_profile("banana", fresh_band="over_3_days", rip_band="6_to_24h", over_band="under_6h")
    item_fresh_banana = _make_item("banana", stage="fresh", stage_level="early")
    dec1 = decide_item(item_fresh_banana, prof_banana, rules, H=14.0, price=180)
    assert dec1.step == "keep"
    assert dec1.shelf_price == 180
    assert dec1.discount_pct is None

    # 2. Late-ripening banana (band 6_to_24h -> 15 * 0.4 = 6 h), 3 h to closing -> discount 30%
    item_rip_banana = _make_item("banana", stage="ripening", stage_level="late")
    dec2 = decide_item(item_rip_banana, prof_banana, rules, H=3.0, price=180)
    assert dec2.step == "discount"
    assert dec2.discount_pct == 30
    assert dec2.discounted_price == 125  # 180 * 0.70 = 126, rounded to 5 -> 125
    assert "30% off" in dec2.reason

    # 3. Same late-ripening banana at 14 h to closing -> bulk sale (6 h < 14 h)
    dec3 = decide_item(item_rip_banana, prof_banana, rules, H=14.0, price=180)
    assert dec3.step == "bulk_sale"
    assert "juice_shop" in dec3.buyer_types
    assert dec3.opening_price is not None
    assert dec3.floor_price is not None
    assert dec3.opening_price >= dec3.floor_price

    # 4. Overripe spinach, 8 h to closing (life <= 4 h) -> bulk sale to restaurants
    prof_spinach = _make_profile(
        "spinach",
        fresh_band="6_to_24h",
        rip_band="under_6h",
        over_band="under_6h",
        over_uses={"juice_shop": False, "restaurant": True, "bakery": False, "charity": True},
    )
    item_over_spinach = _make_item("spinach", stage="overripe", stage_level="mid", unit="kg")
    dec4 = decide_item(item_over_spinach, prof_spinach, rules, H=8.0, price=70)
    assert dec4.step == "bulk_sale"
    assert dec4.buyer_types == ["restaurant"]

    # 5. Fresh (early) spinach (band 6_to_24h, life 15 h), 13 h to closing -> keep for now
    item_fresh_early_spinach = _make_item("spinach", stage="fresh", stage_level="early", unit="kg")
    dec5a = decide_item(item_fresh_early_spinach, prof_spinach, rules, H=13.0, price=70)
    assert dec5a.step == "keep"
    assert dec5a.recheck_next_photo is True
    assert "closer to closing" in dec5a.reason

    # Same spinach at 4 h to closing -> discount 10%
    dec5b = decide_item(item_fresh_early_spinach, prof_spinach, rules, H=4.0, price=70)
    assert dec5b.step == "discount"
    assert dec5b.discount_pct == 10  # clamped to min_discount

    # 6. Overripe potatoes (band over_3_days, life 96 h) -> discount 10% (Case A, keep not allowed)
    prof_potato = _make_profile("potato", over_band="over_3_days")
    item_over_potato = _make_item("potato", stage="overripe", stage_level="early", unit="kg")
    dec6 = decide_item(item_over_potato, prof_potato, rules, H=8.0, price=80)
    assert dec6.step == "discount"
    assert dec6.discount_pct == 10

    # 7. Spoiled without mould -> animal feed if cattle-ok, else compost
    prof_cattle_ok = _make_profile("pumpkin", spoiled_ok_for_cattle=True)
    item_sp_cattle = _make_item("pumpkin", stage="spoiled", issues=["rot"], unit="kg")
    dec7a = decide_item(item_sp_cattle, prof_cattle_ok, rules, H=4.0, price=100)
    assert dec7a.step == "animal_feed"
    assert dec7a.buyer_types == ["dairy_farm"]

    prof_cattle_no = _make_profile("onion", spoiled_ok_for_cattle=False)
    item_sp_onion = _make_item("onion", stage="spoiled", issues=["rot"], unit="kg")
    dec7b = decide_item(item_sp_onion, prof_cattle_no, rules, H=4.0, price=100)
    assert dec7b.step == "compost"
    assert dec7b.needs_approval is True
    assert "approve_compost" in dec7b.staff_actions


def test_remove_bad_pieces_and_buyer_condition_filtering():
    rules = load_mart_rules("demo_mart")
    prof = _make_profile("banana")

    # A ripening group whose worst pieces are mouldy:
    # worst_stage is spoiled, stage is ripening -> remove_bad_pieces set
    item = _make_item(
        name="banana",
        stage="ripening",
        worst_stage="spoiled",
        issues=["browning", "mould"],
        evidence="Mould visible on bottom piece; top pieces sound and yellow.",
    )
    dec = decide_item(item, prof, rules, H=3.0, price=180)

    assert "remove_bad_pieces" in dec.staff_actions
    # buyer_condition must mention neither 'mould' nor evidence text!
    assert "mould" not in dec.buyer_condition.lower()
    assert "bottom piece" not in dec.buyer_condition.lower()
    assert "Sorted; damaged pieces removed." in dec.buyer_condition


def test_missing_price_and_holds():
    rules = load_mart_rules("demo_mart")
    prof = _make_profile("banana")

    # Missing price: price is None
    item = _make_item(name="banana", stage="ripening", stage_level="late")
    dec = decide_item(item, prof, rules, H=3.0, price=None)
    assert dec.needs_price is True
    assert "enter_shelf_price" in dec.staff_actions
    assert dec.discounted_price is None

    # Holds on off-shelf step with staff_check_reasons
    item_hold = _make_item(
        name="banana",
        stage="ripening",
        stage_level="late",
        staff_check_reasons=["low_confidence"],
    )
    # H=14 -> off-shelf bulk_sale
    dec_hold = decide_item(item_hold, prof, rules, H=14.0, price=180)
    assert dec_hold.step == "bulk_sale"
    assert dec_hold.on_hold is True
    assert "check_before_off_shelf" in dec_hold.staff_actions


def test_exhaustive_engine_loop_zero_violations():
    """Exhaustive check across all stage x level x band x use combinations x H in {0.5, 3, 8, 14}."""
    rules = load_mart_rules("demo_mart")
    stages = ["fresh", "ripening", "overripe", "spoiled", "unsafe"]
    levels = ["early", "mid", "late"]
    bands = ["under_6h", "6_to_24h", "1_to_3_days", "over_3_days"]
    h_values = [0.5, 3.0, 8.0, 14.0]

    # Sample boolean combinations for uses
    use_combos = [
        {"juice_shop": True, "restaurant": True, "bakery": True, "charity": True},
        {"juice_shop": False, "restaurant": True, "bakery": False, "charity": False},
        {"juice_shop": False, "restaurant": False, "bakery": False, "charity": True},
        {"juice_shop": False, "restaurant": False, "bakery": False, "charity": False},
    ]

    total_checked = 0
    violations = []

    for stage in stages:
        for level in levels:
            for band in bands:
                for uses in use_combos:
                    for cattle_ok in [True, False]:
                        for H in h_values:
                            total_checked += 1
                            item = _make_item(
                                name="test_produce",
                                stage=stage,
                                stage_level=level,
                                worst_stage=stage,
                            )
                            prof = _make_profile(
                                name="test_produce",
                                fresh_band=band,
                                rip_band=band,
                                over_band=band,
                                fresh_uses=uses,
                                rip_uses=uses,
                                over_uses=uses,
                                overripe_ok_for_cattle=cattle_ok,
                                spoiled_ok_for_cattle=cattle_ok,
                            )
                            dec = decide_item(item, prof, rules, H=H, price=100)

                            # 1. Step must always be allowed
                            if dec.step not in dec.allowed_steps:
                                violations.append(f"Step {dec.step} not in allowed {dec.allowed_steps} for stage {stage}")

                            # 2. Opening >= Floor when both set
                            if dec.opening_price is not None and dec.floor_price is not None:
                                if dec.opening_price < dec.floor_price:
                                    violations.append(f"Opening {dec.opening_price} < floor {dec.floor_price}")

                            # 3. Discount within limits
                            if dec.step == "discount":
                                if dec.discount_pct is None:
                                    violations.append("Discount step missing discount_pct")
                                elif dec.discount_pct < rules.min_discount_pct or dec.discount_pct > rules.max_discount_pct:
                                    violations.append(f"Discount {dec.discount_pct} outside [{rules.min_discount_pct}, {rules.max_discount_pct}]")

    assert not violations, f"Exhaustive test found {len(violations)} violations:\n" + "\n".join(violations[:10])
    assert total_checked > 1000
    print(f"\nExhaustive check verified {total_checked} combinations with 0 violations.")


def test_monotonic_shelf_life_behavior():
    """For the same item and time, a longer shelf-life band never gives a worse step."""
    rules = load_mart_rules("demo_mart")
    item = _make_item(name="mango", stage="ripening", stage_level="mid")
    H = 8.0

    step_rank = {"keep": 0, "discount": 1, "bulk_sale": 2, "donate": 3, "animal_feed": 4, "compost": 5}

    bands_ordered = ["under_6h", "6_to_24h", "1_to_3_days", "over_3_days"]
    prev_rank = 999

    for band in bands_ordered:
        prof = _make_profile("mango", rip_band=band)
        dec = decide_item(item, prof, rules, H=H, price=150)
        curr_rank = step_rank.get(dec.step, 99)

        # Longer band means equal or better (lower rank)
        if prev_rank != 999:
            assert curr_rank <= prev_rank, f"Band {band} gave rank {curr_rank} which is worse than previous {prev_rank}"
        prev_rank = curr_rank
