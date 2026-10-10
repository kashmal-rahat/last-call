"""Tests for decide_inspection orchestration and consistency guarantee (Step 5)."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
import pytest

from lastcall_api.ladder.ladder import decide_inspection
from lastcall_api.ladder.profiles import ProfileOut, ProfilesOut
from lastcall_shared.marts.loader import load_mart_rules
from lastcall_shared.models import (
    BoundingBox,
    FreshnessResult,
    ItemAssessment,
    ObservedQuantity,
    QuantityEstimate,
    StageProfile,
)
from lastcall_shared.store import InMemoryStore

NOW = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, parsed=None, prompt_tokens=60, cand_tokens=40):
        self.parsed = parsed
        self.text = ""
        self.usage_metadata = MagicMock(
            prompt_token_count=prompt_tokens,
            candidates_token_count=cand_tokens,
            thoughts_token_count=10,
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
        resp = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(resp, Exception):
            raise resp
        return resp


def _make_item(name: str, stage: str, stage_level: str, item_key: str, unit: str = "kg") -> ItemAssessment:
    return ItemAssessment(
        item_key=item_key,
        name=name,
        grid="center",
        position=BoundingBox(ymin=0.1, xmin=0.1, ymax=0.4, xmax=0.4),
        stage=stage,
        stage_level=stage_level,
        worst_stage=stage,
        score=85.0,
        confidence=0.9,
        confidence_level="high",
        issues=[],
        evidence="",
        observed=ObservedQuantity(method="count", min=10, max=10),
        quantity=QuantityEstimate(unit=unit, low=2.0, high=2.0),
        needs_staff_check=False,
        staff_check_reasons=[],
    )


def _make_inspection(status: str = "ok", items: list[ItemAssessment] | None = None) -> FreshnessResult:
    return FreshnessResult(
        mart_id="demo_mart",
        inspection_id="insp_test_001",
        shelf_id="shelf_01",
        photo_uri="upload:sha256:12345",
        taken_at=NOW,
        photo_status=status,
        photo_note="" if status == "ok" else "Empty shelf",
        items=items or [],
    )


@pytest.mark.asyncio
async def test_decide_inspection_end_to_end_and_consistency_guarantee():
    rules = load_mart_rules("demo_mart")
    store = InMemoryStore()

    sp_fresh = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    sp_rip = StageProfile(sellable_for="6_to_24h", juice_shop=True, restaurant=True, bakery=True, charity=True)
    sp_over = StageProfile(sellable_for="under_6h", juice_shop=True, restaurant=False, bakery=True, charity=True)
    sp_spinach_over = StageProfile(sellable_for="under_6h", juice_shop=False, restaurant=False, bakery=False, charity=True)

    fake_out = ProfilesOut(
        profiles=[
            ProfileOut(
                input_name="banana",
                note="Tropical fruit",
                fresh=sp_fresh,
                ripening=sp_rip,
                overripe=sp_over,
                overripe_ok_for_cattle=True,
                spoiled_ok_for_cattle=False,
            ),
            ProfileOut(
                input_name="spinach",
                note="Leafy greens",
                fresh=sp_rip,
                ripening=sp_spinach_over,
                overripe=sp_spinach_over,
                overripe_ok_for_cattle=False,
                spoiled_ok_for_cattle=False,
            ),
        ]
    )

    fake_client = FakeGenAIClient([FakeResponse(parsed=fake_out)])

    item1 = _make_item("banana", "ripening", "late", "item_banana_1", unit="dozen")
    item2 = _make_item("spinach", "overripe", "mid", "item_spinach_1", unit="kg")
    insp = _make_inspection(status="ok", items=[item1, item2])

    # Run 1: Gemini writes profiles, code decides
    res1 = await decide_inspection(
        insp,
        rules=rules,
        store=store,
        now=NOW,
        hours_override=3.0,
        client=fake_client,
    )

    assert len(res1.decisions) == 2
    assert fake_client.call_count == 5
    assert res1.meta.profile_calls == 5
    assert res1.meta.profiles_generated == 2
    assert res1.decisions[0].name == "banana"
    assert res1.decisions[0].step == "discount"
    assert res1.decisions[1].name == "spinach"
    assert res1.decisions[1].step == "discount"  # D44: no business buyers -> 40% discount, next_steps [donate]
    assert res1.decisions[1].discount_pct == 40
    assert res1.decisions[1].next_steps == ["donate"]

    # Run 2: EXACT SAME INPUT -> ZERO Gemini calls and IDENTICAL result (consistency guarantee)
    res2 = await decide_inspection(
        insp,
        rules=rules,
        store=store,
        now=NOW,
        hours_override=3.0,
        client=fake_client,
    )

    # ZERO new Gemini calls made
    assert fake_client.call_count == 5
    assert res2.meta.profile_calls == 0
    assert res2.meta.profiles_generated == 0
    # Decisions are completely identical
    assert len(res2.decisions) == len(res1.decisions)
    for d1, d2 in zip(res1.decisions, res2.decisions):
        assert d1.step == d2.step
        assert d1.discount_pct == d2.discount_pct
        assert d1.discounted_price == d2.discounted_price
        assert d1.opening_price == d2.opening_price
        assert d1.floor_price == d2.floor_price
        assert d1.reason == d2.reason
        assert d1.buyer_condition == d2.buyer_condition


@pytest.mark.asyncio
async def test_decide_inspection_price_and_hours_overrides():
    rules = load_mart_rules("demo_mart")
    store = InMemoryStore()

    sp_fresh = StageProfile(sellable_for="1_to_3_days", juice_shop=True, restaurant=True, bakery=False, charity=True)
    fake_out = ProfilesOut(
        profiles=[
            ProfileOut(
                input_name="guava",
                note="Guava fruit",
                fresh=sp_fresh,
                ripening=sp_fresh,
                overripe=sp_fresh,
                overripe_ok_for_cattle=True,
                spoiled_ok_for_cattle=False,
            ),
        ]
    )
    fake_client = FakeGenAIClient([FakeResponse(parsed=fake_out)])

    item = _make_item("guava", "fresh", "early", "item_guava_1", unit="kg")
    insp = _make_inspection(status="ok", items=[item])

    # Default price in demo_mart is 140. We override it with 200.
    res = await decide_inspection(
        insp,
        rules=rules,
        store=store,
        now=NOW,
        hours_override=12.0,
        price_overrides={"item_guava_1": 200},
        client=fake_client,
    )

    assert len(res.decisions) == 1
    dec = res.decisions[0]
    assert dec.shelf_price == 200
    assert res.hours_until_closing == 12.0


@pytest.mark.asyncio
async def test_decide_inspection_no_produce_returns_empty():
    rules = load_mart_rules("demo_mart")
    store = InMemoryStore()

    insp = _make_inspection(status="no_produce", items=[])
    res = await decide_inspection(
        insp,
        rules=rules,
        store=store,
        now=NOW,
    )

    assert len(res.decisions) == 0
    assert res.meta.profiles_used == 0
    assert res.meta.profile_calls == 0
