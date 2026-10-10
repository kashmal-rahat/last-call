"""Unit tests for inspector matching across photos (Step 4)."""

from datetime import datetime, timezone
import pytest

from lastcall_api.inspector.guardrails import ItemDraft
from lastcall_api.inspector.matching import assign_keys, names_match
from lastcall_shared.models import (
    BoundingBox,
    FreshnessResult,
    ItemAssessment,
    ObservedQuantity,
    QuantityEstimate,
)


def _make_draft(name="banana", box=(0.1, 0.1, 0.4, 0.4), grid="top-left", score=88.0, worst="fresh") -> ItemDraft:
    return ItemDraft(
        name=name,
        position=BoundingBox(ymin=box[0], xmin=box[1], ymax=box[2], xmax=box[3]),
        grid=grid,
        stage="fresh",
        stage_level="mid",
        worst_stage=worst,
        score=score,
        observed=ObservedQuantity(method="count", min=12, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )


def _make_prev_result(items: list[ItemAssessment], taken_at: datetime) -> FreshnessResult:
    return FreshnessResult(
        mart_id="mart_1",
        shelf_id="shelf_1",
        inspection_id="insp_prev",
        photo_uri="upload:sha256:123",
        taken_at=taken_at,
        items=items,
    )


def test_names_match():
    assert names_match("banana", "banana") is True
    assert names_match("banana", "bananas") is True
    assert names_match("apples", "apple") is True
    assert names_match("tomatoes", "tomato") is True
    assert names_match("mangoes", "mango") is True
    assert names_match("apple", "orange") is False


def test_matching_same_name_overlapping_box_reuses_key_and_computes_delta():
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    prev_time = datetime(2026, 10, 9, 9, 0, 0, tzinfo=timezone.utc)

    prev_item = ItemAssessment(
        item_key="banana_top_left",
        name="banana",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="top-left",
        stage="fresh",
        stage_level="early",
        worst_stage="fresh",
        score=95.0,
        observed=ObservedQuantity(method="count", min=12, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev_res = _make_prev_result([prev_item], prev_time)

    # New draft with slightly lower score (88.0)
    draft = _make_draft(name="bananas", box=(0.1, 0.1, 0.4, 0.4), score=88.0)
    results = assign_keys([draft], prev_res, now=now)

    assert len(results) == 1
    item = results[0]
    assert item.item_key == "banana_top_left"
    assert item.change_since_last == -7.0
    assert "dropped 7 points" in (item.change_note or "")


def test_same_name_far_box_gets_new_key():
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    prev_time = datetime(2026, 10, 9, 9, 0, 0, tzinfo=timezone.utc)

    prev_item = ItemAssessment(
        item_key="banana_top_left",
        name="banana",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="top-left",
        stage="fresh",
        stage_level="early",
        worst_stage="fresh",
        score=95.0,
        observed=ObservedQuantity(method="count", min=12, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev_res = _make_prev_result([prev_item], prev_time)

    # New draft located far away in bottom-right (IoU = 0)
    draft = _make_draft(name="banana", box=(0.7, 0.7, 0.95, 0.95), grid="bottom-right", score=88.0)
    results = assign_keys([draft], prev_res, now=now)

    assert len(results) == 1
    assert results[0].item_key == "banana_bottom_right"
    assert results[0].change_since_last is None


def test_different_name_same_box_gets_new_key():
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    prev_time = datetime(2026, 10, 9, 9, 0, 0, tzinfo=timezone.utc)

    prev_item = ItemAssessment(
        item_key="apple_top_left",
        name="apple",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="top-left",
        stage="fresh",
        stage_level="early",
        worst_stage="fresh",
        score=95.0,
        observed=ObservedQuantity(method="count", min=12, max=12),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev_res = _make_prev_result([prev_item], prev_time)

    # New draft is banana at same position
    draft = _make_draft(name="banana", box=(0.1, 0.1, 0.4, 0.4), grid="top-left", score=88.0)
    results = assign_keys([draft], prev_res, now=now)

    assert results[0].item_key == "banana_top_left"
    assert results[0].change_since_last is None


def test_worst_pieces_getting_worse_appended_to_change_note():
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    prev_time = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)  # yesterday

    prev_item = ItemAssessment(
        item_key="tomato_center",
        name="tomato",
        position=BoundingBox(ymin=0.3, xmin=0.3, ymax=0.6, xmax=0.6),
        grid="center",
        stage="ripening",
        stage_level="mid",
        worst_stage="ripening",
        score=69.0,
        observed=ObservedQuantity(method="count", min=20, max=20),
        quantity=QuantityEstimate(unit="kg", low=5.0, high=5.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev_res = _make_prev_result([prev_item], prev_time)

    draft = _make_draft(
        name="tomato",
        box=(0.3, 0.3, 0.6, 0.6),
        grid="center",
        score=50.0,
        worst="spoiled",
    )
    results = assign_keys([draft], prev_res, now=now)
    assert len(results) == 1
    assert "worst pieces now spoiled" in results[0].change_note
    assert "yesterday" in results[0].change_note


def test_unmatched_draft_does_not_steal_matched_draft_key():
    """A new draft whose base key equals a matched draft's previous key does not steal it.
    The matched draft keeps its key and change_note."""
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    prev_time = datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc)

    # Previous had a banana in top-left with key "banana_top_left"
    prev_item = ItemAssessment(
        item_key="banana_top_left",
        name="banana",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="top-left",
        stage="fresh",
        stage_level="mid",
        worst_stage="fresh",
        score=88.0,
        observed=ObservedQuantity(method="count", min=10, max=10),
        quantity=QuantityEstimate(unit="dozen", low=1.0, high=1.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev_res = _make_prev_result([prev_item], prev_time)

    # In the new photo:
    # draft 0 is UNMATCHED (far away at bottom-right, but grid labeled "top-left" so its base key is banana_top_left)
    unmatched_draft = _make_draft(
        name="banana",
        box=(0.7, 0.7, 0.95, 0.95),
        grid="top-left",
        score=88.0,
    )
    # draft 1 is MATCHED with prev_item (overlaps IoU >= 0.3)
    matched_draft = _make_draft(
        name="banana",
        box=(0.1, 0.1, 0.4, 0.4),
        grid="top-left",
        score=81.0,
    )

    results = assign_keys([unmatched_draft, matched_draft], prev_res, now=now)

    assert len(results) == 2
    # draft 1 kept its key and got its change note
    assert results[1].item_key == "banana_top_left"
    assert results[1].change_since_last == -7.0
    assert "dropped 7 points" in (results[1].change_note or "")

    # draft 0 did not steal "banana_top_left"; got "banana_top_left_2"
    assert results[0].item_key == "banana_top_left_2"
    assert results[0].change_since_last is None
