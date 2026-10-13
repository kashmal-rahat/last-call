"""Unit tests for inspector guardrails (Step 4)."""

import pytest

from lastcall_api.inspector.guardrails import (
    CONFIDENCE_MAP,
    SCORE_TABLE,
    apply_guardrails,
    clean_item,
    compute_grid,
    merge_neighbours,
)
from lastcall_api.inspector.schema import DetectedItem, InspectorOutput, ObservedOut


def _make_item(**overrides) -> DetectedItem:
    defaults = {
        "name": "banana",
        "box_2d": [100, 100, 300, 300],
        "in_mixed_crate": False,
        "visible_issues": [],
        "evidence": "Fresh yellow bananas.",
        "stage": "fresh",
        "stage_level": "early",
        "worst_stage": "fresh",
        "observed": ObservedOut(method="count", min=12, max=12),
        "sale_unit": "dozen",
        "sale_min": 1.0,
        "sale_max": 1.0,
        "confidence": "high",
        "needs_staff_check": False,
        "check_reason": "",
    }
    defaults.update(overrides)
    return DetectedItem(**defaults)


def test_clean_item_drops_invalid_boxes():
    # Not 4 numbers
    assert clean_item(_make_item(box_2d=[100, 200])) is None
    # Inverted ymin/ymax
    assert clean_item(_make_item(box_2d=[500, 100, 400, 300])) is None
    # Inverted xmin/xmax
    assert clean_item(_make_item(box_2d=[100, 500, 300, 400])) is None


def test_clean_item_clamps_and_cleans_name():
    item = _make_item(
        name="  Sindhri   MANGOES   ",
        box_2d=[-50, 0, 1200, 500],
    )
    cleaned = clean_item(item)
    assert cleaned is not None
    assert cleaned.name == "sindhri mangoes"
    assert cleaned.box_2d == [0, 0, 1000, 500]


def test_clean_item_empty_name_becomes_unknown_produce():
    item = _make_item(name="   ")
    cleaned = clean_item(item)
    assert cleaned is not None
    assert cleaned.name == "unknown produce"


def test_grid_computation():
    # Top row
    assert compute_grid(50, 50, 150, 150) == "top-left"
    assert compute_grid(50, 450, 150, 550) == "top-center"
    assert compute_grid(50, 800, 150, 900) == "top-right"

    # Middle row
    assert compute_grid(450, 50, 550, 150) == "middle-left"
    assert compute_grid(400, 400, 600, 600) == "center"
    assert compute_grid(450, 800, 550, 900) == "middle-right"

    # Bottom row
    assert compute_grid(800, 50, 950, 150) == "bottom-left"
    assert compute_grid(800, 450, 950, 550) == "bottom-center"
    assert compute_grid(800, 800, 950, 950) == "bottom-right"


def test_capping_14_groups_keeps_12_largest_by_box_area():
    # 2 tiny groups at the very top (ymin=0..10, area=100)
    small_1 = _make_item(name="small_1", box_2d=[0, 0, 10, 10])
    small_2 = _make_item(name="small_2", box_2d=[10, 10, 20, 20])

    # 12 large groups lower down (area = 50 * 50 = 2500)
    large_items = [
        _make_item(name=f"large_{i}", box_2d=[100 + i * 50, 100, 150 + i * 50, 150])
        for i in range(12)
    ]

    all_14 = [small_1, small_2] + large_items
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=all_14)
    _, _, _, drafts = apply_guardrails(out)

    assert len(drafts) == 12
    kept_names = {d.name for d in drafts}
    assert "small_1" not in kept_names
    assert "small_2" not in kept_names
    assert kept_names == {f"large_{i}" for i in range(12)}

    # Verify kept groups are sorted top-to-bottom, left-to-right
    for idx in range(len(drafts) - 1):
        curr = (drafts[idx].position.ymin, drafts[idx].position.xmin)
        nxt = (drafts[idx + 1].position.ymin, drafts[idx + 1].position.xmin)
        assert curr <= nxt


def test_worst_stage_raised_if_better_than_stage():
    item = _make_item(stage="ripening", worst_stage="fresh", stage_level="mid")
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    assert len(drafts) == 1
    assert drafts[0].worst_stage == "ripening"


