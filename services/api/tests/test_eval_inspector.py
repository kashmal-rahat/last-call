"""End-to-end unit test for eval runner using fake inspect function (Step 6)."""

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from lastcall_shared.models import (
    BoundingBox,
    FreshnessResult,
    InspectorMeta,
    ItemAssessment,
    ObservedQuantity,
    QuantityEstimate,
)
from scripts.eval_inspector import run_evaluation


def _make_photo_file(p: Path) -> None:
    img = Image.new("RGB", (200, 200), color="red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    p.write_bytes(buf.getvalue())


@pytest.mark.asyncio
async def test_run_evaluation_end_to_end(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    labels_csv = tmp_path / "labels.csv"
    runs_dir = tmp_path / "runs"
    results_dir = tmp_path / "results"

    _make_photo_file(photos_dir / "shelf1.jpg")
    _make_photo_file(photos_dir / "shelf2.jpg")

    # 3-row temporary labels.csv
    csv_content = """filename,split,photo_kind,series_id,seq,item,grid,expected_stage,acceptable_stages,expected_worst_stage,true_count,true_kg,notes
shelf1.jpg,test,normal,,,apple,top-left,fresh,,fresh,10,2.0,Good apples
shelf1.jpg,test,normal,,,banana,bottom-right,ripening,,overripe,6,1.0,Bananas
shelf2.jpg,test,normal,,,tomato,center,fresh,,fresh,20,3.0,Tomatoes
"""
    labels_csv.write_text(csv_content, encoding="utf-8")

    async def fake_inspect(raw_bytes, *, mart_id, shelf_id, previous=None, now=None, zoom=False, thinking_level=None):
        meta = InspectorMeta(
            model="fake-flash",
            prompt_version="1.0",
            thinking_level="low",
            latency_ms=1200,
            calls=1,
            input_tokens=1000,
            output_tokens=200,
        )
        now_dt = now or datetime.now(timezone.utc)
        items = [
            ItemAssessment(
                item_key="item_0",
                name="apple",
                position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.3, xmax=0.3),
                grid="top-left",
                in_mixed_crate=False,
                issues=[],
                evidence="Crisp apple",
                stage="fresh",
                stage_level="mid",
                worst_stage="fresh",
                score=88.0,
                observed=ObservedQuantity(method="count", min=10, max=10),
                quantity=QuantityEstimate(unit="kg", low=2.0, high=2.0),
                confidence=0.9,
                confidence_level="high",
                needs_staff_check=False,
            ),
            ItemAssessment(
                item_key="item_1",
                name="banana",
                position=BoundingBox(ymin=0.7, xmin=0.7, ymax=0.9, xmax=0.9),
                grid="bottom-right",
                in_mixed_crate=False,
                issues=[],
                evidence="Ripe banana",
                stage="ripening",
                stage_level="mid",
                worst_stage="overripe",
                score=69.0,
                observed=ObservedQuantity(method="count", min=6, max=6),
                quantity=QuantityEstimate(unit="dozen", low=0.5, high=0.5),
                confidence=0.9,
                confidence_level="high",
                needs_staff_check=False,
            ),
        ]
        return FreshnessResult(
            schema_version="3.0.0",
            mart_id=mart_id,
            shelf_id=shelf_id,
            inspection_id="insp_123",
            photo_uri="upload:sha256:abc",
            taken_at=now_dt,
            photo_status="ok",
            items=items,
            inspector=meta,
        )

    res = await run_evaluation(
        labels_csv=labels_csv,
        photos_dir=photos_dir,
        runs_dir=runs_dir,
        results_dir=results_dir,
        split="test",
        runs=2,
        inspect_fn=fake_inspect,
    )

    assert "zoom_on" in res
    m = res["zoom_on"]
    assert m["strict_acc"] == 1.0
    assert m["worst_acc"] == 1.0
    assert len(m["critical_misses"]) == 0
    assert (results_dir / "eval.md").exists()
    assert (results_dir / "eval.md").read_text().startswith("# Freshness Inspector Evaluation Results")


@pytest.mark.asyncio
async def test_eval_inspector_records_and_excludes_errors(tmp_path: Path):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    labels_csv = tmp_path / "labels.csv"
    runs_dir = tmp_path / "runs"
    results_dir = tmp_path / "results"

    _make_photo_file(photos_dir / "shelf_ok.jpg")
    _make_photo_file(photos_dir / "shelf_err.jpg")

    csv_content = """filename,split,photo_kind,series_id,seq,item,grid,expected_stage,acceptable_stages,expected_worst_stage,true_count,true_kg,notes
shelf_ok.jpg,test,normal,,,apple,top-left,fresh,,fresh,10,2.0,Ok
shelf_err.jpg,test,normal,,,banana,center,spoiled,,spoiled,5,1.0,Err
"""
    labels_csv.write_text(csv_content, encoding="utf-8")

    async def inspect_with_error(
        raw_bytes, *, mart_id, shelf_id, previous=None, now=None, zoom=False, thinking_level=None
    ):
        if b"shelf_err" in raw_bytes or shelf_id == "eval_shelf":
            # For shelf_err raise exception
            pass
        # Let's inspect by checking photo
        # In run_evaluation, inspect_fn gets raw_bytes. Let's make shelf_err raise RuntimeError
        if len(raw_bytes) == 1234:  # marker or by counter
            pass

    call_count = 0

    async def inspect_mock(raw_bytes, *, mart_id, shelf_id, previous=None, now=None, zoom=False, thinking_level=None):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:
            raise RuntimeError("Gemini connection timed out")
        meta = InspectorMeta(
            model="fake-flash",
            prompt_version="1.0",
            thinking_level="low",
            latency_ms=1000,
            calls=1,
            input_tokens=1000,
            output_tokens=200,
        )
        return FreshnessResult(
            schema_version="3.0.0",
            mart_id=mart_id,
            shelf_id=shelf_id,
            inspection_id="insp_ok",
            photo_uri="upload:123",
            taken_at=datetime.now(timezone.utc),
            photo_status="ok",
            items=[
                ItemAssessment(
                    item_key="item_0",
                    name="apple",
                    position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.3, xmax=0.3),
                    grid="top-left",
                    in_mixed_crate=False,
                    issues=[],
                    evidence="Good",
                    stage="fresh",
                    stage_level="mid",
                    worst_stage="fresh",
                    score=88.0,
                    observed=ObservedQuantity(method="count", min=10, max=10),
                    quantity=QuantityEstimate(unit="kg", low=2.0, high=2.0),
                    confidence=0.9,
                    confidence_level="high",
                    needs_staff_check=False,
                )
            ],
            inspector=meta,
        )

    res = await run_evaluation(
        labels_csv=labels_csv,
        photos_dir=photos_dir,
        runs_dir=runs_dir,
        results_dir=results_dir,
        split="test",
        runs=1,
        inspect_fn=inspect_mock,
    )

    m = res["zoom_on"]
    assert m["errors_count"] == 1
    assert len(m["errors"]) == 1
    assert "Gemini connection timed out" in m["errors"][0]["reason"]
    # Crucially, errored photo is NOT counted as a critical miss
    assert len(m["critical_misses"]) == 0
    assert m["strict_acc"] == 1.0
