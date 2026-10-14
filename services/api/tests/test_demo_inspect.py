"""Tests for POST /demo/inspect and GET /demo/samples endpoints (Milestone 1B Step 9)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lastcall_api.deps import _IP_REQUEST_HISTORY
from lastcall_api.inspector.images import ImageError
from lastcall_api.inspector.inspector import InspectorError
from lastcall_api.main import app
from lastcall_api.routes.pages import STATIC_DIR
from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    BoundingBox,
    FreshnessResult,
    ItemAssessment,
    ObservedQuantity,
    QuantityEstimate,
)
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345-at-least-32-chars-long"
CODE = "test-judge-access-code"
PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=PKT)


def _make_dummy_result(
    mart_id: str = "demo_mart",
    shelf_id: str = "shelf_1",
    inspection_id: str = "insp_1",
    prev_id: str | None = None,
) -> FreshnessResult:
    return FreshnessResult(
        mart_id=mart_id,
        shelf_id=shelf_id,
        inspection_id=inspection_id,
        previous_inspection_id=prev_id,
        photo_uri="memory://test.jpg",
        taken_at=NOW,
        photo_status="ok",
        photo_note="",
        items=[
            ItemAssessment(
                item_key="shelf_1_c0_0",
                name="banana",
                position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.5, xmax=0.5),
                grid="top-left",
                stage="fresh",
                stage_level="mid",
                worst_stage="fresh",
                score=90.0,
                observed=ObservedQuantity(method="count", min=10, max=12),
                quantity=QuantityEstimate(unit="dozen", low=0.8, high=1.0),
                confidence=0.9,
                confidence_level="high",
            )
        ],
    )


@pytest.fixture(autouse=True)
def setup_api_test(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    monkeypatch.setenv("DEMO_DAILY_INSPECT_CAP", "100")
    monkeypatch.setenv("IP_RATE_LIMIT_PER_HOUR", "20")
    _IP_REQUEST_HISTORY.clear()
    store = InMemoryStore()
    app.state.store = store
    return store


def test_get_demo_samples_public():
    client = TestClient(app)
    resp = client.get("/demo/samples")
    assert resp.status_code == 200
    samples = resp.json()
    assert isinstance(samples, list)
    assert len(samples) >= 2
    for s in samples:
        assert s["label"]
        # every listed photo and preview is a real file the page can load
        for key in ("url", "thumb"):
            assert s[key].startswith("/static/samples/")
            assert (STATIC_DIR / s[key].removeprefix("/static/")).is_file()
        # an AI-generated photo says so in its label
        assert s["ai_generated"] == s["label"].endswith("AI")
    # one photo is selected when the page opens (D65: Day 4, the start of the 10-day sequence)
    assert [s["id"] for s in samples if s.get("default")] == ["day4_banana_tomato"]


def test_post_demo_inspect_auth():
    client = TestClient(app)
    file_content = b"fake-jpeg-data"
    files = {"photo": ("test.jpg", file_content, "image/jpeg")}
    data = {"shelf_id": "shelf_test"}

    # No header
    resp1 = client.post("/demo/inspect", files=files, data=data)
    assert resp1.status_code == 401

    # Wrong access code
    files = {"photo": ("test.jpg", file_content, "image/jpeg")}
    resp2 = client.post("/demo/inspect", headers={"X-Demo-Access-Code": "wrong"}, files=files, data=data)
    assert resp2.status_code == 401


def test_post_demo_inspect_shelf_id_and_bin_validation():
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}
    file_content = b"fake-jpeg-data"

    # Bad shelf_ids: spaces, uppercase, symbols, empty, too long
    bad_shelf_ids = ["shelf 1", "SHELF_1", "shelf#1", "", "a" * 41]
    for bad_id in bad_shelf_ids:
        files = {"photo": ("test.jpg", file_content, "image/jpeg")}
        resp = client.post(
            "/demo/inspect",
            headers=headers,
            files=files,
            data={"shelf_id": bad_id},
        )
        assert resp.status_code == 400
        assert "shelf_id" in resp.json()["detail"]

    # Bad bin_capacity_kg: <= 0 or > 500
    for bad_kg in [-1.0, 0.0, 501.0]:
        files = {"photo": ("test.jpg", file_content, "image/jpeg")}
        resp = client.post(
            "/demo/inspect",
            headers=headers,
            files=files,
            data={"shelf_id": "shelf_valid", "bin_capacity_kg": str(bad_kg)},
        )
        assert resp.status_code == 400
        assert "bin_capacity_kg" in resp.json()["detail"]


def test_post_demo_inspect_content_type():
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}
    files = {"photo": ("doc.pdf", b"%PDF-1.4...", "application/pdf")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code == 415
    assert "Please upload a JPEG or PNG photo" in resp.json()["detail"]


def test_post_demo_inspect_file_size_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_MB", 1)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}
    too_large = b"x" * (1024 * 1024 + 10)
    files = {"photo": ("large.jpg", too_large, "image/jpeg")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code == 413
    assert "maximum upload size" in resp.json()["detail"]


def test_post_demo_inspect_ip_rate_limit(monkeypatch):
    monkeypatch.setenv("IP_RATE_LIMIT_PER_HOUR", "2")
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE, "X-Forwarded-For": "198.51.100.1"}

    async def fake_inspect(*args, **kwargs):
        return _make_dummy_result()

    app.state.inspect_fn = fake_inspect

    for _ in range(2):
        files = {"photo": ("test.jpg", b"jpeg-bytes", "image/jpeg")}
        resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
        assert resp.status_code == 200

    # 3rd request blocked
    files = {"photo": ("test.jpg", b"jpeg-bytes", "image/jpeg")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code == 429
    assert "Hourly IP limit reached" in resp.json()["detail"]


def test_post_demo_inspect_daily_cap(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_INSPECT_CAP", "1")
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    async def fake_inspect(*args, **kwargs):
        return _make_dummy_result()

    app.state.inspect_fn = fake_inspect

    # 1st succeeds
    files = {"photo": ("test.jpg", b"jpeg-bytes", "image/jpeg")}
    resp1 = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp1.status_code == 200

    # 2nd exceeds daily cap
    files = {"photo": ("test.jpg", b"jpeg-bytes", "image/jpeg")}
    resp2 = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp2.status_code == 429
    assert "Daily demo inspection cap reached" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_post_demo_inspect_success_and_repeat_shelf(setup_api_test):
    store = setup_api_test
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    received_calls = []

    async def fake_inspect(image, *, mart_id, shelf_id, previous, now, bin_capacity_kg=None, reading_cache=None):
        received_calls.append({"shelf_id": shelf_id, "previous": previous, "bin_capacity_kg": bin_capacity_kg})
        insp_id = f"insp_{len(received_calls)}"
        prev_id = previous.inspection_id if previous else None
        return _make_dummy_result(mart_id=mart_id, shelf_id=shelf_id, inspection_id=insp_id, prev_id=prev_id)

    app.state.inspect_fn = fake_inspect

    # 1. First inspection on shelf_repeat
    files1 = {"photo": ("photo1.jpg", b"img-data-1", "image/jpeg")}
    resp1 = client.post(
        "/demo/inspect",
        headers=headers,
        files=files1,
        data={"shelf_id": "shelf_repeat", "bin_capacity_kg": "25.0"},
    )
    assert resp1.status_code == 200
    res1_data = resp1.json()
    assert res1_data["inspection_id"] == "insp_1"
    assert res1_data["previous_inspection_id"] is None
    assert len(received_calls) == 1
    assert received_calls[0]["previous"] is None
    assert received_calls[0]["bin_capacity_kg"] == 25.0

    # Check store has saved it
    saved_1 = await store.get_inspection("insp_1")
    assert saved_1 is not None
    latest_1 = await store.get_latest_inspection("demo_mart", "shelf_repeat")
    assert latest_1 is not None
    assert latest_1.inspection_id == "insp_1"

    # 2. Second inspection on same shelf
    files2 = {"photo": ("photo2.jpg", b"img-data-2", "image/png")}
    resp2 = client.post(
        "/demo/inspect",
        headers=headers,
        files=files2,
        data={"shelf_id": "shelf_repeat"},
    )
    assert resp2.status_code == 200
    res2_data = resp2.json()
    assert res2_data["inspection_id"] == "insp_2"
    assert res2_data["previous_inspection_id"] == "insp_1"
    assert len(received_calls) == 2
    assert received_calls[1]["previous"] is not None
    assert received_calls[1]["previous"].inspection_id == "insp_1"


def test_post_demo_inspect_image_error():
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    async def fake_inspect(*args, **kwargs):
        raise ImageError("Corrupted image stream")

    app.state.inspect_fn = fake_inspect

    files = {"photo": ("corrupt.jpg", b"corrupt-data", "image/jpeg")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code == 400
    assert "Not a readable image" in resp.json()["detail"]


def test_post_demo_inspect_validation_error_not_turned_into_400():
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Demo-Access-Code": CODE}

    async def fake_inspect(*args, **kwargs):
        # Trigger real pydantic ValidationError
        FreshnessResult.model_validate({"invalid": "data"})

    app.state.inspect_fn = fake_inspect

    files = {"photo": ("valid.jpg", b"good-data", "image/jpeg")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code != 400
    assert resp.status_code == 500


def test_post_demo_inspect_inspector_error():
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    async def fake_inspect(*args, **kwargs):
        raise InspectorError("Quota exhausted after retries")

    app.state.inspect_fn = fake_inspect

    files = {"photo": ("fail.jpg", b"good-data", "image/jpeg")}
    resp = client.post("/demo/inspect", headers=headers, files=files, data={"shelf_id": "shelf_1"})
    assert resp.status_code == 502
    assert "Inspection failed, please try again" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_post_demo_inspect_concurrency_semaphore():
    import asyncio

    from httpx import ASGITransport, AsyncClient

    current_concurrent = 0
    max_concurrent_seen = 0
    gate = asyncio.Event()

    async def blocking_inspect(*args, **kwargs):
        nonlocal current_concurrent, max_concurrent_seen
        current_concurrent += 1
        max_concurrent_seen = max(max_concurrent_seen, current_concurrent)
        await gate.wait()
        current_concurrent -= 1
        return _make_dummy_result()

    app.state.inspect_fn = blocking_inspect

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"X-Demo-Access-Code": CODE}
        data = {"shelf_id": "shelf_conc"}

        # Launch 3 requests concurrently
        t1 = asyncio.create_task(
            client.post(
                "/demo/inspect", headers=headers, files={"photo": ("img1.jpg", b"data1", "image/jpeg")}, data=data
            )
        )
        t2 = asyncio.create_task(
            client.post(
                "/demo/inspect", headers=headers, files={"photo": ("img2.jpg", b"data2", "image/jpeg")}, data=data
            )
        )
        t3 = asyncio.create_task(
            client.post(
                "/demo/inspect", headers=headers, files={"photo": ("img3.jpg", b"data3", "image/jpeg")}, data=data
            )
        )

        # Allow tasks to start and queue
        await asyncio.sleep(0.05)
        # Exactly 2 should have entered inspect_fn due to semaphore(2)
        assert current_concurrent == 2
        assert max_concurrent_seen == 2

        # Release the gate to let the first 2 finish and the 3rd enter
        gate.set()
        resps = await asyncio.gather(t1, t2, t3)
        for r in resps:
            assert r.status_code == 200
        assert max_concurrent_seen == 2
