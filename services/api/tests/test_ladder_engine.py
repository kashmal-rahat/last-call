"""Tests for pure Ladder decision engine (Step 4)."""

from datetime import datetime, timezone

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
    assert allowed_steps(_make_item(stage="ripening")) == ["keep", "discount"]
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

    # Ripening banana where life > H + O (e.g. rip_band 1_to_3_days, life 33.6h, H=4 -> 4+10=14h) -> keep
    prof_rip = _make_profile("banana", rip_band="1_to_3_days")
    item_rip = _make_item("banana", stage="ripening", stage_level="early")
    # Ripening has allowed_steps: ["keep", "discount"]
    dec_rip = decide_item(item_rip, prof_rip, rules, H=4.0, price=180)
    assert dec_rip.step == "keep"
    assert "discount" in dec_rip.allowed_steps
    assert dec_rip.next_steps[0] == "discount"


def test_hours_until_closing():
    rules = load_mart_rules("demo_mart")

    # Override takes precedence
    assert hours_until_closing(rules, NOW, override=4.5) == 4.5

    # Fixed time in PKT: 20:00 PKT with closing 23:00 -> 3.0 hours
    dt = datetime(2026, 10, 10, 20, 0, 0, tzinfo=timezone.utc)
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Karachi")
    t1 = datetime(2026, 10, 10, 19, 0, 0, tzinfo=tz)  # 19:00 PKT -> 4 hours until 23:00
    assert abs(hours_until_closing(rules, t1) - 4.0) < 0.01

    # After closing: 23:30 PKT -> counts to tomorrow's 23:00 -> 23.5 hours
    t2 = datetime(2026, 10, 10, 23, 30, 0, tzinfo=tz)
    assert abs(hours_until_closing(rules, t2) - 23.5) < 0.01


