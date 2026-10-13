"""Tests for inspector engine and D30 guard policy (Step 4)."""

import ast
import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image

from lastcall_api.inspector.inspector import (
    FORBIDDEN_CONFIG_KEYS,
    InspectorError,
    build_config,
    inspect_photo,
)
from lastcall_api.inspector.schema import DetectedItem, InspectorOutput, ObservedOut
from lastcall_shared.models import BoundingBox, FreshnessResult, ItemAssessment, ObservedQuantity, QuantityEstimate


def _make_dummy_image() -> bytes:
    img = Image.new("RGB", (400, 300), color="green")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_valid_output() -> InspectorOutput:
    item = DetectedItem(
        name="apple",
        box_2d=[100, 100, 300, 300],
        in_mixed_crate=False,
        visible_issues=[],
        evidence="Clean fresh apples.",
        stage="fresh",
        stage_level="early",
        worst_stage="fresh",
        observed=ObservedOut(method="count", min=10, max=10),
        sale_unit="kg",
        sale_min=2.0,
        sale_max=2.0,
        confidence="high",
        needs_staff_check=False,
        check_reason="",
    )
    return InspectorOutput(
        photo_status="ok",
        photo_note="",
        photo_issues=[],
        items=[item],
    )


class FakeResponse:
    def __init__(self, parsed=None, text="", prompt_tokens=100, cand_tokens=50):
        self.parsed = parsed
        self.text = text
        self.usage_metadata = MagicMock(
            prompt_token_count=prompt_tokens,
            candidates_token_count=cand_tokens,
            thoughts_token_count=10,
            cached_content_token_count=0,
        )


class FakeGenAIClient:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.call_count = 0
        self.aio = MagicMock()
        self.aio.models.generate_content = self._generate_content

    async def _generate_content(self, model, contents, config):
        self.call_count += 1
        if not self.responses:
            raise RuntimeError("No more responses configured in FakeGenAIClient")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_d30_guard_forbidden_config_keys():
    """Verifies that build_config contains none of the forbidden parameters (D30)."""
    cfg = build_config()
    cfg_dump = cfg.model_dump(exclude_none=True)
    for key in FORBIDDEN_CONFIG_KEYS:
        assert key not in cfg_dump, f"Forbidden key '{key}' found in build_config dump"


def test_d30_guard_source_code_scan():
    """No inspector module uses a forbidden generation setting outside the FORBIDDEN_CONFIG_KEYS definition.

    Reads the code structure (ast), so formatting can't hide or fake a violation.
    """
    inspector_dir = Path(__file__).parent.parent / "lastcall_api" / "inspector"
    py_files = list(inspector_dir.glob("*.py"))
    assert len(py_files) >= 5

    def is_forbidden_definition(node: ast.AST) -> bool:
        targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        return any(isinstance(t, ast.Name) and t.id == "FORBIDDEN_CONFIG_KEYS" for t in targets)

    violations = []
    for f in py_files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        skip = {id(n) for d in ast.walk(tree) if is_forbidden_definition(d) for n in ast.walk(d)}
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            used = None
            if isinstance(node, ast.Constant) and node.value in FORBIDDEN_CONFIG_KEYS:
                used = node.value
            elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_CONFIG_KEYS:
                used = node.arg
            if used:
                violations.append(f"{f.name}:{getattr(node, 'lineno', '?')} uses forbidden key '{used}'")

    assert not violations, "D30 guard violation detected:\n" + "\n".join(violations)


@pytest.mark.asyncio
async def test_inspect_photo_valid_single_pass():
    valid_out = _make_valid_output()
    fake_client = FakeGenAIClient([FakeResponse(parsed=valid_out)])

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    result = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=False,
    )

    assert result.photo_status == "ok"
    assert len(result.items) == 1
    assert result.items[0].name == "apple"
    assert result.inspector is not None
    assert result.inspector.calls == 1
    assert result.inspector.input_tokens == 100
    assert result.inspector.output_tokens == 60  # 50 candidates + 10 thoughts


@pytest.mark.asyncio
async def test_inspect_photo_retry_on_invalid_json_then_success():
    valid_out = _make_valid_output()
    # First response invalid text, second valid
    fake_client = FakeGenAIClient(
        [
            FakeResponse(text="not valid json"),
            FakeResponse(parsed=valid_out),
        ]
    )

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    result = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=False,
    )
    assert result.inspector.calls == 2
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_inspect_photo_timeout_raises_inspector_error():
    fake_client = FakeGenAIClient(
        [
            asyncio.TimeoutError("timeout 1"),
            asyncio.TimeoutError("timeout 2"),
            asyncio.TimeoutError("timeout 3"),
        ]
    )

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(InspectorError, match="Inspection call failed after retries"):
        await inspect_photo(
            img_bytes,
            mart_id="mart_1",
            shelf_id="shelf_1",
            now=now,
            client=fake_client,
            zoom=False,
        )


