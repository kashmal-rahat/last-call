"""Unit tests for scripts/produce_profiles.py (Step 7)."""

import json

import pytest

from lastcall_api.ladder.profiles import PROFILE_PROMPT_VERSION
from lastcall_shared.models import ProduceProfile, StageProfile
from lastcall_shared.store import InMemoryStore
from scripts.produce_profiles import cmd_delete, cmd_set, cmd_show, cmd_warm


class FakeResponse:
    def __init__(self, parsed):
        self.parsed = parsed
        self.usage_metadata = None


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    async def _generate_content(self, model, contents, config):
        self.call_count += 1
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


@pytest.mark.asyncio
async def test_cmd_warm_and_show(capsys):
    store = InMemoryStore()
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    p_banana = ProduceProfile(
        key=f"banana__v{PROFILE_PROMPT_VERSION}",
        name="banana",
        note="Banana preloaded",
        fresh=sp,
        ripening=sp,
        overripe=sp,
        spoiled_ok_for_cattle=False,
        overripe_ok_for_cattle=True,
        source="gemini",
        prompt_version=PROFILE_PROMPT_VERSION,
        created_at=store._now(),
    )
    await store.create_profile(p_banana)

    # 1. Warm already present item -> 0 calls, no error
    await cmd_warm(["banana"], store=store)
    out = capsys.readouterr().out
    assert "Done in" in out
    assert "banana__v1" in out

    # 2. Show banana
    await cmd_show("banana", store=store)
    out_show = capsys.readouterr().out
    assert "Banana preloaded" in out_show
    assert f"banana__v{PROFILE_PROMPT_VERSION}" in out_show


@pytest.mark.asyncio
async def test_cmd_set_and_delete(tmp_path, capsys):
    store = InMemoryStore()
    profile_data = {
        "note": "Manager specified note for mango",
        "fresh": {
            "sellable_for": "1_to_3_days",
            "juice_shop": True,
            "restaurant": True,
            "bakery": False,
            "charity": True,
        },
        "ripening": {
            "sellable_for": "6_to_24h",
            "juice_shop": True,
            "restaurant": True,
            "bakery": True,
            "charity": True,
        },
        "overripe": {
            "sellable_for": "under_6h",
            "juice_shop": True,
            "restaurant": False,
            "bakery": True,
            "charity": True,
        },
        "overripe_ok_for_cattle": True,
        "spoiled_ok_for_cattle": False,
        "uncertain_fields": ["ripening.sellable_for", "overripe.bakery"],
    }

    file_p = tmp_path / "mango.json"
    file_p.write_text(json.dumps(profile_data), encoding="utf-8")

    # 1. Set manager profile
    await cmd_set("mango", str(file_p), store=store)
    out = capsys.readouterr().out
    assert "Successfully set manager profile for 'mango' under 'mango__manager'" in out

    # Verify in store (B5: uncertain_fields must be empty for manager profiles)
    profs = await store.get_profiles(["mango__manager"])
    assert "mango__manager" in profs
    assert profs["mango__manager"].source == "manager"
    assert profs["mango__manager"].note == "Manager specified note for mango"
    assert profs["mango__manager"].uncertain_fields == []

    # 2. Delete manager profile
    await cmd_delete("mango", is_manager=True, store=store)
    out_del = capsys.readouterr().out
    assert "Successfully deleted profile 'mango__manager'" in out_del

    profs_after = await store.get_profiles(["mango__manager"])
    assert "mango__manager" not in profs_after
