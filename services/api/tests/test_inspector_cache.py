"""Tests for Module 1 follow-up F1: inspector reading cache (D45)."""

import io
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lastcall_api.inspector.inspector import (
    READING_CACHE_VERSION,
    build_config,
    inspect_photo,
    reading_key,
)
from lastcall_api.inspector.prompt import PROMPT_VERSION
from lastcall_api.inspector.schema import DetectedItem, InspectorOutput, ObservedOut
from lastcall_api.main import app, _IP_REQUEST_HISTORY
from lastcall_shared.config import get_settings
from lastcall_shared.models import FreshnessResult, ItemAssessment
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345-at-least-32-chars-long"
CODE = "test-judge-access-code"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup_api_test(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    monkeypatch.setenv("DEMO_DAILY_INSPECT_CAP", "100")
    monkeypatch.setenv("IP_RATE_LIMIT_PER_HOUR", "20")
    get_settings.cache_clear()
    _IP_REQUEST_HISTORY.clear()
    store = InMemoryStore()
    app.state.store = store
    return store


def _make_dummy_image(color: str = "green") -> bytes:
    img = Image.new("RGB", (400, 300), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_valid_output(
    name: str = "apple",
    stage: str = "fresh",
    worst_stage: str = "fresh",
    visible_issues: list[str] | None = None,
) -> InspectorOutput:
    item = DetectedItem(
        name=name,
        box_2d=[100, 100, 300, 300],
        in_mixed_crate=False,
        visible_issues=visible_issues or [],
        evidence="Fresh produce.",
        stage=stage,
        stage_level="early",
        worst_stage=worst_stage,
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
    def __init__(self, responses: list[object]):
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


@pytest.mark.asyncio
async def test_1_same_image_twice_with_cache():
    """1. The same image twice with a cache: first makes calls, second makes 0 calls from_cache=True."""
    img = _make_dummy_image("green")
    out = _make_valid_output("apple", stage="fresh", worst_stage="fresh")
    client = FakeGenAIClient([FakeResponse(parsed=out)])
    store = InMemoryStore()

    # First call: makes Gemini call, stores reading
    res1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW,
        client=client,
        reading_cache=store,
    )
    assert res1.inspector.from_cache is False
    assert res1.inspector.calls == 1
    assert client.call_count == 1

    # Second call: cache hit, 0 calls, identical values
    res2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW + timedelta(minutes=5),
        client=client,
        reading_cache=store,
    )
    assert res2.inspector.from_cache is True
    assert res2.inspector.calls == 0
    assert client.call_count == 1  # No new client calls

    assert [i.stage for i in res1.items] == [i.stage for i in res2.items]
    assert [i.worst_stage for i in res1.items] == [i.worst_stage for i in res2.items]
    assert [i.issues for i in res1.items] == [i.issues for i in res2.items]
    assert [(i.quantity.unit, i.quantity.low, i.quantity.high) for i in res1.items] == [
        (i.quantity.unit, i.quantity.low, i.quantity.high) for i in res2.items
    ]
    assert [i.staff_check_reasons for i in res1.items] == [i.staff_check_reasons for i in res2.items]


@pytest.mark.asyncio
async def test_2_different_image_is_miss():
    """2. A different image -> a new reading (calls > 0)."""
    img1 = _make_dummy_image("green")
    img2 = _make_dummy_image("red")
    out = _make_valid_output("apple")
    client = FakeGenAIClient([FakeResponse(parsed=out), FakeResponse(parsed=out)])
    store = InMemoryStore()

    res1 = await inspect_photo(
        img1,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW,
        client=client,
        reading_cache=store,
    )
    assert res1.inspector.from_cache is False
    assert res1.inspector.calls == 1

    res2 = await inspect_photo(
        img2,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW + timedelta(minutes=1),
        client=client,
        reading_cache=store,
    )
    assert res2.inspector.from_cache is False
    assert res2.inspector.calls == 1
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_3_differing_parameters_is_miss(monkeypatch):
    """3. Same image with different bin_capacity_kg, zoom setting or prompt version -> miss."""
    img = _make_dummy_image("blue")
    out = _make_valid_output("apple")
    client = FakeGenAIClient([
        FakeResponse(parsed=out),
        FakeResponse(parsed=out),
        FakeResponse(parsed=out),
        FakeResponse(parsed=out),
    ])
    store = InMemoryStore()

    # Initial baseline
    r1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        bin_capacity_kg=None,
        zoom=True,
        client=client,
        reading_cache=store,
    )
    assert r1.inspector.from_cache is False

    # Different bin_capacity_kg
    r2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        bin_capacity_kg=15.0,
        zoom=True,
        client=client,
        reading_cache=store,
    )
    assert r2.inspector.from_cache is False

    # Different zoom setting
    r3 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        bin_capacity_kg=None,
        zoom=False,
        client=client,
        reading_cache=store,
    )
    assert r3.inspector.from_cache is False

    # Different prompt version
    monkeypatch.setattr("lastcall_api.inspector.inspector.PROMPT_VERSION", "99.0")
    r4 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        bin_capacity_kg=None,
        zoom=True,
        client=client,
        reading_cache=store,
    )
    assert r4.inspector.from_cache is False


