"""Unit tests for inspector eval metrics (Step 6)."""

from lastcall_api.inspector.eval_metrics import (
    LabelRow,
    calculate_confusion_matrix,
    calculate_consistency,
    calculate_lenient_stage_accuracy,
    calculate_strict_stage_accuracy,
    calculate_worst_stage_accuracy,
    check_edge_photo,
    find_critical_misses,
    find_false_alarms,
    match_labels_to_predictions,
)
from lastcall_shared.models import (
    BoundingBox,
    FreshnessResult,
    ItemAssessment,
    ObservedQuantity,
    QuantityEstimate,
)


def _make_assessment(
    name: str = "apple",
    stage: str = "fresh",
    worst_stage: str | None = None,
    grid: str = "center",
    box: tuple[float, float, float, float] = (0.2, 0.2, 0.4, 0.4),
    needs_staff_check: bool = False,
    confidence_level: str = "high",
) -> ItemAssessment:
    effective_worst = worst_stage if worst_stage is not None else stage
    return ItemAssessment(
        item_key="item_0",
        name=name,
        position=BoundingBox(ymin=box[0], xmin=box[1], ymax=box[2], xmax=box[3]),
        grid=grid,
        in_mixed_crate=False,
        issues=[],
        evidence="Evidence text.",
        stage=stage,
        stage_level="mid",
        worst_stage=effective_worst,
        score=88.0,
        observed=ObservedQuantity(method="count", min=10, max=10),
        quantity=QuantityEstimate(unit="kg", low=2.0, high=2.0),
        confidence=0.9,
        confidence_level=confidence_level,
        needs_staff_check=needs_staff_check,
        staff_check_reasons=[],
        check_reason="",
        zoomed=False,
    )


def test_matching_prefers_grid_and_largest_box():
    lbl = LabelRow(
        filename="shelf1.jpg",
        item="apple",
        grid="top-left",
        expected_stage="fresh",
    )

    # Two apple predictions: one with matching grid, one with non-matching grid but larger box
    pred_other_grid = _make_assessment(
        name="apple",
        grid="bottom-right",
        box=(0.6, 0.6, 0.9, 0.9),  # area = 0.09
    )
    pred_match_grid = _make_assessment(
        name="apple",
        grid="top-left",
        box=(0.0, 0.0, 0.2, 0.2),  # area = 0.04
    )

    matched = match_labels_to_predictions([lbl], [pred_other_grid, pred_match_grid])
    assert len(matched) == 1
    assert matched[0][1] is pred_match_grid


def test_matching_variant_names():
    lbl = LabelRow(
        filename="shelf1.jpg",
        item="orange;sweet lime;kinnow",
        expected_stage="fresh",
    )
    pred = _make_assessment(name="sweet lime")
    matched = match_labels_to_predictions([lbl], [pred])
    assert len(matched) == 1
    assert matched[0][1] is pred


def test_strict_and_lenient_accuracy():
    lbl1 = LabelRow(
        filename="s1.jpg",
        item="banana",
        expected_stage="ripening",
        acceptable_stages=["fresh"],
    )
    lbl2 = LabelRow(
        filename="s1.jpg",
        item="apple",
        expected_stage="fresh",
    )

    pred1 = _make_assessment(name="banana", stage="fresh")  # acceptable, but not strict match
    pred2 = _make_assessment(name="apple", stage="fresh")   # exact match

    matches = [(lbl1, pred1), (lbl2, pred2)]
    assert calculate_strict_stage_accuracy(matches) == 0.5
    assert calculate_lenient_stage_accuracy(matches) == 1.0


def test_worst_stage_accuracy():
    lbl = LabelRow(
        filename="s1.jpg",
        item="banana",
        expected_stage="ripening",
        expected_worst_stage="overripe",
    )
    pred_correct = _make_assessment(name="banana", stage="ripening", worst_stage="overripe")
    assert calculate_worst_stage_accuracy([(lbl, pred_correct)]) == 1.0

    pred_wrong = _make_assessment(name="banana", stage="ripening", worst_stage="ripening")
    assert calculate_worst_stage_accuracy([(lbl, pred_wrong)]) == 0.0


def test_critical_miss_detection():
    lbl_bad = LabelRow(
        filename="bad_apples.jpg",
        item="apple",
        expected_stage="spoiled",
    )
    # Model said fresh with no staff check -> CRITICAL MISS
    pred_miss = _make_assessment(name="apple", stage="fresh", worst_stage="fresh", needs_staff_check=False)
    misses = find_critical_misses([(lbl_bad, pred_miss)])
    assert len(misses) == 1
    assert misses[0]["filename"] == "bad_apples.jpg"

    # If model flagged staff check, not a critical miss
    pred_flagged = _make_assessment(name="apple", stage="fresh", worst_stage="fresh", needs_staff_check=True)
    misses_safe = find_critical_misses([(lbl_bad, pred_flagged)])
    assert len(misses_safe) == 0


def test_false_alarm_detection():
    lbl_fresh = LabelRow(
        filename="fresh.jpg",
        item="banana",
        expected_stage="fresh",
    )
    # Model said spoiled -> FALSE ALARM
    pred_alarm = _make_assessment(name="banana", stage="spoiled", worst_stage="spoiled")
    alarms = find_false_alarms([(lbl_fresh, pred_alarm)])
    assert len(alarms) == 1
    assert alarms[0]["filename"] == "fresh.jpg"


def test_confusion_matrix():
    lbl = LabelRow(filename="s.jpg", item="apple", expected_stage="fresh")
    pred = _make_assessment(name="apple", stage="ripening")
    matrix = calculate_confusion_matrix([(lbl, pred)])
    assert matrix["fresh"]["ripening"] == 1
    assert matrix["fresh"]["fresh"] == 0


def test_edge_photo_verification():
    from datetime import datetime, timezone

    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    res_blurry = FreshnessResult(
        schema_version="3.0.0",
        mart_id="m1",
        shelf_id="s1",
        inspection_id="i1",
        photo_uri="upload:sha256:abc",
        taken_at=now,
        photo_status="unreadable",
        items=[],
    )
    assert check_edge_photo("blurry", res_blurry) is True

    res_no_prod = FreshnessResult(
        schema_version="3.0.0",
        mart_id="m1",
        shelf_id="s1",
        inspection_id="i2",
        photo_uri="upload:sha256:abc",
        taken_at=now,
        photo_status="no_produce",
        items=[],
    )
    assert check_edge_photo("no_produce", res_no_prod) is True


def test_consistency_calculation():
    it1 = _make_assessment(name="banana", stage="fresh", worst_stage="fresh")
    it2_same = _make_assessment(name="banana", stage="fresh", worst_stage="fresh")
    it2_diff = _make_assessment(name="banana", stage="ripening", worst_stage="ripening")

    assert calculate_consistency([it1], [it2_same]) == 1.0
    assert calculate_consistency([it1], [it2_diff]) == 0.0
