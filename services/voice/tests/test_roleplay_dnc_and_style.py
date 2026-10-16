"""Tests for Module 6 Step 5: role-play do-not-call safety and city style."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.store import InMemoryStore
from lastcall_voice.call_context import CallContext, register_context, unregister_context
from lastcall_voice.negotiator.prompt import render_instruction
from lastcall_voice.negotiator.tools import record_outcome
from lastcall_voice.text_session import end_text_call, get_context, start_text_call

PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 11, 14, 0, 0, tzinfo=PKT)


class FakeToolContext:
    def __init__(self, call_id: str):
        self.state = {"call_id": call_id}


@pytest.mark.asyncio
async def test_places_browser_call_does_not_record_dnc():
    store = InMemoryStore()
    call, batch = build_call("easy_yes", now=NOW)
    call.channel = "browser"
    call.brief.buyer.buyer_id = "places:ChIJ_real_business_123"

    await store.create_call(call, batch)

    ctx = CallContext(store=store, call_id=call.call_id)
    register_context(ctx)
    try:
        t_ctx = FakeToolContext(call.call_id)
        res = await record_outcome("do_not_call", "Judge said don't call again", tool_context=t_ctx)
        assert res["ok"] is True
        assert res["recorded"] == "do_not_call"

        # Verification: NO DNC entry in store
        assert await store.is_do_not_call(call.mart_id, "places:ChIJ_real_business_123") is False
        # Flag added
        assert "dnc_roleplay_not_recorded" in ctx.flags
    finally:
        unregister_context(call.call_id)


@pytest.mark.asyncio
async def test_test_buyer_still_records_dnc():
    store = InMemoryStore()
    call, batch = build_call("easy_yes", now=NOW)
    call.channel = "browser"
    call.brief.buyer.buyer_id = "test:easy_yes:buyer_1"

    await store.create_call(call, batch)

    ctx = CallContext(store=store, call_id=call.call_id)
    register_context(ctx)
    try:
        t_ctx = FakeToolContext(call.call_id)
        res = await record_outcome("do_not_call", "Test buyer opted out", tool_context=t_ctx)
        assert res["ok"] is True

        # Verification: DNC IS written for test: buyer
        assert await store.is_do_not_call(call.mart_id, "test:easy_yes:buyer_1") is True
        assert "dnc_roleplay_not_recorded" not in ctx.flags
    finally:
        unregister_context(call.call_id)


def test_city_style_lahore_renders_lahori_line():
    call, _ = build_call("easy_yes", now=NOW)
    agent_view = call.brief.agent_view()

    prompt_lahore = render_instruction(
        view=agent_view,
        agent_gender="female",
        city_style="lahore",
    )
    assert "Lahore market style: warm and friendly, relaxed and confident bargaining." in prompt_lahore
    assert "Paaji" not in prompt_lahore
    # One address rule for any buyer: "aap", then "Bhai" or "Baji" once clear; no fixed "Bhai" in the lines
    assert (
        'Speak to the buyer as "aap". Add "Bhai" for a man or "Baji" for a woman only once it is clear' in prompt_lahore
    )
    assert "Koi baat nahi, phir kabhi sahi. Allah Hafiz." in prompt_lahore
    assert "Assalam-o-Alaikum, main" in prompt_lahore

    prompt_karachi = render_instruction(
        view=agent_view,
        agent_gender="female",
        city_style="karachi",
    )
    assert "Karachi market style" in prompt_karachi
    assert "Paaji" not in prompt_karachi


@pytest.mark.asyncio
async def test_lock_released_after_deal_in_text_session():
    store = InMemoryStore()
    call_id = await start_text_call(store, "easy_yes", now=NOW)
    ctx = get_context(call_id)
    assert ctx is not None

    # Simulate deal occurred during session
    ctx.outcome_set = True
    ctx.outcome = "deal"
    ctx.agreed_price_per_unit = 160
    ctx.agreed_quantity = 30.0
    from datetime import timedelta

    ctx.pickup_time = NOW + timedelta(hours=2)

    call = await store.get_call(call_id)
    # End the call
    result = await end_text_call(call_id)
    assert result.outcome == "deal"

    # Batch lock must be released even though deal occurred!
    b = await store.get_batch(call.batch_id)
    assert b.locked_by_call is None
    assert b.locked_until is None
