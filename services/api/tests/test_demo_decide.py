"""Tests for POST /demo/decide endpoint (Step 8)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from lastcall_api.main import app
from lastcall_shared.models import (
    FreshnessResult,
    LadderDecision,
    LadderMeta,
    LadderResult,
)
from lastcall_shared.store import InMemoryStore

ACCESS_CODE = "test-demo-passcode"
NOW = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def test_env(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", ACCESS_CODE)
    monkeypatch.setenv("APP_SIGNING_KEY", "a" * 32)
    monkeypatch.setenv("DEMO_DAILY_DECIDE_CAP", "200")


@pytest.fixture
def mock_store():
    store = InMemoryStore()
    app.state.store = store
    return store


@pytest.fixture
def client(test_env, mock_store):
    return TestClient(app)


def _make_dummy_result(inspection_id: str, hours: float = 12.0) -> LadderResult:
    dec = LadderDecision(
        item_key="item_01",
        name="banana",
        step="keep",
        allowed_steps=["keep", "discount"],
        unit="dozen",
        shelf_price=180,
        reason="Fresh banana",
    )
    return LadderResult(
        mart_id="demo_mart",
        inspection_id=inspection_id,
        decided_at=NOW,
        hours_until_closing=hours,
        decisions=[dec],
        meta=LadderMeta(latency_ms=45, profiles_used=1),
    )


def _make_inspection(inspection_id: str, mart_id: str = "demo_mart") -> FreshnessResult:
    return FreshnessResult(
        mart_id=mart_id,
        inspection_id=inspection_id,
        shelf_id="shelf_01",
        photo_uri="upload:sha256:test",
        taken_at=NOW,
        photo_status="ok",
        items=[],
    )


def test_decide_401_unauthorized(client):
    # No header
    resp = client.post("/demo/decide", json={"inspection_id": "insp_01"})
    assert resp.status_code == 401

    # Wrong header
    resp2 = client.post(
        "/demo/decide",
        json={"inspection_id": "insp_01"},
        headers={"X-Demo-Access-Code": "wrong-code"},
    )
    assert resp2.status_code == 401


def test_decide_400_validations(client, mock_store):
    headers = {"X-Demo-Access-Code": ACCESS_CODE}

    # Missing / empty inspection_id
    r = client.post("/demo/decide", json={"inspection_id": ""}, headers=headers)
    assert r.status_code == 400
    assert "inspection_id" in r.json()["detail"]

    # Invalid hours < 0.5
    r = client.post("/demo/decide", json={"inspection_id": "insp_01", "hours_until_closing": 0.2}, headers=headers)
    assert r.status_code == 400
    assert "hours_until_closing" in r.json()["detail"]

    # Invalid hours > 16.0
    r = client.post("/demo/decide", json={"inspection_id": "insp_01", "hours_until_closing": 18.0}, headers=headers)
    assert r.status_code == 400

    # Over 12 price overrides
    too_many = {f"item_{i}": 100 for i in range(13)}
    r = client.post("/demo/decide", json={"inspection_id": "insp_01", "price_overrides": too_many}, headers=headers)
    assert r.status_code == 400
    assert "At most 12" in r.json()["detail"]

    # Invalid override key
    r = client.post(
        "/demo/decide",
        json={"inspection_id": "insp_01", "price_overrides": {"BAD KEY!": 100}},
        headers=headers,
    )
    assert r.status_code == 400
    assert "Invalid key" in r.json()["detail"]

    # Invalid price <= 0 or > 100000
    r = client.post(
        "/demo/decide",
        json={"inspection_id": "insp_01", "price_overrides": {"item_1": 0}},
        headers=headers,
    )
    assert r.status_code == 400
    r = client.post(
        "/demo/decide",
        json={"inspection_id": "insp_01", "price_overrides": {"item_1": 150_000}},
        headers=headers,
    )
    assert r.status_code == 400

    # Invalid inspection_id format (B3)
    r = client.post("/demo/decide", json={"inspection_id": "bad/path/123"}, headers=headers)
    assert r.status_code == 400
    assert "Invalid inspection_id format" in r.json()["detail"]

    r = client.post("/demo/decide", json={"inspection_id": "no_prefix_123"}, headers=headers)
    assert r.status_code == 400
    assert "Invalid inspection_id format" in r.json()["detail"]


@pytest.mark.asyncio
async def test_decide_404_missing_or_wrong_mart(client, mock_store):
    headers = {"X-Demo-Access-Code": ACCESS_CODE}

    # Inspection not found (valid format but not in store)
    r = client.post("/demo/decide", json={"inspection_id": "insp_nonexistent"}, headers=headers)
    assert r.status_code == 404

    # Inspection from wrong mart
    await mock_store.save_inspection(_make_inspection("insp_other", mart_id="other_mart"))
    r2 = client.post("/demo/decide", json={"inspection_id": "insp_other"}, headers=headers)
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_decide_429_daily_cap(client, mock_store, monkeypatch):
    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    await mock_store.save_inspection(_make_inspection("insp_cap"))

    # Cap set to 0
    monkeypatch.setenv("DEMO_DAILY_DECIDE_CAP", "0")
    r = client.post("/demo/decide", json={"inspection_id": "insp_cap"}, headers=headers)
    assert r.status_code == 429
    assert "Daily demo decide cap" in r.json()["detail"]


@pytest.mark.asyncio
async def test_decide_200_saves_overwrites_and_passes_params(client, mock_store):
    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    await mock_store.save_inspection(_make_inspection("insp_success"))

    recorded_calls = []

    async def fake_decide_fn(insp, *, rules, store, now, hours_override, price_overrides):
        recorded_calls.append(
            {
                "insp_id": insp.inspection_id,
                "hours": hours_override,
                "prices": price_overrides,
            }
        )
        return _make_dummy_result(insp.inspection_id, hours=hours_override or 12.0)

    app.state.decide_fn = fake_decide_fn

    # 1. Run decide with hours and price overrides
    payload = {
        "inspection_id": "insp_success",
        "hours_until_closing": 4.0,
        "price_overrides": {"item_banana": 200},
    }
    resp = client.post("/demo/decide", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["inspection_id"] == "insp_success"
    assert data["hours_until_closing"] == 4.0
    assert len(recorded_calls) == 1
    assert recorded_calls[0]["hours"] == 4.0
    assert recorded_calls[0]["prices"] == {"item_banana": 200}

    # Check saved to store
    stored_result = await mock_store.get_decisions("insp_success")
    assert stored_result is not None
    assert stored_result.hours_until_closing == 4.0

    # 2. Re-decide overwrites stored result
    payload_2 = {
        "inspection_id": "insp_success",
        "hours_until_closing": 1.0,
    }
    resp_2 = client.post("/demo/decide", json=payload_2, headers=headers)
    assert resp_2.status_code == 200
    assert resp_2.json()["hours_until_closing"] == 1.0

    stored_result_2 = await mock_store.get_decisions("insp_success")
    assert stored_result_2 is not None
    assert stored_result_2.hours_until_closing == 1.0
