"""Unit tests for zoom selection and merging (Step 4, D29)."""

from lastcall_api.inspector.schema import DetectedItem, InspectorOutput, ObservedOut
from lastcall_api.inspector.zoom import merge_zoom, select_for_zoom


def _make_item(**overrides) -> DetectedItem:
    defaults = {
        "name": "banana",
        "box_2d": [100, 100, 300, 300],
        "in_mixed_crate": False,
        "visible_issues": [],
        "evidence": "Yellow bananas.",
        "stage": "fresh",
        "stage_level": "mid",
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


def test_select_for_zoom_clean_single_group_gets_no_crops():
    # Large, clear, high-confidence, evenly fresh single group
    # box covers (800-100)/1000 * (800-100)/1000 = 0.7 * 0.7 = 0.49 (> 0.15)
    item = _make_item(box_2d=[100, 100, 800, 800], stage="fresh", worst_stage="fresh", confidence="high")
    selected = select_for_zoom([item])
    assert selected == []


def test_select_for_zoom_priority_and_cap():
    # Create 8 candidate items with different rules
    # Item 0: Rule 2 (worst != stage)
    it0 = _make_item(worst_stage="ripening", stage="fresh")
    # Item 1: Rule 1 (rot)
    it1 = _make_item(visible_issues=["rot"])
    # Item 2: Rule 3 (confidence low)
    it2 = _make_item(confidence="low")
    # Item 3: Rule 4 (stage_level late)
    it3 = _make_item(stage_level="late")
    # Item 4: Rule 5 (small box in multi-item display)
    it4 = _make_item(box_2d=[10, 10, 50, 50])
    # Item 5: Rule 6 (count wide range: 10 to 30)
    it5 = _make_item(observed=ObservedOut(method="count", min=10, max=30))
    # Item 6: Another rule 1 (mould, smaller box)
    it6 = _make_item(visible_issues=["mould"], box_2d=[10, 10, 100, 100])
    # Item 7: Another rule 1 (slime, larger box)
    it7 = _make_item(visible_issues=["slime"], box_2d=[10, 10, 500, 500])

    items = [it0, it1, it2, it3, it4, it5, it6, it7]
    selected = select_for_zoom(items, max_crops=6)

    assert len(selected) == 6
    # Rule 1 items (it1, it6, it7) must be first, sorted by box area smaller first
    assert selected[0] == 6  # mould, area = 0.09 * 0.09
    assert selected[1] in (1, 7)


def test_merge_zoom_failed_crop_lowers_confidence():
    base = _make_item(confidence="high")
    merged, reasons = merge_zoom(base, None)
    assert merged.confidence == "medium"
    assert reasons == []

    merged2, _ = merge_zoom(base.model_copy(update={"confidence": "medium"}), None)
    assert merged2.confidence == "low"


def test_merge_zoom_name_mismatch_yields_disagreement():
    base = _make_item(name="banana", confidence="high")
    crop_item = _make_item(name="orange")
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    merged, reasons = merge_zoom(base, crop_out)
    assert merged.name == "banana"
    assert merged.confidence == "low"
    assert "zoom_disagreement" in reasons


def test_merge_zoom_quantity_from_crop_when_both_count():
    base = _make_item(
        observed=ObservedOut(method="count", min=10, max=20),
        sale_min=1.0,
        sale_max=2.0,
    )
    crop_item = _make_item(
        observed=ObservedOut(method="count", min=14, max=16),
        sale_min=1.2,
        sale_max=1.4,
    )
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    merged, _ = merge_zoom(base, crop_out)
    assert merged.observed.min == 14
    assert merged.observed.max == 16
    assert merged.sale_min == 1.2
    assert merged.sale_max == 1.4


def test_merge_zoom_quantity_keeps_base_when_fill_level():
    base = _make_item(
        observed=ObservedOut(method="fill_level", min=50, max=70),
        sale_min=5.0,
        sale_max=7.0,
    )
    crop_item = _make_item(
        observed=ObservedOut(method="count", min=10, max=10),
        sale_min=1.0,
        sale_max=1.0,
    )
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    merged, _ = merge_zoom(base, crop_out)
    assert merged.observed.method == "fill_level"
    assert merged.observed.min == 50
    assert merged.sale_min == 5.0


def test_merge_zoom_worse_worst_stage_and_issues_union():
    base = _make_item(
        worst_stage="overripe",
        visible_issues=["bruising"],
    )
    crop_item = _make_item(
        worst_stage="spoiled",
        visible_issues=["dark_spots", "bruising"],
    )
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    merged, _ = merge_zoom(base, crop_out)
    assert merged.worst_stage == "spoiled"
    assert set(merged.visible_issues) == {"bruising", "dark_spots"}


def test_merge_zoom_stages_two_steps_apart_causes_disagreement():
    base = _make_item(stage="fresh", confidence="high")
    # 2 steps worse: overripe
    crop_item = _make_item(stage="overripe", confidence="high")
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    merged, reasons = merge_zoom(base, crop_out)
    assert merged.confidence == "low"
    assert "zoom_disagreement" in reasons


def test_select_for_zoom_box_area_rules():
    # 1. Single group with box area 0.8 and worst_stage != stage -> not zoomed
    it_large = _make_item(
        box_2d=[0, 0, 800, 1000],  # area = 0.8 * 1.0 = 0.8
        stage="fresh",
        worst_stage="ripening",
    )
    assert select_for_zoom([it_large]) == []

    # 2. Two groups with areas 0.51 and 0.49, both medium confidence -> neither zoomed
    it_51 = _make_item(box_2d=[0, 0, 510, 1000], confidence="medium")  # 0.51
    it_49 = _make_item(box_2d=[510, 0, 1000, 1000], confidence="medium")  # 0.49
    assert select_for_zoom([it_51, it_49]) == []

    # 3. Single group with area 0.2 and medium confidence -> zoomed
    it_20 = _make_item(box_2d=[0, 0, 400, 500], confidence="medium")  # 0.4 * 0.5 = 0.2
    assert select_for_zoom([it_20]) == [0]

    # 4. A 900x200 strip (area 0.18) with medium confidence -> zoomed
    it_strip = _make_item(box_2d=[0, 0, 900, 200], confidence="medium")  # 0.9 * 0.2 = 0.18
    assert select_for_zoom([it_strip]) == [0]