def test_mould_triggers_safety_override_and_bad_pieces():
    # Mould on ripening bananas -> worst_stage becomes unsafe, stage stays ripening
    item = _make_item(
        stage="ripening",
        worst_stage="ripening",
        stage_level="mid",
        visible_issues=["mould"],
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.stage == "ripening"
    assert d.worst_stage == "unsafe"
    assert "safety_override" in d.staff_check_reasons
    assert "bad_pieces_in_group" in d.staff_check_reasons
    assert d.needs_staff_check is True


def test_rot_triggers_safety_override_spoiled():
    item = _make_item(
        stage="overripe",
        worst_stage="overripe",
        stage_level="mid",
        visible_issues=["rot"],
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    d = drafts[0]
    assert d.worst_stage == "spoiled"
    assert "safety_override" in d.staff_check_reasons


def test_score_table_values():
    assert SCORE_TABLE[("fresh", "early")] == 95.0
    assert SCORE_TABLE[("fresh", "mid")] == 88.0
    assert SCORE_TABLE[("fresh", "late")] == 81.0
    assert SCORE_TABLE[("ripening", "mid")] == 69.0
    assert SCORE_TABLE[("overripe", "late")] == 37.0
    assert SCORE_TABLE[("spoiled", "early")] == 30.0
    assert SCORE_TABLE[("unsafe", "late")] == 2.0


def test_confidence_mapping():
    assert CONFIDENCE_MAP["high"] == 0.9
    assert CONFIDENCE_MAP["medium"] == 0.65
    assert CONFIDENCE_MAP["low"] == 0.35


def test_photo_status_no_produce_drops_items():
    item = _make_item()
    out = InspectorOutput(
        photo_status="no_produce",
        photo_note="A chair in a room",
        photo_issues=[],
        items=[item],
    )
    status, note, issues, drafts = apply_guardrails(out)
    assert status == "no_produce"
    assert drafts == []


def test_photo_status_ok_with_zero_valid_items_becomes_no_produce():
    # Only invalid items that get dropped
    item = _make_item(box_2d=[500, 100, 400, 300])  # invalid box
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    status, note, issues, drafts = apply_guardrails(out)
    assert status == "no_produce"
    assert note == "No produce found"
    assert drafts == []


def test_quantity_dozen_from_pieces():
    # 30 bananas counted -> 2.5 dozen
    item = _make_item(
        observed=ObservedOut(method="count", min=30, max=30),
        sale_unit="dozen",
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    assert drafts[0].quantity.low == 2.5
    assert drafts[0].quantity.high == 2.5


def test_observed_quantity_swapped_min_max_and_fill_cap():
    item = _make_item(
        observed=ObservedOut(method="fill_level", min=90, max=40),
        sale_unit="kg",
        sale_min=20.0,
        sale_max=10.0,
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    d = drafts[0]
    assert d.observed.min == 40
    assert d.observed.max == 90
    assert d.quantity.low == 10.0
    assert d.quantity.high == 20.0


def test_unknown_produce_triggers_staff_check():
    item = _make_item(name="unknown produce")
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    d = drafts[0]
    assert "unknown_produce" in d.staff_check_reasons
    assert d.needs_staff_check is True


def test_merge_neighbours_two_touching_tomatoes_sum_counts():
    t1 = _make_item(
        name="tomato",
        box_2d=[100, 100, 200, 200],
        observed=ObservedOut(method="count", min=10, max=20),
        sale_unit="kg",
        sale_min=2.0,
        sale_max=4.0,
    )
    t2 = _make_item(
        name="tomatoes",
        box_2d=[200, 100, 300, 200],  # touching at y=200
        observed=ObservedOut(method="count", min=15, max=25),
        sale_unit="kg",
        sale_min=3.0,
        sale_max=5.0,
    )
    from lastcall_api.inspector.guardrails import merge_neighbours

    merged = merge_neighbours([t1, t2])
    assert len(merged) == 1
    m = merged[0]
    assert m.box_2d == [100, 100, 300, 200]
    assert m.observed.method == "count"
    assert m.observed.min == 25
    assert m.observed.max == 45
    assert m.sale_min == 5.0
    assert m.sale_max == 9.0


def test_merge_neighbours_same_name_far_apart_stays_two():
    t1 = _make_item(name="tomato", box_2d=[100, 100, 200, 200])
    t2 = _make_item(name="tomato", box_2d=[500, 500, 600, 600])
    from lastcall_api.inspector.guardrails import merge_neighbours

    merged = merge_neighbours([t1, t2])
    assert len(merged) == 2


def test_merge_neighbours_different_names_touching_stays_two():
    t1 = _make_item(name="tomato", box_2d=[100, 100, 200, 200])
    t2 = _make_item(name="apple", box_2d=[200, 100, 300, 200])
    from lastcall_api.inspector.guardrails import merge_neighbours

    merged = merge_neighbours([t1, t2])
    assert len(merged) == 2


def test_merge_neighbours_worst_stage_and_lowest_confidence_win():
    t1 = _make_item(
        name="tomato",
        box_2d=[100, 100, 200, 200],
        stage="fresh",
        worst_stage="ripening",
        confidence="high",
    )
    t2 = _make_item(
        name="tomato",
        box_2d=[210, 100, 310, 200],  # gap of 10 <= 30
        stage="ripening",
        worst_stage="spoiled",
        confidence="low",
    )
    from lastcall_api.inspector.guardrails import merge_neighbours

    merged = merge_neighbours([t1, t2])
    assert len(merged) == 1
    m = merged[0]
    assert m.worst_stage == "spoiled"
    assert m.confidence == "low"


def test_merge_neighbours_chain_of_three_crates_merges_into_one():
    c1 = _make_item(name="orange", box_2d=[100, 100, 200, 200])
    c2 = _make_item(name="oranges", box_2d=[210, 100, 310, 200])
    c3 = _make_item(name="orange", box_2d=[320, 100, 420, 200])
    from lastcall_api.inspector.guardrails import merge_neighbours

    merged = merge_neighbours([c1, c2, c3])
    assert len(merged) == 1
    assert merged[0].box_2d == [100, 100, 420, 200]


def test_staff_check_fallback_builds_all_reasons_in_plain_words():
    # Item has low confidence and is in mixed crate, with empty check_reason
    item = _make_item(
        confidence="low",
        in_mixed_crate=True,
        check_reason="",
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.needs_staff_check is True
    # Must contain both reasons in plain words, e.g. "Low confidence; mixed crate."
    assert "Low confidence" in d.check_reason
    assert "mixed crate" in d.check_reason
    assert "Staff check recommended" not in d.check_reason
    assert d.check_reason == "Low confidence; mixed crate."


def test_merge_neighbours_unknown_produce_never_merges():
    """merge_neighbours must never merge groups named 'unknown produce', even if adjacent."""
    u1 = _make_item(name="unknown produce", box_2d=[100, 100, 200, 200])
    u2 = _make_item(name="unknown produce", box_2d=[210, 100, 310, 200])  # gap 10 px
    merged = merge_neighbours([u1, u2])
    assert len(merged) == 2
    assert merged[0].name == "unknown produce"
    assert merged[1].name == "unknown produce"


@pytest.mark.parametrize(
    "sale_unit,obs_method,obs_min,obs_max,sale_min,sale_max,expected_low,expected_high",
    [
        ("dozen", "count", 1, 1, 0.0, 0.0, 0.1, 0.1),
        ("dozen", "count", 3, 5, 0.0, 0.0, 0.3, 0.4),
        ("dozen", "count", 15, 15, 0.0, 0.0, 1.3, 1.3),
        ("dozen", "count", 30, 30, 0.0, 0.0, 2.5, 2.5),
        ("kg", "fill_level", 50, 50, 0.35, 0.35, 0.4, 0.4),
        ("kg", "fill_level", 50, 50, 0.04, 0.04, 0.0, 0.0),
    ],
)
def test_sale_quantity_rounded_half_up_to_tenth(
    sale_unit, obs_method, obs_min, obs_max, sale_min, sale_max, expected_low, expected_high
):
    item = _make_item(
        observed=ObservedOut(method=obs_method, min=obs_min, max=obs_max),
        sale_unit=sale_unit,
        sale_min=sale_min,
        sale_max=sale_max,
    )
    out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[item])
    _, _, _, drafts = apply_guardrails(out)
    assert len(drafts) == 1
    assert drafts[0].quantity.low == expected_low
    assert drafts[0].quantity.high == expected_high


