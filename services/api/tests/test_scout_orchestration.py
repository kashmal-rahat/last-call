"""Unit tests for Scout orchestration (D46, D48, D50, D52, Step 8)."""

import json
import logging
from datetime import datetime, timezone

import pytest

from lastcall_api.gemini_call import CallUsage, GeminiCallError
from lastcall_api.scout.fit import FitOut, FitsOut
from lastcall_api.scout.places import PlaceRaw, PlacesError
from lastcall_api.scout.scout import (
    ScoutCapReached,
    ScoutFailed,
    ScoutNotApplicable,
    ScoutTarget,
    run_scout,
)
from lastcall_shared.buyer_keys import phone_key
from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    Branch,
    GeoPoint,
    LadderDecision,
    MartRules,
)
from lastcall_shared.store import InMemoryStore


def make_branch(branch_id: str = "johar_town", name: str = "Johar Town") -> Branch:
    return Branch(
        branch_id=branch_id,
        name=name,
        location="Johar Town, Lahore, Pakistan",
        geo=GeoPoint(lat=31.4697, lng=74.2728),
    )


from pathlib import Path

DEMO_MART_PATH = Path(__file__).resolve().parents[3] / "shared/lastcall_shared/marts/demo_mart.json"


def make_rules() -> MartRules:
    return MartRules.model_validate_json(DEMO_MART_PATH.read_text())


def make_raw_place(
    pid: str,
    name: str,
    primary_type: str = "juice_shop",
    types: list[str] | None = None,
    lat: float = 31.4700,
    lng: float = 74.2730,
    phone: str = "+92 300 1234567",
    open_now: bool | None = True,
    business_status: str = "OPERATIONAL",
) -> PlaceRaw:
    return PlaceRaw(
        id=pid,
        name=name,
        primary_type=primary_type,
        types=types or [primary_type, "food"],
        lat=lat,
        lng=lng,
        business_status=business_status,
        international_phone=phone,
        open_now=open_now,
        maps_uri=f"https://maps.google.com/?cid={pid}",
    )


def test_scout_target_from_decision():
    """ScoutTarget.from_decision accepts bulk_sale, animal_feed and rejects keep/discount/compost."""
    # Invalid steps raise ScoutNotApplicable
    for step in ("keep", "discount", "compost"):
        dec = LadderDecision(
            item_key="banana",
            name="Banana",
            step=step,  # type: ignore
            allowed_steps=[step],  # type: ignore
            unit="kg",
            reason=f"Test {step}",
            buyer_condition="Ripe",
            buyer_types=["juice_shop"],
        )
        with pytest.raises(ScoutNotApplicable):
            ScoutTarget.from_decision(dec, "insp_123")

    # Valid steps succeed and copy fields
    dec_bulk = LadderDecision(
        item_key="banana",
        name="Banana",
        step="bulk_sale",
        allowed_steps=["bulk_sale"],
        unit="kg",
        reason="Test bulk sale",
        buyer_condition="Ripe, yellow with speckles",
        buyer_types=["juice_shop", "bakery"],
    )
    target_bulk = ScoutTarget.from_decision(dec_bulk, "insp_456")
    assert target_bulk.step == "bulk_sale"
    assert target_bulk.item_key == "banana"
    assert target_bulk.item == "Banana"
    assert target_bulk.condition == "Ripe, yellow with speckles"
    assert target_bulk.buyer_types == ("juice_shop", "bakery")

    dec_feed = LadderDecision(
        item_key="carrot",
        name="Carrot",
        step="animal_feed",
        allowed_steps=["animal_feed"],
        unit="kg",
        reason="Test animal feed",
        buyer_condition="Soft carrots",
        buyer_types=["dairy_farm"],
    )
    target_feed = ScoutTarget.from_decision(dec_feed, "insp_789")
    assert target_feed.step == "animal_feed"
    assert target_feed.buyer_types == ("dairy_farm",)


def test_hand_built_donate_target():
    """A hand-built donate target (Module 6 escalation path) is valid."""
    target_donate = ScoutTarget(
        inspection_id="insp_esc",
        item_key="spinach",
        item="Spinach",
        condition="Wilting, edible today",
        step="donate",
        buyer_types=("charity",),
    )
    assert target_donate.step == "donate"
    assert target_donate.buyer_types == ("charity",)