@pytest.mark.asyncio
async def test_inspect_photo_with_previous_result_change_note():
    valid_out = _make_valid_output()
    fake_client = FakeGenAIClient([FakeResponse(parsed=valid_out)])

    prev_item = ItemAssessment(
        item_key="apple_top_left",
        name="apple",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.3, xmax=0.3),
        grid="top-left",
        stage="fresh",
        stage_level="mid",
        worst_stage="fresh",
        score=88.0,
        observed=ObservedQuantity(method="count", min=10, max=10),
        quantity=QuantityEstimate(unit="kg", low=2.0, high=2.0),
        confidence=0.9,
        confidence_level="high",
    )
    prev = FreshnessResult(
        mart_id="mart_1",
        shelf_id="shelf_1",
        inspection_id="insp_prev",
        photo_uri="upload:sha256:123",
        taken_at=datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc),
        items=[prev_item],
    )

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    res = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        previous=prev,
        now=now,
        client=fake_client,
        zoom=False,
    )
    assert len(res.items) == 1
    assert res.items[0].item_key == "apple_top_left"
    assert res.items[0].change_since_last is not None
    assert "up 7 points" in res.items[0].change_note


@pytest.mark.asyncio
async def test_inspect_photo_zoom_success():
    # Pass 1 output has worst != stage, qualifying for zoom
    p1_item = DetectedItem(
        name="banana",
        box_2d=[100, 100, 400, 400],
        in_mixed_crate=False,
        visible_issues=["bruising"],
        evidence="Yellow bananas.",
        stage="fresh",
        stage_level="mid",
        worst_stage="overripe",
        observed=ObservedOut(method="count", min=10, max=10),
        sale_unit="dozen",
        sale_min=1.0,
        sale_max=1.0,
        confidence="high",
        needs_staff_check=False,
        check_reason="",
    )
    p1_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[p1_item])

    # Pass 2 crop output: finds worse defect (spoiled)
    crop_item = DetectedItem(
        name="banana",
        box_2d=[50, 50, 950, 950],
        in_mixed_crate=False,
        visible_issues=["bruising", "rot"],
        evidence="Close-up shows rot.",
        stage="ripening",
        stage_level="late",
        worst_stage="spoiled",
        observed=ObservedOut(method="count", min=10, max=10),
        sale_unit="dozen",
        sale_min=1.0,
        sale_max=1.0,
        confidence="high",
        needs_staff_check=True,
        check_reason="Rot on bottom banana.",
    )
    crop_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[crop_item])

    fake_client = FakeGenAIClient([FakeResponse(parsed=p1_out), FakeResponse(parsed=crop_out)])

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    res = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=True,
    )

    assert res.inspector.calls == 2
    assert res.inspector.zoomed_groups == 1
    assert len(res.items) == 1
    item = res.items[0]
    assert item.zoomed is True
    assert item.worst_stage == "spoiled"
    assert "rot" in item.issues


@pytest.mark.asyncio
async def test_inspect_photo_zoom_failure_retains_base_with_lowered_confidence():
    p1_item = DetectedItem(
        name="banana",
        box_2d=[100, 100, 400, 400],
        in_mixed_crate=False,
        visible_issues=[],
        evidence="Yellow bananas.",
        stage="fresh",
        stage_level="mid",
        worst_stage="ripening",
        observed=ObservedOut(method="count", min=10, max=10),
        sale_unit="dozen",
        sale_min=1.0,
        sale_max=1.0,
        confidence="high",
        needs_staff_check=False,
        check_reason="",
    )
    p1_out = InspectorOutput(photo_status="ok", photo_note="", photo_issues=[], items=[p1_item])

    # Crop call raises an exception
    fake_client = FakeGenAIClient([FakeResponse(parsed=p1_out), RuntimeError("crop call error")])

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    res = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=True,
    )

    assert res.inspector.zoom_failures == 1
    assert len(res.items) == 1
    item = res.items[0]
    # Confidence lowered from high (0.9) to medium (0.65)
    assert item.confidence == 0.65
    assert item.confidence_level == "medium"