@pytest.mark.parametrize(
    "scenario_id,item_args,profile_args,H,expected_step,expected_discount,flags_to_check",
    [
        # 1: onion, fresh (mid), fresh over_3_days (67.2h), 10:00 (H=13) -> keep
        (
            1,
            {"name": "onion", "stage": "fresh", "stage_level": "mid"},
            {"fresh_band": "over_3_days"},
            13.0,
            "keep",
            None,
            [],
        ),
        # 2: banana, ripening (mid), ripening 6_to_24h (10.5h), 10:00 (H=13) -> keep (for now), recheck_next_photo
        (
            2,
            {"name": "banana", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "6_to_24h"},
            13.0,
            "keep",
            None,
            ["recheck_next_photo"],
        ),
        # 3: same as 2, 19:00 (H=4) -> discount 20%
        (
            3,
            {"name": "banana", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "6_to_24h"},
            4.0,
            "discount",
            20,
            [],
        ),
        # 4: same as 2, 22:00 (H=1) -> discount 35%
        (
            4,
            {"name": "banana", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "6_to_24h"},
            1.0,
            "discount",
            35,
            [],
        ),
        # 5: banana, ripening (mid), ripening 1_to_3_days (33.6h), 19:00 (H=4) -> keep
        (
            5,
            {"name": "banana", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "1_to_3_days"},
            4.0,
            "keep",
            None,
            [],
        ),
        # 6: tomato, fresh (early), fresh 1_to_3_days (48h), 19:00 (H=4) -> keep
        (
            6,
            {"name": "tomato", "stage": "fresh", "stage_level": "early"},
            {"fresh_band": "1_to_3_days"},
            4.0,
            "keep",
            None,
            [],
        ),
        # 7: spinach, fresh (early), fresh 6_to_24h (15h), 10:00 (H=13) -> keep (for now)
        (
            7,
            {"name": "spinach", "stage": "fresh", "stage_level": "early"},
            {"fresh_band": "6_to_24h"},
            13.0,
            "keep",
            None,
            [],
        ),
        # 8: same as 7, 17:00 (H=6) -> discount 10%
        (
            8,
            {"name": "spinach", "stage": "fresh", "stage_level": "early"},
            {"fresh_band": "6_to_24h"},
            6.0,
            "discount",
            10,
            [],
        ),
        # 9: same as 7, 22:00 (H=1) -> keep (still fine at 09:00 tomorrow)
        (
            9,
            {"name": "spinach", "stage": "fresh", "stage_level": "early"},
            {"fresh_band": "6_to_24h"},
            1.0,
            "keep",
            None,
            ["fine_tomorrow"],
        ),
        # 10: spinach, ripening (mid), ripening under_6h (2.8h), 19:00 (H=4) -> discount 40% (stops before closing)
        (
            10,
            {"name": "spinach", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "under_6h"},
            4.0,
            "discount",
            40,
            ["stops_before_closing"],
        ),
        # 11: same as 10, 10:00 (H=13) -> keep (for now)
        (
            11,
            {"name": "spinach", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "under_6h"},
            13.0,
            "keep",
            None,
            [],
        ),
        # 12: banana, overripe (mid), overripe: juice_shop, bakery, 10:00 (H=13) -> bulk_sale
        (
            12,
            {"name": "banana", "stage": "overripe", "stage_level": "mid"},
            {"over_uses": {"juice_shop": True, "restaurant": False, "bakery": True, "charity": True}},
            13.0,
            "bulk_sale",
            None,
            ["buyers:juice_shop,bakery"],
        ),
        # 13: same as 12, 20:30 (H=2.5) -> bulk_sale
        (
            13,
            {"name": "banana", "stage": "overripe", "stage_level": "mid"},
            {"over_uses": {"juice_shop": True, "restaurant": False, "bakery": True, "charity": True}},
            2.5,
            "bulk_sale",
            None,
            [],
        ),
        # 14: same as 12, 21:30 (H=1.5) -> discount 40% (too late for pickup)
        (
            14,
            {"name": "banana", "stage": "overripe", "stage_level": "mid"},
            {"over_uses": {"juice_shop": True, "restaurant": False, "bakery": True, "charity": True}},
            1.5,
            "discount",
            40,
            ["too_late_for_pickup"],
        ),
        # 15: coriander, overripe (mid), no business use, cattle no, 10:00 (H=13) -> discount 40%; next_steps [donate]
        (
            15,
            {"name": "coriander", "stage": "overripe", "stage_level": "mid"},
            {
                "over_uses": {"juice_shop": False, "restaurant": False, "bakery": False, "charity": True},
                "overripe_ok_for_cattle": False,
            },
            13.0,
            "discount",
            40,
            ["next_steps:donate"],
        ),
        # 16: potato, overripe (early), overripe: restaurant, 10:00 (H=13) -> bulk_sale
        (
            16,
            {"name": "potato", "stage": "overripe", "stage_level": "early"},
            {"over_uses": {"juice_shop": False, "restaurant": True, "bakery": False, "charity": True}},
            13.0,
            "bulk_sale",
            None,
            ["buyers:restaurant"],
        ),
        # 17: tomato, spoiled, no mould, spoiled_ok_for_cattle yes, any (H=4) -> animal_feed
        (
            17,
            {"name": "tomato", "stage": "spoiled", "stage_level": "mid", "issues": ["rot"]},
            {"spoiled_ok_for_cattle": True},
            4.0,
            "animal_feed",
            None,
            [],
        ),
        # 18: tomato, spoiled, no mould, spoiled_ok_for_cattle no, any (H=4) -> compost, needs_approval
        (
            18,
            {"name": "tomato", "stage": "spoiled", "stage_level": "mid", "issues": ["rot"]},
            {"spoiled_ok_for_cattle": False},
            4.0,
            "compost",
            None,
            ["needs_approval"],
        ),
        # 19: tomato, spoiled, mould in issues, spoiled_ok_for_cattle yes, any (H=4) -> compost, needs_approval
        (
            19,
            {"name": "tomato", "stage": "spoiled", "stage_level": "mid", "issues": ["mould"]},
            {"spoiled_ok_for_cattle": True},
            4.0,
            "compost",
            None,
            ["needs_approval"],
        ),
        # 20: apple, fresh (mid), worst_stage spoiled, fresh over_3_days (67.2h), 10:00 (H=13) -> keep, remove_bad_pieces
        (
            20,
            {"name": "apple", "stage": "fresh", "stage_level": "mid", "worst_stage": "spoiled"},
            {"fresh_band": "over_3_days"},
            13.0,
            "keep",
            None,
            ["remove_bad_pieces"],
        ),
        # 21: banana, overripe, staff reason low_confidence, as 12, 10:00 (H=13) -> bulk_sale, on_hold, check_before_off_shelf
        (
            21,
            {"name": "banana", "stage": "overripe", "stage_level": "mid", "staff_check_reasons": ["low_confidence"]},
            {"over_uses": {"juice_shop": True, "restaurant": False, "bakery": True, "charity": True}},
            13.0,
            "bulk_sale",
            None,
            ["on_hold", "check_before_off_shelf"],
        ),
        # 22: unknown produce, overripe, fallback profile, 10:00 (H=13) -> bulk_sale, buyers restaurant; on_hold, identify_item, enter_shelf_price
        (
            22,
            {
                "name": "unknown produce",
                "stage": "overripe",
                "stage_level": "mid",
                "staff_check_reasons": ["unknown_produce"],
            },
            {"over_uses": {"juice_shop": False, "restaurant": True, "bakery": False, "charity": True}},
            13.0,
            "bulk_sale",
            None,
            ["buyers:restaurant", "on_hold", "identify_item", "needs_price", "enter_shelf_price"],
        ),
        # 23: produce not in price list, ripening (mid), ripening 1_to_3_days (33.6h), 10:00 (H=13) -> keep, needs_price, enter_shelf_price
        (
            23,
            {"name": "dragonfruit", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "1_to_3_days"},
            13.0,
            "keep",
            None,
            ["needs_price", "enter_shelf_price"],
        ),
        # 24: banana, ripening (mid), as 2 (10.5h), 00:30 (H=22.5) -> keep (for now)
        (
            24,
            {"name": "banana", "stage": "ripening", "stage_level": "mid"},
            {"rip_band": "6_to_24h"},
            22.5,
            "keep",
            None,
            [],
        ),
    ],
)
def test_twenty_four_scenarios_table_driven(
    scenario_id,
    item_args,
    profile_args,
    H,
    expected_step,
    expected_discount,
    flags_to_check,
):
    rules = load_mart_rules("demo_mart")
    item = _make_item(**item_args)
    prof = _make_profile(name=item.name, **profile_args)

    price = find_price(rules, item.name, item.quantity.unit)
    dec = decide_item(item, prof, rules, H=H, price=price)

    assert dec.step == expected_step, f"Scenario {scenario_id} expected step {expected_step}, got {dec.step}"
    if expected_discount is not None:
        assert dec.discount_pct == expected_discount, (
            f"Scenario {scenario_id} expected discount {expected_discount}%, got {dec.discount_pct}%"
        )

    for flag in flags_to_check:
        if flag == "recheck_next_photo":
            assert dec.recheck_next_photo is True
        elif flag == "fine_tomorrow":
            assert "09:00" in dec.reason and "tomorrow" in dec.reason
        elif flag == "stops_before_closing":
            assert "stops selling before" in dec.reason
        elif flag == "too_late_for_pickup":
            assert "too late for pickup" in dec.reason
        elif flag == "next_steps:donate":
            assert dec.next_steps == ["donate"]
        elif flag.startswith("buyers:"):
            expected_buyers = flag.split(":", 1)[1].split(",")
            for b in expected_buyers:
                assert b in dec.buyer_types
        elif flag == "remove_bad_pieces":
            assert "remove_bad_pieces" in dec.staff_actions
        elif flag == "on_hold":
            assert dec.on_hold is True
        elif flag == "check_before_off_shelf":
            assert "check_before_off_shelf" in dec.staff_actions
        elif flag == "identify_item":
            assert "identify_item" in dec.staff_actions
        elif flag == "needs_price":
            assert dec.needs_price is True
        elif flag == "enter_shelf_price":
            assert "enter_shelf_price" in dec.staff_actions
        elif flag == "needs_approval":
            assert dec.needs_approval is True
            assert "approve_compost" in dec.staff_actions


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

    # Holds on off-shelf step with staff_check_reasons (overripe bulk_sale)
    item_hold = _make_item(
        name="banana",
        stage="overripe",
        stage_level="mid",
        staff_check_reasons=["low_confidence"],
    )
    # H=14 -> off-shelf bulk_sale
    dec_hold = decide_item(item_hold, prof, rules, H=14.0, price=180)
    assert dec_hold.step == "bulk_sale"
    assert dec_hold.on_hold is True
    assert "check_before_off_shelf" in dec_hold.staff_actions