@pytest.mark.asyncio
async def test_run_scout_two_searches_parallel(monkeypatch):
    """2 types -> exactly 2 searches executed concurrently, typed Nearby and Text specs."""
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = InMemoryStore(clock=lambda: now)
    branch = make_branch()
    rules = make_rules()

    target = ScoutTarget(
        inspection_id="insp_001",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop", "bakery"),
    )

    searched_specs = []

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            searched_specs.append((spec.endpoint, spec.included_type or spec.text_query))
            if spec.included_type == "juice_shop":
                return [make_raw_place("ChIJ_juice1", "Fresh Juice Bar", "juice_shop", lat=31.471, lng=74.274, phone="+92 300 1111111")]
            else:
                return [make_raw_place("ChIJ_bake1", "Sweet Bakery", "bakery", lat=31.472, lng=74.275, phone="+92 300 2222222")]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(
                fits=[
                    FitOut(ref="c1", fit="likely", why="Uses ripe bananas for smoothies"),
                    FitOut(ref="c2", fit="likely", why="Uses bananas for banana bread"),
                ]
            ),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(searched_specs) == 2
    endpoints = [s[0] for s in searched_specs]
    assert endpoints == ["searchNearby", "searchNearby"]
    assert len(result.buyers) == 2
    assert result.meta.places_requests == 2
    assert result.meta.failed_searches == []
    assert result.branch_id == "johar_town"
    assert result.branch_name == "Johar Town"


@pytest.mark.asyncio
async def test_run_scout_one_search_fails_partial_result(monkeypatch):
    """When 1 of 2 searches fails, the other succeeds and failed_searches is recorded."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_002",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop", "bakery"),
    )

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            if spec.included_type == "juice_shop":
                return [make_raw_place("ChIJ_juice1", "Fresh Juice Bar", "juice_shop")]
            raise PlacesError(500, "Internal Server Error")

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(fits=[FitOut(ref="c1", fit="likely", why="Good fit")]),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(result.buyers) == 1
    assert result.meta.failed_searches == ["bakery"]


@pytest.mark.asyncio
async def test_run_scout_all_searches_fail_raises_scout_failed():
    """When all Places searches fail, ScoutFailed is raised."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_003",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop", "bakery"),
    )

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            raise PlacesError(503, "Service Unavailable")

    with pytest.raises(ScoutFailed):
        await run_scout(
            target,
            rules=rules,
            branch=branch,
            store=store,
            places=MockPlacesClient(),
            now=now,
        )


@pytest.mark.asyncio
async def test_run_scout_cap_refused_no_searches_made():
    """When reserve_places returns False, ScoutCapReached is raised without making searches."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_004",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    searched = False

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            nonlocal searched
            searched = True
            return []

    async def mock_reserve(count: int) -> bool:
        return False

    with pytest.raises(ScoutCapReached):
        await run_scout(
            target,
            rules=rules,
            branch=branch,
            store=store,
            places=MockPlacesClient(),
            reserve_places=mock_reserve,
            now=now,
        )

    assert not searched


@pytest.mark.asyncio
async def test_run_scout_seeded_deal_history_ranks_first(monkeypatch):
    """A buyer with past deals in store history ranks first."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_005",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    # Candidate 1 is nearer (0.2 km), Candidate 2 is further (1.0 km) but has a past deal
    c1 = make_raw_place("ChIJ_c1", "Near Juice Bar", lat=31.4705, lng=74.2730, phone="+92 300 1111111")
    c2 = make_raw_place("ChIJ_c2", "Loyal Juice Bar", lat=31.4750, lng=74.2750, phone="+92 300 2222222")

    # Seed deal in store
    await store.record_buyer_call(
        mart_id="demo_mart",
        buyer_id="places:ChIJ_c2",
        place_id="ChIJ_c2",
        outcome="deal",
        at=datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc),
        price=100.0,
        unit="kg",
    )

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c1, c2]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(
                fits=[
                    FitOut(ref="c1", fit="likely", why="Good"),
                    FitOut(ref="c2", fit="likely", why="Good"),
                ]
            ),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(result.buyers) == 2
    assert result.buyers[0].buyer_id == "places:ChIJ_c2"
    assert result.buyers[0].past_deals == 1
    assert "Bought from us" in result.buyers[0].reason
    assert result.buyers[1].buyer_id == "places:ChIJ_c1"


