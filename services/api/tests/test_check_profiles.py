"""Unit tests for scripts/check_profiles.py."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from lastcall_api.ladder.profiles import ProfileOut, ProfilesOut
from lastcall_shared.models import StageProfile
from scripts.check_profiles import (
    calculate_cost,
    check_profiles_flow,
    compare_profiles,
)
from lastcall_api.gemini_call import CallUsage


class FakeResponse:
    def __init__(self, parsed=None, prompt_tokens=100, cand_tokens=80):
        self.parsed = parsed
        self.text = ""
        self.usage_metadata = MagicMock(
            prompt_token_count=prompt_tokens,
            candidates_token_count=cand_tokens,
            thoughts_token_count=10,
            cached_content_token_count=0,
        )


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.aio = MagicMock()
        self.aio.models.generate_content = self._generate_content

    async def _generate_content(self, model, contents, config):
        resp = self.responses.pop(0)
        return resp


def test_calculate_cost():
    usage = CallUsage(input_tokens=1_000_000, output_tokens=1_000_000, cached_tokens=0)
    cost = calculate_cost(usage)
    assert abs(cost - (0.75 + 3.75)) < 1e-6


def test_compare_profiles_identical_and_differing():
    sp1 = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    sp2 = StageProfile(sellable_for="6_to_24h", juice_shop=False, restaurant=True, bakery=False, charity=True)

    p1 = ProfileOut(
        input_name="banana",
        note="note 1",
        fresh=sp1,
        ripening=sp1,
        overripe=sp1,
        overripe_ok_for_cattle=True,
        spoiled_ok_for_cattle=False,
    )
    p2 = ProfileOut(
        input_name="banana",
        note="note 2",
        fresh=sp1,
        ripening=sp2,  # differing band and juice_shop
        overripe=sp1,
        overripe_ok_for_cattle=False,  # differing cattle
        spoiled_ok_for_cattle=False,
    )

    # Identical
    comp_same = compare_profiles(p1, p1)
    assert comp_same["identical"] is True
    assert comp_same["diff_count"] == 0

    # Differing
    comp_diff = compare_profiles(p1, p2)
    assert comp_diff["identical"] is False
    assert comp_diff["diff_count"] >= 2


@pytest.mark.asyncio
async def test_check_profiles_flow_with_fake_client(tmp_path):
    sp = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    items1 = [
        ProfileOut(input_name="banana", note="banana", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ProfileOut(input_name="spinach", note="spinach", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=False, spoiled_ok_for_cattle=False),
    ]
    sp_differ = StageProfile(sellable_for="under_6h", juice_shop=False, restaurant=False, bakery=False, charity=True)
    items2 = [
        ProfileOut(input_name="banana", note="banana", fresh=sp, ripening=sp, overripe=sp, overripe_ok_for_cattle=True, spoiled_ok_for_cattle=False),
        ProfileOut(input_name="spinach", note="spinach", fresh=sp, ripening=sp, overripe=sp_differ, overripe_ok_for_cattle=False, spoiled_ok_for_cattle=False),
    ]

    client = FakeClient([
        FakeResponse(parsed=ProfilesOut(profiles=items1)),
        FakeResponse(parsed=ProfilesOut(profiles=items2)),
    ])

    out_md = tmp_path / "profiles.md"
    results = await check_profiles_flow(
        produce_names=["banana", "spinach"],
        client=client,
        output_md_path=out_md,
    )

    assert results["total_produce"] == 2
    assert results["differences_count"] == 1  # spinach differed between run 1 and run 2
    assert out_md.is_file()
    content = out_md.read_text(encoding="utf-8")
    assert "Produce Profiles Accuracy & Consistency Report" in content
    assert "Sense check (user)" in content
    assert "labels" not in content.lower()