@pytest.mark.asyncio
async def test_4_zoom_failure_does_not_cache():
    """4. A zoom failure on the first run -> nothing stored; second run calls Gemini again."""
    img = _make_dummy_image("yellow")
    # Qualifies for zoom via visible_issues=["mould"]
    out_with_mould = _make_valid_output("apple", stage="fresh", worst_stage="spoiled", visible_issues=["mould"])

    # First run: pass 1 succeeds, pass 2 (zoom crop) fails with APIError
    client = FakeGenAIClient([
        FakeResponse(parsed=out_with_mould),
        RuntimeError("Zoom crop call failed"),
        FakeResponse(parsed=out_with_mould),
        FakeResponse(parsed=out_with_mould),  # if zoom runs again
    ])
    store = InMemoryStore()

    res1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        zoom=True,
        client=client,
        reading_cache=store,
    )
    assert res1.inspector.zoom_failures == 1
    # Check that nothing was stored in cache
    assert len(store.inspector_readings) == 0

    # Second run: calls Gemini again because nothing was stored
    res2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW + timedelta(minutes=2),
        zoom=True,
        client=client,
        reading_cache=store,
    )
    assert res2.inspector.from_cache is False
    assert client.call_count >= 3


@pytest.mark.asyncio
async def test_5_corrupted_stored_entry_treated_as_miss():
    """5. A corrupted stored entry (invalid output) -> treated as a miss; inspection succeeds."""
    img = _make_dummy_image("purple")
    out = _make_valid_output("apple")
    client = FakeGenAIClient([FakeResponse(parsed=out)])
    store = InMemoryStore()

    # Pre-populate store with a corrupt entry
    key = reading_key(
        image_sha256="bad_sha",  # Will populate via actual key
        model="gemini-3.8-flash",
        prompt_version=PROMPT_VERSION,
        thinking_level="low",
        zoom=True,
        bin_capacity_kg=None,
    )
    # Put corrupt data into any key
    await store.create_reading(key, {"output": {"corrupted": True}})

    # Now inspect with a store where all get_reading returns corrupt data
    class CorruptStore(InMemoryStore):
        async def get_reading(self, key: str):
            return {"output": {"invalid_fields": 123}}

    cstore = CorruptStore()
    res = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        client=client,
        reading_cache=cstore,
    )
    assert res.photo_status == "ok"
    assert res.inspector.from_cache is False
    assert len(res.items) == 1


@pytest.mark.asyncio
async def test_6_cache_exceptions_fall_back_gracefully():
    """6. get_reading or create_reading raising -> inspection still succeeds."""
    img = _make_dummy_image("cyan")
    out = _make_valid_output("apple")
    client = FakeGenAIClient([FakeResponse(parsed=out), FakeResponse(parsed=out)])

    class RaisingGetStore(InMemoryStore):
        async def get_reading(self, key: str):
            raise RuntimeError("Firestore get_reading failure")

    class RaisingCreateStore(InMemoryStore):
        async def create_reading(self, key: str, data: dict):
            raise RuntimeError("Firestore create_reading failure")

    # get_reading raises
    r1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        client=client,
        reading_cache=RaisingGetStore(),
    )
    assert r1.photo_status == "ok"
    assert r1.inspector.from_cache is False

    # create_reading raises
    r2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="s1",
        now=NOW,
        client=client,
        reading_cache=RaisingCreateStore(),
    )
    assert r2.photo_status == "ok"
    assert r2.inspector.from_cache is False


@pytest.mark.asyncio
async def test_7_previous_inspection_applied_on_cache_hit():
    """7. previous is applied on a cache hit: second result has previous_inspection_id and change note."""
    img = _make_dummy_image("magenta")
    out = _make_valid_output("apple", stage="fresh")
    client = FakeGenAIClient([FakeResponse(parsed=out)])
    store = InMemoryStore()

    # First inspection
    res1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_A",
        now=NOW,
        client=client,
        reading_cache=store,
    )
    assert res1.previous_inspection_id is None

    # Second inspection on same shelf with previous=res1
    now2 = NOW + timedelta(hours=1)
    res2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_A",
        previous=res1,
        now=now2,
        client=client,
        reading_cache=store,
    )
    assert res2.inspector.from_cache is True
    assert res2.previous_inspection_id == res1.inspection_id
    assert len(res2.items) == 1
    # Change note should indicate no change since previous inspection
    assert res2.items[0].change_note is not None
    assert "no change" in res2.items[0].change_note.lower()


@pytest.mark.asyncio
async def test_8_without_reading_cache_default_is_none():
    """8. Without reading_cache (the default), two calls make two sets of Gemini calls."""
    # Check default parameter
    sig = inspect.signature(inspect_photo)
    assert sig.parameters["reading_cache"].default is None

    img = _make_dummy_image("teal")
    out = _make_valid_output("apple")
    client = FakeGenAIClient([FakeResponse(parsed=out), FakeResponse(parsed=out)])

    res1 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW,
        client=client,
    )
    assert res1.inspector.from_cache is False
    assert client.call_count == 1

    res2 = await inspect_photo(
        img,
        mart_id="demo_mart",
        shelf_id="shelf_1",
        now=NOW + timedelta(minutes=1),
        client=client,
    )
    assert res2.inspector.from_cache is False
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_9_demo_inspect_passes_store_as_reading_cache(setup_api_test):
    """9. /demo/inspect passes the store as reading_cache."""
    store = setup_api_test
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    captured_kwargs = {}

    async def fake_inspect_fn(image, **kwargs):
        captured_kwargs.update(kwargs)
        # Return valid minimal result
        return FreshnessResult(
            mart_id="demo_mart",
            shelf_id="shelf_test",
            inspection_id="insp_test",
            previous_inspection_id=None,
            photo_uri="memory://test.jpg",
            taken_at=NOW,
            photo_status="ok",
            photo_note="",
            items=[],
        )

    app.state.inspect_fn = fake_inspect_fn

    files = {"photo": ("photo.jpg", b"jpeg-bytes-data", "image/jpeg")}
    data = {"shelf_id": "shelf_test"}
    resp = client.post("/demo/inspect", headers=headers, files=files, data=data)
    assert resp.status_code == 200

    assert "reading_cache" in captured_kwargs
    assert captured_kwargs["reading_cache"] is store
