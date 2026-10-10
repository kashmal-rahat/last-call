"""Tests for produce profiles resolution, caching, and D30 compliance (Step 3)."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
import pytest
from google.genai import types

from lastcall_api.gemini_call import CallUsage, GeminiCallError
from lastcall_api.ladder.profiles import (
    PROFILE_PROMPT_VERSION,
    ProfileOut,
    ProfilesOut,
    build_profile_config,
    check_profile,
    fallback_profile,
    produce_key,
    resolve_profiles,
)
from lastcall_shared.models import ProduceProfile, StageProfile
from lastcall_shared.store import InMemoryStore

FORBIDDEN_CONFIG_KEYS = {"temperature", "top_p", "top_k", "seed", "candidate_count", "presence_penalty", "frequency_penalty"}
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, parsed=None, text="", prompt_tokens=50, cand_tokens=25):
        self.parsed = parsed
        self.text = text
        self.usage_metadata = MagicMock(
            prompt_token_count=prompt_tokens,
            candidates_token_count=cand_tokens,
            thoughts_token_count=5,
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


def test_produce_key_normalisation():
    assert produce_key(" Green Apple ") == "green_apple"
    assert produce_key("banana") == "banana"
    assert produce_key("Okra / Bhindi") == "okra_bhindi"
    assert produce_key("---tomato---") == "tomato"


def test_d30_guard_on_profile_config():
    cfg = build_profile_config()
    cfg_dump = cfg.model_dump(exclude_none=True)
    for key in FORBIDDEN_CONFIG_KEYS:
        assert key not in cfg_dump, f"Forbidden key '{key}' found in profile config"


def test_check_profile_monotonic_and_note():
    # Setup violating profile: fresh=6_to_24h, ripening=1_to_3_days (longer!), overripe=over_3_days (even longer!)
    fresh_sp = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=False, charity=True)
    rip_sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    over_sp = StageProfile(sellable_for="over_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)

    long_note = "A" * 150
    prof = ProduceProfile(
        key="spinach__v1",
        name="spinach",
        note=long_note,
        fresh=fresh_sp,
        ripening=rip_sp,
        overripe=over_sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=False,
        source="gemini",
        prompt_version="1",
        created_at=NOW,
    )

    checked, notes = check_profile(prof)
    # ripening must be capped to fresh ("6_to_24h")
    assert checked.ripening.sellable_for == "6_to_24h"
    # overripe must be capped to ripening ("6_to_24h")
    assert checked.overripe.sellable_for == "6_to_24h"
    # note must be truncated to <= 120 chars
    assert len(checked.note) == 120
    assert len(notes) >= 2


@pytest.mark.asyncio
async def test_resolve_profiles_cached_makes_zero_calls():
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    p = ProduceProfile(
        key="banana__v1",
        name="banana",
        note="Preloaded banana",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=NOW,
    )
    await store.create_profile(p)

    fake_client = FakeGenAIClient([])
    deadline = asyncio.get_event_loop().time() + 10.0

    profiles, usage, stats = await resolve_profiles(
        ["banana"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )

    assert fake_client.call_count == 0
    assert "banana" in profiles
    assert profiles["banana"].note == "Preloaded banana"
    assert usage.input_tokens == 0
    assert stats.calls == 0
    assert stats.generated == 0
    assert stats.fallbacks == 0


@pytest.mark.asyncio
async def test_resolve_profiles_manager_wins_over_gemini():
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)

    gemini_p = ProduceProfile(
        key=f"banana__v{PROFILE_PROMPT_VERSION}",
        name="banana",
        note="Gemini note",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=NOW,
    )
    manager_p = ProduceProfile(
        key="banana__manager",
        name="banana",
        note="Manager corrected note",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="manager",
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=NOW,
    )
    await store.create_profile(gemini_p)
    await store.set_profile(manager_p)

    fake_client = FakeGenAIClient([])
    deadline = asyncio.get_event_loop().time() + 10.0

    profiles, _, stats = await resolve_profiles(
        ["banana"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )

    assert fake_client.call_count == 0
    assert profiles["banana"].source == "manager"
    assert profiles["banana"].note == "Manager corrected note"
    assert stats.calls == 0


@pytest.mark.asyncio
async def test_resolve_profiles_three_unknowns_one_call_and_cached():
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)

    out = ProfilesOut(
        profiles=[
            ProfileOut(input_name="apple", note="Fresh apple", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
            ProfileOut(input_name="guava", note="Fresh guava", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
            ProfileOut(input_name="mango", note="Fresh mango", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ]
    )
    fake_client = FakeGenAIClient([FakeResponse(parsed=out)])
    deadline = asyncio.get_event_loop().time() + 10.0

    profiles, usage, stats = await resolve_profiles(
        ["apple", "guava", "mango"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )

    assert fake_client.call_count == 1
    assert stats.calls == 1
    assert stats.generated == 3
    assert stats.fallbacks == 0
    assert len(profiles) >= 3
    assert profiles["apple"].source == "gemini"
    assert profiles["guava"].source == "gemini"
    assert profiles["mango"].source == "gemini"

    # Verify they were saved in store
    stored = await store.get_profiles([f"apple__v{PROFILE_PROMPT_VERSION}", f"guava__v{PROFILE_PROMPT_VERSION}"])
    assert len(stored) == 2


@pytest.mark.asyncio
async def test_resolve_profiles_missing_answer_gives_fallback_for_that_only():
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)

    # Gemini only returns 'apple', misses 'papaya'
    out = ProfilesOut(
        profiles=[
            ProfileOut(input_name="apple", note="Fresh apple", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ]
    )
    fake_client = FakeGenAIClient([FakeResponse(parsed=out)])
    deadline = asyncio.get_event_loop().time() + 10.0

    profiles, _, stats = await resolve_profiles(
        ["apple", "papaya"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )

    assert profiles["apple"].source == "gemini"
    assert profiles["papaya"].source == "fallback"
    assert stats.calls == 1
    assert stats.generated == 1
    assert stats.fallbacks == 1

    # Papaya fallback must NOT be saved in store
    stored = await store.get_profiles([f"papaya__v{PROFILE_PROMPT_VERSION}"])
    assert len(stored) == 0


@pytest.mark.asyncio
async def test_resolve_profiles_failed_call_gives_all_fallbacks_nothing_saved():
    store = InMemoryStore()
    fake_client = FakeGenAIClient([RuntimeError("Gemini unavailable")])
    deadline = asyncio.get_event_loop().time() + 10.0

    profiles, _, stats = await resolve_profiles(
        ["tomato", "potato"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )

    assert profiles["tomato"].source == "fallback"
    assert profiles["potato"].source == "fallback"
    assert stats.calls == 1
    assert stats.generated == 0
    assert stats.fallbacks == 2

    stored = await store.get_profiles([f"tomato__v{PROFILE_PROMPT_VERSION}", f"potato__v{PROFILE_PROMPT_VERSION}"])
    assert len(stored) == 0


def test_check_profile_charity_correction():
    """C2: in check_profile, set charity = True for fresh, ripening and overripe stages."""
    fresh_sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=False)
    rip_sp = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=False, charity=False)
    over_sp = StageProfile(sellable_for="under_6h", juice_shop=True, restaurant=False, bakery=False, charity=False)

    prof = ProduceProfile(
        key="banana__v1",
        name="banana",
        note="Test banana",
        fresh=fresh_sp,
        ripening=rip_sp,
        overripe=over_sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version="1",
        created_at=NOW,
    )
    checked, notes = check_profile(prof)
    assert checked.fresh.charity is True
    assert checked.ripening.charity is True
    assert checked.overripe.charity is True
    assert any("charity" in n for n in notes)


@pytest.mark.asyncio
async def test_resolve_profiles_race_condition_reads_back_stored(monkeypatch):
    """I1: If store.create_profile returns False, read the stored __v{N} profile back and use it."""
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    out = ProfilesOut(
        profiles=[
            ProfileOut(input_name="banana", note="My new banana", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ]
    )
    fake_client = FakeGenAIClient([FakeResponse(parsed=out)])

    winner_profile = ProduceProfile(
        key=f"banana__v{PROFILE_PROMPT_VERSION}",
        name="banana",
        note="Winner banana from concurrent writer",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=NOW,
    )

    async def race_create_profile(p):
        await store.set_profile(winner_profile)
        return False

    monkeypatch.setattr(store, "create_profile", race_create_profile)

    deadline = asyncio.get_event_loop().time() + 10.0
    profiles, _, stats = await resolve_profiles(
        ["banana"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )
    assert fake_client.call_count == 1
    assert "banana" in profiles
    assert profiles["banana"].note == "Winner banana from concurrent writer"
    assert stats.generated == 1


@pytest.mark.asyncio
async def test_resolve_profiles_save_exception_still_uses_generated(monkeypatch):
    """I2: If saving a profile raises, log a warning and still use generated profile."""
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    out = ProfilesOut(
        profiles=[
            ProfileOut(input_name="mango", note="Fresh mango", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ]
    )
    fake_client = FakeGenAIClient([FakeResponse(parsed=out)])

    async def broken_create_profile(p):
        raise RuntimeError("Simulated Firestore timeout")

    monkeypatch.setattr(store, "create_profile", broken_create_profile)

    deadline = asyncio.get_event_loop().time() + 10.0
    profiles, _, stats = await resolve_profiles(
        ["mango"],
        store=store,
        client=fake_client,
        deadline=deadline,
    )
    assert fake_client.call_count == 1
    assert "mango" in profiles
    assert profiles["mango"].note == "Fresh mango"
    assert profiles["mango"].source == "gemini"
    assert stats.generated == 1