def test_exhaustive_engine_loop_zero_violations():
    """Exhaustive check across all stage x level x band x use combinations x H in {0.5, 1, 1.9, 2, 3, 5, 6, 8, 14, 23}."""
    rules = load_mart_rules("demo_mart")
    stages = ["fresh", "ripening", "overripe", "spoiled", "unsafe"]
    levels = ["early", "mid", "late"]
    bands = ["under_6h", "6_to_24h", "1_to_3_days", "over_3_days"]
    h_values = [0.5, 1.0, 1.9, 2.0, 3.0, 5.0, 6.0, 8.0, 14.0, 23.0]

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
                                violations.append(
                                    f"Step {dec.step} not in allowed {dec.allowed_steps} for stage {stage}"
                                )

                            # 2. D44: fresh and ripening never get an off-shelf step
                            if stage in ("fresh", "ripening") and dec.step not in ("keep", "discount"):
                                violations.append(f"Stage {stage} got off-shelf step {dec.step}")

                            # 3. Opening >= Floor when both set
                            if dec.opening_price is not None and dec.floor_price is not None:
                                if dec.opening_price < dec.floor_price:
                                    violations.append(f"Opening {dec.opening_price} < floor {dec.floor_price}")

                            # 4. Discount within limits
                            if dec.step == "discount":
                                if dec.discount_pct is None:
                                    violations.append("Discount step missing discount_pct")
                                elif (
                                    dec.discount_pct < rules.min_discount_pct
                                    or dec.discount_pct > rules.max_discount_pct
                                ):
                                    violations.append(
                                        f"Discount {dec.discount_pct} outside [{rules.min_discount_pct}, {rules.max_discount_pct}]"
                                    )

    assert not violations, f"Exhaustive test found {len(violations)} violations:\n" + "\n".join(violations[:10])
    assert total_checked > 2000
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


def test_monotonic_discount_inside_window():
    """Inside evening window, discount never gets smaller as H decreases."""
    rules = load_mart_rules("demo_mart")
    item = _make_item(name="banana", stage="ripening", stage_level="late")
    prof = _make_profile("banana", rip_band="6_to_24h")
    # life = 15 * 0.4 = 6.0 h; for H in [6, 5, 4, 3, 2, 1, 0.5], life < H + O always (6.0 < 10 + H)
    h_values = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.5]
    prev_discount = 0

    for H in h_values:
        dec = decide_item(item, prof, rules, H=H, price=180)
        assert dec.step == "discount"
        assert dec.discount_pct is not None
        assert dec.discount_pct >= prev_discount, (
            f"At H={H}, discount {dec.discount_pct}% is smaller than previous {prev_discount}%"
        )
        prev_discount = dec.discount_pct
