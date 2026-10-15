"""Tests for API demo endpoints (/demo, /demo/calls, /demo/batches) per Step 6."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lastcall_api.deps import _IP_REQUEST_HISTORY
from lastcall_api.main import app
from lastcall_shared.models import (
    BoundingBox,
    CallResult,
    FreshnessResult,
    ItemAssessment,
    LadderDecision,
    LadderMeta,
    LadderResult,
    ObservedQuantity,
    QuantityEstimate,
    ScoutCandidate,
    ScoutMeta,
    ScoutResult,
)
from lastcall_shared.session_tokens import verify
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345-at-least-32-chars-long"
CODE = "test-judge-access-code"
PKT = ZoneInfo("Asia/Karachi")


@pytest.fixture(autouse=True)
def setup_api_test(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    monkeypatch.setenv("DEMO_DAILY_SESSION_CAP", "5")
    monkeypatch.setenv("VOICE_WS_URL", "wss://voice.example.com/ws/call")
    _IP_REQUEST_HISTORY.clear()
    store = InMemoryStore()
    app.state.store = store
    return store


def _make_item(item_key: str, produce: str, qty: QuantityEstimate | None) -> ItemAssessment:
    return ItemAssessment(
        item_key=item_key,
        name=produce,
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        grid="center",
        stage="overripe",
        stage_level="mid",
        worst_stage="overripe",
        score=40.0,
        confidence=0.9,
        confidence_level="high",
        observed=ObservedQuantity(method="count", min=10, max=20),
        quantity=qty,
    )


async def seed_demo_data(
    store: InMemoryStore,
    on_hold: bool = False,
    step: str = "bulk_sale",
    needs_price: bool = False,
    no_quantity: bool = False,
):
    now = datetime.now(PKT)
    qty = (
        QuantityEstimate(unit="dozen", low=0.0, high=0.0)
        if no_quantity
        else QuantityEstimate(unit="dozen", low=20.0, high=30.0)
    )
    inspection = FreshnessResult(
        inspection_id="insp_1",
        mart_id="demo_mart",
        shelf_id="shelf_1",
        captured_at=now,
        taken_at=now,
        photo_uri="gs://bucket/test.jpg",
        items=[_make_item("item_banana_1", "banana", qty)],
    )
    await store.save_inspection(inspection)

    decisions = LadderResult(
        inspection_id="insp_1",
        mart_id="demo_mart",
        shelf_id="shelf_1",
        decided_at=now,
        hours_until_closing=6.0,
        meta=LadderMeta(latency_ms=45, profiles_used=1),
        decisions=[
            LadderDecision(
                item_key="item_banana_1",
                name="banana",
                unit="dozen",
                shelf_price=180,
                step=step,
                allowed_steps=list(set([step, "bulk_sale", "donate", "animal_feed"])),
                opening_price=110 if not needs_price else 0,
                floor_price=65 if not needs_price else 0,
                buyer_types=["juice_shop", "bakery"],
                next_steps=["donate"],
                reason="Overripe bananas",
                buyer_condition="Ripe bananas for shakes",
                on_hold=on_hold,
                needs_price=needs_price,
            )
        ],
    )
    await store.save_decisions(decisions)

    scout_result = ScoutResult(
        key="insp_1__item_banana_1__johar_town",
        mart_id="demo_mart",
        branch_id="johar_town",
        branch_name="Demo Mart Johar Town",
        inspection_id="insp_1",
        item_key="item_banana_1",
        step="bulk_sale",
        buyer_types=["juice_shop", "bakery"],
        buyers=[
            ScoutCandidate(
                rank=1,
                buyer_id="places:ChIJ_buyer_1",
                place_id="ChIJ_buyer_1",
                name="Lahore Shake Shack",
                buyer_type="juice_shop",
                phone="+923001234567",
                distance_km=1.2,
                open_now=True,
                fit="likely",
                reason="Juice shop 1.2 km",
            ),
            ScoutCandidate(
                rank=2,
                buyer_id="places:ChIJ_buyer_2",
                place_id="ChIJ_buyer_2",
                name="Al-Jannat Bakery",
                buyer_type="bakery",
                phone="+923007654321",
                distance_km=2.0,
                open_now=True,
                fit="likely",
                reason="Bakery 2.0 km",
            ),
        ],
        searched_at=now,
        expire_at=now + timedelta(hours=1),
        meta=ScoutMeta(latency_ms=100),
    )
    await store.save_scout_result(scout_result)


def test_get_demo_page():
    client = TestClient(app)
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "Last Call" in resp.text


def test_auth_endpoints():
    client = TestClient(app)
    # Missing / wrong auth on /demo/calls
    r1 = client.post("/demo/calls", json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r1.status_code == 401
    r2 = client.post(
        "/demo/calls",
        headers={"X-Demo-Access-Code": "bad"},
        json={"inspection_id": "insp_1", "item_key": "item_banana_1"},
    )
    assert r2.status_code == 401

    # Missing / wrong auth on /demo/batches/{id}
    r3 = client.get("/demo/batches/insp_1__item_banana_1__johar_town")
    assert r3.status_code == 401

    # Missing / wrong auth on /demo/batches/{id}/next-step
    r4 = client.post("/demo/batches/insp_1__item_banana_1__johar_town/next-step")
    assert r4.status_code == 401


@pytest.mark.asyncio
async def test_demo_calls_errors_parametrized(setup_api_test):
    store = setup_api_test
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    # 400 Bad regex
    r_bad_id = client.post("/demo/calls", headers=headers, json={"inspection_id": "INVALID!!", "item_key": "item_1"})
    assert r_bad_id.status_code == 400

    r_bad_qty = client.post(
        "/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_1", "quantity": -5}
    )
    assert r_bad_qty.status_code == 400

    r_bad_buyer_id = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_1", "buyer_id": "invalid_buyer"},
    )
    assert r_bad_buyer_id.status_code == 400

    # 404 Missing inspection / decision
    r_404 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_missing", "item_key": "item_1"})
    assert r_404.status_code == 404

    # 409 On hold waiting for staff check
    await seed_demo_data(store, on_hold=True)
    r_hold = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_banana_1", "staff_checked": False},
    )
    assert r_hold.status_code == 409
    assert "Waiting for staff check" in r_hold.json()["detail"]

    # 409 Needs price
    await seed_demo_data(store, needs_price=True)
    r_np = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r_np.status_code == 409
    assert "Enter the shelf price first" in r_np.json()["detail"]

    # 409 Stays in store
    await seed_demo_data(store, step="keep")
    r_keep = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r_keep.status_code == 409
    assert "This item stays in store" in r_keep.json()["detail"]

    # 409 Needs quantity
    await seed_demo_data(store, no_quantity=True)
    r_qty = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r_qty.status_code == 409
    assert "Enter the quantity" in r_qty.json()["detail"]

    # 400 Buyer not on list
    await seed_demo_data(store)
    r_not_on_list = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_banana_1", "buyer_id": "places:ChIJ_unknown_buyer"},
    )
    assert r_not_on_list.status_code == 400
    assert "Buyer not on search list" in r_not_on_list.json()["detail"]


@pytest.mark.asyncio
async def test_daily_cap_and_refusal_does_not_increment_cap(monkeypatch, setup_api_test):
    monkeypatch.setenv("DEMO_DAILY_SESSION_CAP", "1")
    store = setup_api_test
    await seed_demo_data(store, on_hold=True)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    # 1. A refusal (409) does NOT count against daily cap
    r_refused = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_banana_1", "staff_checked": False},
    )
    assert r_refused.status_code == 409

    # 2. Re-seed with on_hold=False, so first call succeeds
    await seed_demo_data(store, on_hold=False)
    r_success = client.post(
        "/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"}
    )
    assert r_success.status_code == 200

    # 3. Next call hits daily cap 429
    r_cap = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r_cap.status_code == 429
    assert "Daily demo session cap reached" in r_cap.json()["detail"]


@pytest.mark.asyncio
async def test_demo_call_success_contract(setup_api_test):
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    resp = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert resp.status_code == 200
    data = resp.json()

    # 1. No full phone in response
    assert "+923001234567" not in resp.text
    assert "3001234567" not in resp.text

    # 2. Structure & Deal fields
    assert data["batch_id"] == "insp_1__item_banana_1__johar_town"
    assert data["deal"]["item"] == "banana"
    assert data["deal"]["opening"] == 110
    assert data["deal"]["floor"] == 65
    assert data["deal"]["quantity"] == 20.0
    assert data["deal"]["unit"] == "dozen"
    assert "Demo Mart" in data["deal"]["mart_name"]
    assert "pickup_window" in data["deal"]

    # 3. Token verification
    token = data["token"]
    valid, payload, err = verify(token, key=KEY)
    assert valid is True
    assert payload["call_id"] == data["call_id"]

    # 4. Check stored CallRecord
    call_rec = await store.get_call(data["call_id"])
    assert call_rec is not None
    assert "+923001234567" not in call_rec.brief.buyer.phone
    assert call_rec.city_style == "lahore"
    assert call_rec.brief.quantity == 20.0
    assert call_rec.expire_at == call_rec.created_at + timedelta(hours=24)


@pytest.mark.asyncio
async def test_existing_batch_ignores_new_quantity(setup_api_test):
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    # First call creates batch with quantity 20.0
    r1 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r1.status_code == 200
    data1 = r1.json()

    # Finish call 1 as declined
    await store.finish_call(
        data1["call_id"],
        CallResult(
            mart_id="demo_mart",
            batch_id="insp_1__item_banana_1__johar_town",
            call_id=data1["call_id"],
            status="completed",
            outcome="declined",
            flags=[],
        ),
    )

    # Second call with new quantity=50.0 should be ignored; batch retains 20.0
    r2 = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_banana_1", "quantity": 50.0},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["deal"]["quantity"] == 20.0

    batch = await store.get_batch("insp_1__item_banana_1__johar_town")
    assert batch.total_quantity == 20.0


@pytest.mark.asyncio
async def test_second_call_offers_rank_2(setup_api_test):
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    # Call 1 -> offers rank 1
    r1 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    data1 = r1.json()
    assert data1["buyer"]["rank"] == 1

    # Finish call 1
    await store.finish_call(
        data1["call_id"],
        CallResult(
            mart_id="demo_mart",
            batch_id="insp_1__item_banana_1__johar_town",
            call_id=data1["call_id"],
            status="completed",
            outcome="declined",
            flags=[],
        ),
    )

    # Attempting to call buyer 1 again in the same step yields 409
    r_dup = client.post(
        "/demo/calls",
        headers=headers,
        json={"inspection_id": "insp_1", "item_key": "item_banana_1", "buyer_id": "places:ChIJ_buyer_1"},
    )
    assert r_dup.status_code == 409
    assert "Buyer already called" in r_dup.json()["detail"]

    # Second call without buyer_id -> offers rank 2
    r2 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["buyer"]["rank"] == 2
    assert data2["buyer"]["buyer_id"] == "places:ChIJ_buyer_2"


@pytest.mark.asyncio
async def test_get_batch_no_phones(setup_api_test):
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    r1 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    batch_id = r1.json()["batch_id"]

    r_batch = client.get(f"/demo/batches/{batch_id}", headers=headers)
    assert r_batch.status_code == 200
    batch_data = r_batch.json()

    # No phone numbers in response text
    assert "+92" not in r_batch.text
    assert "1234567" not in r_batch.text

    assert batch_data["batch_id"] == batch_id
    assert batch_data["remaining_quantity"] == 20.0
    assert batch_data["step_index"] == 0
    assert batch_data["current_step"] == "bulk_sale"
    assert len(batch_data["attempts"]) == 1
    assert batch_data["attempts"][0]["name"] == "Lahore Shake Shack"


@pytest.mark.asyncio
async def test_batch_next_action_names_the_buyer_by_id(setup_api_test):
    """The next buyer is identified by ID as well as rank, so the page can't match the wrong row."""
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    r1 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    batch_id, call_id = r1.json()["batch_id"], r1.json()["call_id"]
    await store.finish_call(
        call_id,
        CallResult(
            mart_id="demo_mart", batch_id=batch_id, call_id=call_id, status="completed", outcome="declined", flags=[]
        ),
    )

    action = client.get(f"/demo/batches/{batch_id}", headers=headers).json()["next_action"]
    assert action["kind"] == "call"
    assert action["buyer_rank"] == 2
    assert action["buyer_id"] == "places:ChIJ_buyer_2"