@pytest.mark.asyncio
async def test_run_scout_dnc_by_place_id_and_by_phone_key(monkeypatch):
    """DNC buyers are filtered out whether listed under places:ID or phone:KEY."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    phone_secret = get_settings().APP_SIGNING_KEY.get_secret_value()

    target = ScoutTarget(
        inspection_id="insp_006",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    c_ok = make_raw_place("ChIJ_ok", "Good Juice Bar", phone="+92 300 1111111")
    c_dnc_place = make_raw_place("ChIJ_dnc_pid", "DNC By Place", phone="+92 300 2222222")
    c_dnc_phone = make_raw_place("ChIJ_dnc_phone", "DNC By Phone", phone="+92 300 3333333")

    # Add DNC records
    await store.add_do_not_call("demo_mart", "places:ChIJ_dnc_pid")
    await store.add_do_not_call("demo_mart", phone_key("+923003333333", phone_secret))

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c_ok, c_dnc_place, c_dnc_phone]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(fits=[FitOut(ref="c1", fit="likely", why="Good")]),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(result.buyers) == 1
    assert result.buyers[0].buyer_id == "places:ChIJ_ok"
    assert result.skipped.get("do_not_call") == 2


@pytest.mark.asyncio
async def test_run_scout_duplicate_phone_keeps_nearer_only(monkeypatch):
    """Two listings with the same phone -> only nearer appears, duplicate_phone count incremented."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_007",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    # Same phone, different distance
    c_near = make_raw_place("ChIJ_near", "Branch 1", lat=31.4705, lng=74.2730, phone="+92 300 9999999")
    c_far = make_raw_place("ChIJ_far", "Branch 2", lat=31.4850, lng=74.2850, phone="+92 300 9999999")

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c_near, c_far]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(fits=[FitOut(ref="c1", fit="likely", why="Good")]),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(result.buyers) == 1
    assert result.buyers[0].buyer_id == "places:ChIJ_near"
    assert result.skipped.get("duplicate_phone") == 1


@pytest.mark.asyncio
async def test_run_scout_gemini_fallback_on_error(monkeypatch):
    """If Gemini fit screening fails, all candidates default to possible with fit_fallback=True."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_008",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    c1 = make_raw_place("ChIJ_c1", "Juice Stop")

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c1]

    async def mock_call_structured_fail(*args, **kwargs):
        raise GeminiCallError("Quota exhausted", status_code=429)

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured_fail)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    assert len(result.buyers) == 1
    assert result.buyers[0].fit == "possible"
    assert result.meta.fit_fallback is True


@pytest.mark.asyncio
async def test_run_scout_saved_result_validates_and_roundtrips(monkeypatch):
    """Saved ScoutResult can be read back from store and matches."""
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    store = InMemoryStore(clock=lambda: now)
    branch = make_branch()
    rules = make_rules()

    target = ScoutTarget(
        inspection_id="insp_009",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    c1 = make_raw_place("ChIJ_c1", "Juice Stop")

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c1]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(fits=[FitOut(ref="c1", fit="likely", why="Good fit")]),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    result = await run_scout(
        target,
        rules=rules,
        branch=branch,
        store=store,
        places=MockPlacesClient(),
        now=now,
    )

    loaded = await store.get_scout_result(result.key)
    assert loaded is not None
    assert loaded.key == result.key
    assert loaded.mart_id == "demo_mart"
    assert loaded.step == "bulk_sale"
    assert len(loaded.buyers) == 1
    assert loaded.buyers[0].name == "Juice Stop"


@pytest.mark.asyncio
async def test_run_scout_structured_logging_never_logs_phones_or_raw_names(monkeypatch, caplog):
    """Structured logging records key, step, counts but NEVER raw phone numbers or business names."""
    store = InMemoryStore()
    branch = make_branch()
    rules = make_rules()
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    target = ScoutTarget(
        inspection_id="insp_010",
        item_key="banana",
        item="Banana",
        condition="Ripe",
        step="bulk_sale",
        buyer_types=("juice_shop",),
    )

    raw_phone = "+92 300 7654321"
    raw_name = "Super Secret Juice House"
    c1 = make_raw_place("ChIJ_c1", raw_name, phone=raw_phone)

    class MockPlacesClient:
        async def search(self, spec, center, radius_km, deadline=None):
            return [c1]

    async def mock_call_structured(client, contents, config, schema, deadline, **kwargs):
        return (
            FitsOut(fits=[FitOut(ref="c1", fit="likely", why="Good fit")]),
            CallUsage(input_tokens=100, output_tokens=20, cached_tokens=0),
            1,
            False,
        )

    monkeypatch.setattr("lastcall_api.scout.fit.call_structured", mock_call_structured)

    with caplog.at_level(logging.INFO):
        await run_scout(
            target,
            rules=rules,
            branch=branch,
            store=store,
            places=MockPlacesClient(),
            now=now,
        )

    log_text = " ".join(record.message for record in caplog.records)
    for record in caplog.records:
        # Check formatted output if structured json logging is used
        if hasattr(record, "__dict__"):
            dumped = json.dumps({k: str(v) for k, v in record.__dict__.items()})
            assert "7654321" not in dumped, "Raw phone number leaked into structured log!"
            assert raw_name not in dumped, "Raw business name leaked into structured log!"