@pytest.mark.asyncio
async def test_400_is_not_retried():
    """Verifies that non-retryable 400 INVALID_ARGUMENT fails immediately without retry."""
    from google.genai import errors

    err_400 = errors.APIError(400, "INVALID_ARGUMENT: Invalid schema or prompt")
    fake_client = FakeGenAIClient([err_400, _make_valid_output()])

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(InspectorError) as exc_info:
        await inspect_photo(
            img_bytes,
            mart_id="mart_1",
            shelf_id="shelf_1",
            now=now,
            client=fake_client,
            zoom=False,
        )

    assert "non-retryable" in str(exc_info.value) or "400" in str(exc_info.value)
    # Crucial assertion: exactly 1 call was made, no retry
    assert fake_client.call_count == 1


@pytest.mark.asyncio
async def test_503_is_retried():
    """Verifies that 503 UNAVAILABLE is retried and succeeds on attempt 2."""
    from google.genai import errors

    err_503 = errors.APIError(503, "Service Unavailable")
    valid_resp = FakeResponse(parsed=_make_valid_output())
    fake_client = FakeGenAIClient([err_503, valid_resp])

    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

    res = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=False,
    )

    assert res.photo_status == "ok"
    assert len(res.items) == 1
    # Crucial assertion: exactly 2 calls made (attempt 1 failed 503, attempt 2 succeeded)
    assert fake_client.call_count == 2


@pytest.mark.asyncio
async def test_hedging_slow_then_fast_client(monkeypatch):
    """Verifies that hedging spawns a 2nd identical request after HEDGE_AFTER_S,

    and the faster response wins while cancelling the slower one.
    """
    import lastcall_api.inspector.inspector as insp_mod

    # Set hedge delay to 50ms for fast test execution
    monkeypatch.setattr(insp_mod, "HEDGE_AFTER_S", 0.05)

    invocations = 0

    class SlowThenFastAioModels:
        async def generate_content(self, *args, **kwargs):
            nonlocal invocations
            invocations += 1
            cur_idx = invocations
            if cur_idx == 1:
                # First call is slow (simulates tail spike)
                await asyncio.sleep(2.0)
                return FakeResponse(parsed=_make_valid_output(), prompt_tokens=100, cand_tokens=50)
            else:
                # Hedged second call is fast
                await asyncio.sleep(0.01)
                return FakeResponse(parsed=_make_valid_output(), prompt_tokens=100, cand_tokens=50)

    class FakeClientWithHedging:
        def __init__(self):
            self.aio = MagicMock()
            self.aio.models = SlowThenFastAioModels()

    fake_client = FakeClientWithHedging()
    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

    res = await inspect_photo(
        img_bytes,
        mart_id="mart_1",
        shelf_id="shelf_1",
        now=now,
        client=fake_client,
        zoom=False,
    )

    assert res.photo_status == "ok"
    assert len(res.items) == 1
    # Both calls were started due to hedging
    assert invocations == 2
    assert res.inspector.calls == 2
    assert res.inspector.hedges == 1


@pytest.mark.asyncio
async def test_no_hedge_when_less_than_3s_left(monkeypatch):
    """Verifies that no hedged call is launched if remaining attempt timeout is < 3.0s."""
    import lastcall_api.inspector.inspector as insp_mod

    # Set HEDGE_AFTER_S to 0.05
    monkeypatch.setattr(insp_mod, "HEDGE_AFTER_S", 0.05)

    invocations = 0

    class TrackingAioModels:
        async def generate_content(self, *args, **kwargs):
            nonlocal invocations
            invocations += 1
            # Takes 0.1s (finishes after hedge delay 0.05s)
            await asyncio.sleep(0.1)
            return FakeResponse(parsed=_make_valid_output(), prompt_tokens=100, cand_tokens=50)

    class FakeClient:
        def __init__(self):
            self.aio = MagicMock()
            self.aio.models = TrackingAioModels()

    fake_client = FakeClient()
    img_bytes = _make_dummy_image()
    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

    # Call _call directly with per_attempt_timeout = 1.0s (less than 3s left after 0.05s hedge delay: 0.95s < 3.0s)
    output, usage, attempts, was_hedged = await insp_mod._call(
        fake_client,
        img_bytes,
        "test prompt",
        insp_mod.build_config("low"),
        deadline=asyncio.get_event_loop().time() + 10.0,
        per_attempt_timeout=1.0,
    )

    assert output.photo_status == "ok"
    assert invocations == 1
    assert attempts == 1
    assert was_hedged is False