@pytest.mark.asyncio
async def test_next_step_then_demo_scout_charity(setup_api_test):
    store = setup_api_test
    await seed_demo_data(store)
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE}

    # 1. Make call 1 and complete it
    r1 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    batch_id = r1.json()["batch_id"]
    await store.finish_call(
        r1.json()["call_id"],
        CallResult(
            mart_id="demo_mart",
            batch_id=batch_id,
            call_id=r1.json()["call_id"],
            status="completed",
            outcome="declined",
            flags=[],
        ),
    )

    # 2. Make call 2 and complete it
    r2 = client.post("/demo/calls", headers=headers, json={"inspection_id": "insp_1", "item_key": "item_banana_1"})
    await store.finish_call(
        r2.json()["call_id"],
        CallResult(
            mart_id="demo_mart",
            batch_id=batch_id,
            call_id=r2.json()["call_id"],
            status="completed",
            outcome="declined",
            flags=[],
        ),
    )

    # 3. Next action should be next_step
    # Advance batch step
    r_step = client.post(f"/demo/batches/{batch_id}/next-step", headers=headers)
    assert r_step.status_code == 200
    step_data = r_step.json()
    assert step_data["step_index"] == 1
    assert step_data["current_step"] == "donate"

    # 4. Scout endpoint uses current step ("donate", charities)
    captured_target = None

    async def mock_scout(target, **kwargs):
        nonlocal captured_target
        captured_target = target
        return ScoutResult(
            key=batch_id,
            mart_id="demo_mart",
            branch_id="johar_town",
            branch_name="Demo Mart Johar Town",
            inspection_id=target.inspection_id,
            item_key=target.item_key,
            step=target.step,
            buyer_types=list(target.buyer_types),
            buyers=[],
            searched_at=datetime.now(PKT),
            expire_at=datetime.now(PKT) + timedelta(hours=1),
            meta=ScoutMeta(latency_ms=10),
        )

    app.state.scout_fn = mock_scout
    try:
        r_scout = client.post(
            "/demo/scout",
            headers=headers,
            json={"inspection_id": "insp_1", "item_key": "item_banana_1", "branch_id": "johar_town", "refresh": True},
        )
        assert r_scout.status_code == 200
        assert captured_target is not None
        assert captured_target.step == "donate"
        assert captured_target.buyer_types == ("charity",)
    finally:
        delattr(app.state, "scout_fn")


def test_root_opens_the_demo_page():
    client = TestClient(app)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/demo"


def test_favicon_is_the_page_icon():
    """The tab icon is declared by the page and also answers /favicon.ico (no 404 in the console)."""
    client = TestClient(app)
    page = client.get("/demo").text
    assert '<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">' in page
    for path in ("/static/favicon.svg", "/favicon.ico"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("image/svg+xml"), path
        assert r.content.startswith(b"<svg"), path


def test_static_and_demo_cache_control():
    client = TestClient(app)
    r_demo = client.get("/demo")
    assert r_demo.status_code == 200
    assert r_demo.headers.get("Cache-Control") == "no-cache"

    # Every stylesheet the page links (one per part of the page) is served and revalidated
    page = r_demo.text
    sheets = re.findall(r'href="(/static/css/[a-z]+\.css)"', page)
    assert len(sheets) == 9
    for href in sheets:
        r_css = client.get(href)
        assert r_css.status_code == 200, href
        assert r_css.headers.get("Cache-Control") == "no-cache", href

    r_js = client.get("/static/js/main.js")
    assert r_js.status_code == 200
    assert r_js.headers.get("Cache-Control") == "no-cache"
