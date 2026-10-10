"""Contract tests for CallStore implementations (InMemoryStore & FirestoreStore) and scenario loader."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from lastcall_shared.models import (
    CallResult,
    DealRecord,
    FreshnessResult,
    OutboxMessage,
    StaffTask,
    TranscriptEntry,
)
from lastcall_shared.scenarios.loader import build_call, list_scenarios, load_scenario
from lastcall_shared.store import InMemoryStore
from lastcall_shared.firestore_store import FirestoreStore

PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 7, 14, 0, 0, tzinfo=PKT)


@pytest.fixture(params=["in_memory", "firestore"])
async def store(request):
    """Parametrized fixture running contract tests on InMemoryStore and FirestoreStore."""
    if request.param == "in_memory":
        yield InMemoryStore()
    elif request.param == "firestore":
        if os.getenv("RUN_FIRESTORE_TESTS") != "1":
            pytest.skip("RUN_FIRESTORE_TESTS!=1: Firestore tests skipped")
        test_prefix = f"test_{uuid.uuid4().hex[:8]}_"
        fs = FirestoreStore(collection_prefix=test_prefix)
        try:
            yield fs
        finally:
            await fs.clean_prefix()


def test_scenario_loader():
    scenarios = list_scenarios()
    assert len(scenarios) == 5
    assert "easy_yes" in scenarios
    assert "donation" in scenarios

    call, batch = build_call("easy_yes", now=NOW)
    assert call.call_id.startswith("call_easy_yes_")
    assert batch.batch_id.startswith("batch_easy_yes_")
    assert call.brief.buyer.buyer_id.startswith("test:easy_yes:")
    assert call.brief.floor_price_per_unit == 130
    assert call.negotiation.ladder[0] == 180
    assert call.negotiation.ladder[-1] == 130


@pytest.mark.asyncio
async def test_call_lifecycle_and_deal_tx(store):
    call, batch = build_call("easy_yes", now=NOW)

    # 1. Create call in store
    await store.create_call(call, batch)
    fetched = await store.get_call(call.call_id)
    assert fetched is not None
    assert fetched.status == "pending"

    # 2. Start session transaction
    # Bad nonce fails
    assert await store.start_session(call.call_id, "wrong_nonce") is False
    # Correct nonce succeeds
    assert await store.start_session(call.call_id, call.session_nonce) is True
    # Reused nonce on now in_progress call fails
    assert await store.start_session(call.call_id, call.session_nonce) is False
    assert (await store.get_call(call.call_id)).status == "in_progress"

    # 3. Lock batch
    lock_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert await store.lock_batch(batch.batch_id, call.call_id, lock_until) is True

    # Another call trying to lock active batch fails
    assert await store.lock_batch(batch.batch_id, "call_other", lock_until) is False

    # 4. Save deal transaction (all-or-nothing)
    deal = DealRecord(
        mart_id=call.mart_id,
        call_id=call.call_id,
        batch_id=batch.batch_id,
        buyer_id=call.brief.buyer.buyer_id,
        deal_type="sale",
        price_per_unit=160,
        unit="kg",
        quantity=30.0,
        pickup_time=NOW + timedelta(hours=2),
        pickup_deadline=call.brief.pickup_deadline,
        payment_terms="Cash",
        status="agreed",
        created_at=NOW,
    )
    ok, err = await store.save_deal_tx(call.call_id, deal, 30.0)
    assert ok is True
    assert err is None

    # Check batch decremented: 50 - 30 = 20 remaining, status partly_sold
    updated_batch = await store.get_batch(batch.batch_id)
    assert updated_batch.remaining_quantity == 20.0
    assert updated_batch.status == "partly_sold"

    # 5. Idempotent deal replay with identical terms succeeds
    ok2, err2 = await store.save_deal_tx(call.call_id, deal, 30.0)
    assert ok2 is True
    assert err2 is None
    # Remaining quantity unchanged after replay
    assert (await store.get_batch(batch.batch_id)).remaining_quantity == 20.0

    # Deal replay with conflicting terms fails
    conflicting_deal = deal.model_copy(update={"price_per_unit": 150})
    ok_bad, err_bad = await store.save_deal_tx(call.call_id, conflicting_deal, 30.0)
    assert ok_bad is False
    assert "different terms" in err_bad

    # 6. Complete remaining stock
    deal_2 = deal.model_copy(update={"call_id": "call_2", "quantity": 20.0})
    await store.release_batch(batch.batch_id, call.call_id)
    assert await store.lock_batch(batch.batch_id, "call_2", lock_until) is True
    ok3, _ = await store.save_deal_tx("call_2", deal_2, 20.0)
    assert ok3 is True
    assert (await store.get_batch(batch.batch_id)).remaining_quantity == 0.0
    assert (await store.get_batch(batch.batch_id)).status == "sold"


@pytest.mark.asyncio
async def test_lazy_expiry_lock(store):
    call, batch = build_call("hard_bargainer", now=NOW)
    await store.create_call(call, batch)

    # Lock batch in the past (expired)
    past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    assert await store.lock_batch(batch.batch_id, "old_call", past_time) is True

    # New call takes over expired lock
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert await store.lock_batch(batch.batch_id, "new_call", future_time) is True
    assert (await store.get_batch(batch.batch_id)).locked_by_call == "new_call"


@pytest.mark.asyncio
async def test_release_batch_isolation(store):
    call, batch = build_call("hard_bargainer", now=NOW)
    await store.create_call(call, batch)

    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert await store.lock_batch(batch.batch_id, "call_a", future_time) is True

    # Another call attempts to release it -> must NOT release call_a's lock
    await store.release_batch(batch.batch_id, "call_b")
    assert (await store.get_batch(batch.batch_id)).locked_by_call == "call_a"

    # Owning call releases -> lock is cleared
    await store.release_batch(batch.batch_id, "call_a")
    assert (await store.get_batch(batch.batch_id)).locked_by_call is None


@pytest.mark.asyncio
async def test_outbox_tasks_and_do_not_call(store):
    # Do-not-call
    assert await store.is_do_not_call("mart_1", "buyer_1") is False
    await store.add_do_not_call("mart_1", "buyer_1")
    assert await store.is_do_not_call("mart_1", "buyer_1") is True

    # Outbox message
    msg = OutboxMessage(
        mart_id="mart_1",
        kind="whatsapp_confirmation",
        call_id="call_1",
        to_buyer_id="buyer_1",
        payload={"deal_id": "d1"},
    )
    await store.add_outbox(msg)
    outbox = await store.get_outbox(call_id="call_1")
    assert len(outbox) == 1
    assert outbox[0].to_buyer_id == "buyer_1"

    # Staff task
    task = StaffTask(
        mart_id="mart_1",
        kind="manager_callback",
        call_id="call_1",
        note="Call back buyer",
        created_at=NOW,
    )
    await store.add_staff_task(task)
    tasks = await store.get_staff_tasks(call_id="call_1")
    assert len(tasks) == 1
    assert tasks[0].note == "Call back buyer"


@pytest.mark.asyncio
async def test_daily_sessions_cap(store):
    date_str = "2026-10-07"
    assert await store.incr_daily_sessions(date_str, 2) is True
    assert await store.incr_daily_sessions(date_str, 2) is True
    assert await store.incr_daily_sessions(date_str, 2) is False  # Reached cap of 2


@pytest.mark.asyncio
async def test_inspection_lifecycle(store):
    # Unknown shelf and inspection id return None
    assert await store.get_inspection("nonexistent_id") is None
    assert await store.get_latest_inspection("mart_1", "unknown_shelf") is None

    # 1. Save and get inspection
    insp_1 = FreshnessResult(
        mart_id="mart_1",
        shelf_id="shelf_1",
        inspection_id="insp_1",
        photo_uri="gs://test/photo1.jpg",
        taken_at=NOW,
        photo_status="no_produce",
        photo_note="Empty shelf",
        items=[],
    )
    await store.save_inspection(insp_1)
    fetched_1 = await store.get_inspection("insp_1")
    assert fetched_1 is not None
    assert fetched_1.inspection_id == "insp_1"
    assert fetched_1.photo_note == "Empty shelf"

    # Latest inspection on shelf_1 returns insp_1
    latest = await store.get_latest_inspection("mart_1", "shelf_1")
    assert latest is not None
    assert latest.inspection_id == "insp_1"

    # 2. Save a newer inspection to the same shelf
    insp_2 = FreshnessResult(
        mart_id="mart_1",
        shelf_id="shelf_1",
        inspection_id="insp_2",
        previous_inspection_id="insp_1",
        photo_uri="gs://test/photo2.jpg",
        taken_at=NOW + timedelta(hours=1),
        photo_status="no_produce",
        photo_note="Still empty",
        items=[],
    )
    await store.save_inspection(insp_2)

    # get_latest_inspection now returns the newer one
    latest_2 = await store.get_latest_inspection("mart_1", "shelf_1")
    assert latest_2 is not None
    assert latest_2.inspection_id == "insp_2"
    assert latest_2.previous_inspection_id == "insp_1"

    # Other shelf still returns None
    assert await store.get_latest_inspection("mart_1", "shelf_2") is None


@pytest.mark.asyncio
async def test_produce_profile_lifecycle(store):
    from lastcall_shared.models import ProduceProfile, StageProfile

    sp = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=False, charity=True)
    p1 = ProduceProfile(
        key="banana__v1",
        name="banana",
        note="Initial v1 note",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version="1",
        created_at=NOW,
    )

    # 1. create_profile creates-if-absent
    created = await store.create_profile(p1)
    assert created is True

    # 2. create doesn't overwrite
    p1_dup = p1.model_copy(update={"note": "Different note"})
    created_again = await store.create_profile(p1_dup)
    assert created_again is False

    # Check profile was not overwritten
    profiles = await store.get_profiles(["banana__v1"])
    assert "banana__v1" in profiles
    assert profiles["banana__v1"].note == "Initial v1 note"

    # 3. get_profiles with missing keys returns only found keys
    multi = await store.get_profiles(["banana__v1", "missing_key_xyz"])
    assert set(multi.keys()) == {"banana__v1"}

    # 4. set_profile overwrites
    p1_updated = p1.model_copy(update={"note": "Updated manager note", "source": "manager"})
    await store.set_profile(p1_updated)
    profiles_after_set = await store.get_profiles(["banana__v1"])
    assert profiles_after_set["banana__v1"].note == "Updated manager note"
    assert profiles_after_set["banana__v1"].source == "manager"

    # 5. delete_profile
    await store.delete_profile("banana__v1")
    profiles_after_delete = await store.get_profiles(["banana__v1"])
    assert "banana__v1" not in profiles_after_delete


@pytest.mark.asyncio
async def test_firestore_store_get_profiles_async_generator():
    """C1: FirestoreStore.get_profiles must iterate self.client.get_all(...) with async for, not await."""
    from unittest.mock import MagicMock
    from lastcall_shared.models import ProduceProfile, StageProfile

    sp = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=False, charity=True)
    p1 = ProduceProfile(
        key="banana__v1",
        name="banana",
        note="Banana note",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version="1",
        created_at=NOW,
    )

    fs = FirestoreStore(collection_prefix="mock_")

    snap_found = MagicMock()
    snap_found.id = "banana__v1"
    snap_found.exists = True
    snap_found.to_dict.return_value = p1.model_dump(mode="json")

    snap_missing = MagicMock()
    snap_missing.id = "missing__v1"
    snap_missing.exists = False

    async def fake_get_all(doc_refs):
        for snap in [snap_found, snap_missing]:
            yield snap

    fs.client.get_all = fake_get_all

    res = await fs.get_profiles(["banana__v1", "missing__v1"])
    assert "banana__v1" in res
    assert res["banana__v1"].name == "banana"
    assert "missing__v1" not in res


@pytest.mark.asyncio
async def test_decisions_lifecycle(store):
    from lastcall_shared.models import LadderDecision, LadderMeta, LadderResult

    # Unknown inspection_id returns None
    assert await store.get_decisions("insp_unknown_999") is None

    dec = LadderDecision(
        item_key="item_01",
        name="banana",
        step="keep",
        allowed_steps=["keep", "discount"],
        next_steps=["discount"],
        unit="dozen",
        sellable_hours=48.0,
        shelf_price=180,
        reason="Banana is fresh",
    )
    res = LadderResult(
        mart_id="demo_mart",
        inspection_id="insp_dec_001",
        decided_at=NOW,
        hours_until_closing=12.0,
        decisions=[dec],
        meta=LadderMeta(latency_ms=100, profiles_used=1),
    )

    # 1. Save decisions
    await store.save_decisions(res)
    fetched = await store.get_decisions("insp_dec_001")
    assert fetched is not None
    assert fetched.inspection_id == "insp_dec_001"
    assert len(fetched.decisions) == 1
    assert fetched.decisions[0].name == "banana"
    assert fetched.decisions[0].step == "keep"

    # 2. Overwrite decisions (e.g. on re-decide)
    dec_updated = dec.model_copy(update={"step": "discount", "discount_pct": 20, "discounted_price": 145})
    res_updated = res.model_copy(update={"decisions": [dec_updated], "hours_until_closing": 2.0})
    await store.save_decisions(res_updated)

    fetched_2 = await store.get_decisions("insp_dec_001")
    assert fetched_2 is not None
    assert fetched_2.hours_until_closing == 2.0
    assert fetched_2.decisions[0].step == "discount"
    assert fetched_2.decisions[0].discount_pct == 20


@pytest.mark.asyncio
async def test_readings_lifecycle(store):
    # 1. Unknown key -> None
    assert await store.get_reading("r_unknown_999") is None

    # 2. Create then get
    data = {"output": {"items": [{"name": "banana"}]}, "zoomed_groups": 1, "test_num": 42}
    created = await store.create_reading("r_test_001", data)
    assert created is True

    fetched = await store.get_reading("r_test_001")
    assert fetched is not None
    assert fetched["zoomed_groups"] == 1
    assert fetched["test_num"] == 42
    assert fetched["output"]["items"][0]["name"] == "banana"

    # 3. Second create with same key fails and does not overwrite
    second_data = {"output": {"items": [{"name": "apple"}]}, "zoomed_groups": 2, "test_num": 99}
    second_created = await store.create_reading("r_test_001", second_data)
    assert second_created is False

    fetched_again = await store.get_reading("r_test_001")
    assert fetched_again is not None
    assert fetched_again["zoomed_groups"] == 1
    assert fetched_again["test_num"] == 42


