"""Tests for GET /demo/branches and POST /demo/scout endpoints (Step 9)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lastcall_api.main import app
from lastcall_api.scout.scout import ScoutCapReached, ScoutFailed, ScoutNotApplicable
from lastcall_shared.models import (
    LadderDecision,
    LadderMeta,
    LadderResult,
    ScoutCandidate,
    ScoutMeta,
    ScoutResult,
    ScreenedOut,
)
from lastcall_shared.store import InMemoryStore

ACCESS_CODE = "test-demo-passcode"
NOW = datetime(2026, 10, 11, 14, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def test_env(monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", ACCESS_CODE)
    monkeypatch.setenv("APP_SIGNING_KEY", "a" * 32)
    monkeypatch.setenv("DEMO_DAILY_PLACES_CAP", "200")
    monkeypatch.setenv("SCOUT_IP_LIMIT_PER_HOUR", "60")


@pytest.fixture
def mock_store():
    store = InMemoryStore(clock=lambda: NOW)
    app.state.store = store
    return store


@pytest.fixture
def client(test_env, mock_store):
    return TestClient(app)


def _make_ladder_result(inspection_id: str, step: str = "bulk_sale") -> LadderResult:
    dec = LadderDecision(
        item_key="banana_grp1",
        name="banana",
        step=step,  # type: ignore
        allowed_steps=[step],  # type: ignore
        unit="dozen",
        shelf_price=180,
        reason=f"Decided {step}",
        buyer_condition="Ripe",
        buyer_types=["juice_shop", "bakery"] if step == "bulk_sale" else [],
    )
    return LadderResult(
        mart_id="demo_mart",
        inspection_id=inspection_id,
        decided_at=NOW,
        hours_until_closing=6.0,
        decisions=[dec],
        meta=LadderMeta(latency_ms=45, profiles_used=1),
    )


def _make_dummy_scout_result(
    inspection_id: str,
    item_key: str,
    branch_id: str,
    branch_name: str,
) -> ScoutResult:
    c1 = ScoutCandidate(
        rank=1,
        buyer_id="places:ChIJ_test1",
        place_id="ChIJ_test1",
        name="Local Shake Point",
        buyer_type="juice_shop",
        distance_km=0.8,
        open_now=True,
        phone="+923001234567",
        maps_uri="https://maps.google.com/?cid=123",
        fit="likely",
        fit_why="Uses fresh bananas",
        reason="Juice shop · 0.8 km · open now",
    )
    so = ScreenedOut(
        name="Mega Chain Bakery",
        buyer_type="bakery",
        distance_km=1.2,
        why="Uses centralized corporate procurement",
    )
    meta = ScoutMeta(
        latency_ms=120,
        places_requests=2,
        places_results=40,
        input_tokens=500,
        output_tokens=150,
    )
    return ScoutResult(
        key=f"{inspection_id}__{item_key}__{branch_id}",
        mart_id="demo_mart",
        inspection_id=inspection_id,
        item_key=item_key,
        branch_id=branch_id,
        branch_name=branch_name,
        step="bulk_sale",
        buyer_types=["juice_shop", "bakery"],
        searched_at=NOW,
        expire_at=NOW + timedelta(hours=1),
        buyers=[c1],
        skipped={"no_phone": 5},
        screened_out=[so],
        meta=meta,
        attribution="Google Maps",
    )


def test_get_demo_branches_returns_branches_without_coordinates(client):
    """GET /demo/branches returns branches and default_branch_id, and NEVER coordinates."""
    resp = client.get("/demo/branches")
    assert resp.status_code == 200
    data = resp.json()
    assert "branches" in data
    assert "default_branch_id" in data
    assert len(data["branches"]) >= 3
    assert data["default_branch_id"] == "johar_town"

    for b in data["branches"]:
        assert "branch_id" in b
        assert "name" in b
        assert "location" in b
        assert "geo" not in b
        assert "lat" not in b
        assert "lng" not in b


@pytest.mark.parametrize(
    "auth,insp_id,item_key,branch_id,seed_step,expected_status",
    [
        ("wrong-code", "insp_01", "banana_grp1", "johar_town", "bulk_sale", 401),
        (ACCESS_CODE, "bad_id", "banana_grp1", "johar_town", "bulk_sale", 400),
        (ACCESS_CODE, "insp_01", "bad item!", "johar_town", "bulk_sale", 400),
        (ACCESS_CODE, "insp_01", "banana_grp1", "unknown_branch", "bulk_sale", 400),
        (ACCESS_CODE, "insp_missing", "banana_grp1", "johar_town", "bulk_sale", 404),
        (ACCESS_CODE, "insp_01", "missing_key", "johar_town", "bulk_sale", 404),
        (ACCESS_CODE, "insp_01", "banana_grp1", "johar_town", "keep", 409),
    ],
)
def test_demo_scout_errors_parametrized(
    client, mock_store, auth, insp_id, item_key, branch_id, seed_step, expected_status
):
    """Parametrized error handling: 401, 400s, 404s, and 409."""
    # Seed decisions if insp_01
    import asyncio

    if insp_id == "insp_01":
        ladder_res = _make_ladder_result(insp_id, step=seed_step)
        asyncio.run(mock_store.save_decisions(ladder_res))

    headers = {"X-Demo-Access-Code": auth} if auth else {}
    payload = {
        "inspection_id": insp_id,
        "item_key": item_key,
        "branch_id": branch_id,
    }
    resp = client.post("/demo/scout", json=payload, headers=headers)
    assert resp.status_code == expected_status


def test_demo_scout_429s_and_502(client, mock_store, monkeypatch):
    """Verifies daily cap 429, IP rate limit 429, and scout failure 502."""
    import asyncio

    ladder_res = _make_ladder_result("insp_429", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_429", "item_key": "banana_grp1", "branch_id": "johar_town"}

    # 1. Daily places cap reached -> 429
    async def mock_scout_cap_reached(*args, **kwargs):
        raise ScoutCapReached("Limit reached")

    app.state.scout_fn = mock_scout_cap_reached
    resp = client.post("/demo/scout", json=payload, headers=headers)
    assert resp.status_code == 429
    assert "Daily buyer-search limit reached" in resp.json()["detail"]

    # 2. Scout failed -> 502
    async def mock_scout_failed(*args, **kwargs):
        raise ScoutFailed("Searches failed")

    app.state.scout_fn = mock_scout_failed
    resp = client.post("/demo/scout", json=payload, headers=headers)
    assert resp.status_code == 502
    assert "Buyer search failed" in resp.json()["detail"]

    # 3. IP limit reached -> 429
    monkeypatch.setenv("SCOUT_IP_LIMIT_PER_HOUR", "1")
    # First successful request
    dummy_res = _make_dummy_scout_result("insp_429", "banana_grp1", "johar_town", "Johar Town")
    app.state.scout_fn = AsyncMock(return_value=dummy_res)
    client.post("/demo/scout", json=payload, headers=headers)
    # Second request hits IP limit
    resp_ip = client.post("/demo/scout", json=payload, headers=headers)
    assert resp_ip.status_code == 429
    assert "Hourly IP limit reached" in resp_ip.json()["detail"]


def test_demo_scout_200_public_view_no_raw_phones(client, mock_store):
    """POST /demo/scout 200 drops raw E.164 phone numbers and returns public_view format."""
    import asyncio

    ladder_res = _make_ladder_result("insp_200", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    dummy_res = _make_dummy_scout_result("insp_200", "banana_grp1", "johar_town", "Demo Mart Johar Town")
    app.state.scout_fn = AsyncMock(return_value=dummy_res)

    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_200", "item_key": "banana_grp1", "branch_id": "johar_town"}
    resp = client.post("/demo/scout", json=payload, headers=headers)

    assert resp.status_code == 200
    # Strict privacy check: raw phone string does NOT appear anywhere in the response text
    assert "+923001234567" not in resp.text
    data = resp.json()
    assert len(data["buyers"]) == 1
    b = data["buyers"][0]
    assert b["phone_masked"] == "+92 ••••••• 567"
    assert "phone" not in b
    assert len(data["screened_out"]) == 1
    so = data["screened_out"][0]
    assert so["name"] == "Mega Chain Bakery"
    assert so["why"] == "Uses centralized corporate procurement"
    assert "phone" not in so
    assert "place_id" not in so


def test_demo_scout_reuse_within_1h(client, mock_store):
    """Reuse within 1h returns cached result with reused=True without calling scout_fn."""
    import asyncio

    ladder_res = _make_ladder_result("insp_reuse", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    dummy_res = _make_dummy_scout_result("insp_reuse", "banana_grp1", "johar_town", "Demo Mart Johar Town")

    async def mock_scout_impl(*args, **kwargs):
        store = kwargs.get("store")
        if store:
            await store.save_scout_result(dummy_res)
        return dummy_res

    mock_scout = AsyncMock(side_effect=mock_scout_impl)
    app.state.scout_fn = mock_scout

    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_reuse", "item_key": "banana_grp1", "branch_id": "johar_town"}

    # 1. First call: executes scout_fn and saves result
    resp1 = client.post("/demo/scout", json=payload, headers=headers)
    assert resp1.status_code == 200
    assert mock_scout.call_count == 1
    assert resp1.json()["meta"]["reused"] is False

    # 2. Second call within 1h: reuses cached result without calling scout_fn
    resp2 = client.post("/demo/scout", json=payload, headers=headers)
    assert resp2.status_code == 200
    assert mock_scout.call_count == 1  # Unchanged!
    assert resp2.json()["meta"]["reused"] is True

    # 3. Call with refresh=True: runs scout_fn again
    payload_refresh = dict(payload, refresh=True)
    resp3 = client.post("/demo/scout", json=payload_refresh, headers=headers)
    assert resp3.status_code == 200
    assert mock_scout.call_count == 2


def test_demo_scout_cap_counter_keyed_by_pacific_date(client, mock_store):
    """Daily places counter is incremented with amount=len(types) and Pacific date key."""
    import asyncio

    ladder_res = _make_ladder_result("insp_cap_key", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    captured_reserves = []

    async def mock_scout_tracking(target, *, rules, branch, store, now, reserve_places, **kwargs):
        allowed = await reserve_places(len(target.buyer_types))
        captured_reserves.append((len(target.buyer_types), allowed))
        return _make_dummy_scout_result("insp_cap_key", "banana_grp1", branch.branch_id, branch.name)

    app.state.scout_fn = mock_scout_tracking

    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_cap_key", "item_key": "banana_grp1", "branch_id": "johar_town"}
    resp = client.post("/demo/scout", json=payload, headers=headers)

    assert resp.status_code == 200
    assert len(captured_reserves) == 1
    # 2 types: juice_shop, bakery -> amount 2
    assert captured_reserves[0][0] == 2

    # Check store daily_sessions key
    now_utc = datetime.now(timezone.utc)
    pacific_date = now_utc.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    expected_counter_key = f"places-{pacific_date}"
    assert mock_store.daily_sessions.get(expected_counter_key) == 2


def test_demo_scout_scout_not_applicable_inside_scout_fn_409(client, mock_store):
    """G2: ScoutNotApplicable inside scout_fn maps to 409 detail 'This item stays in store; no buyers needed'."""
    import asyncio

    ladder_res = _make_ladder_result("insp_g2", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    async def mock_not_applicable(*args, **kwargs):
        raise ScoutNotApplicable("No search specs for buyer type")

    app.state.scout_fn = mock_not_applicable
    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_g2", "item_key": "banana_grp1", "branch_id": "johar_town"}
    resp = client.post("/demo/scout", json=payload, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This item stays in store; no buyers needed"


def test_demo_scout_no_branches_configured_409(client, mock_store, monkeypatch):
    """G3: When no branches are configured on mart, returns 409 detail 'Buyer search isn't set up for this mart'."""
    import asyncio

    ladder_res = _make_ladder_result("insp_g3", step="bulk_sale")
    asyncio.run(mock_store.save_decisions(ladder_res))

    # Monkeypatch mart rules to have empty branches and no default
    from lastcall_shared.marts.loader import load_mart_rules

    real_rules = load_mart_rules("demo_mart")
    empty_branch_rules = real_rules.model_copy(update={"branches": [], "default_branch_id": None})
    monkeypatch.setattr("lastcall_api.deps.load_mart_rules", lambda mart_id: empty_branch_rules)

    headers = {"X-Demo-Access-Code": ACCESS_CODE}
    payload = {"inspection_id": "insp_g3", "item_key": "banana_grp1"}
    resp = client.post("/demo/scout", json=payload, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Buyer search isn't set up for this mart"
