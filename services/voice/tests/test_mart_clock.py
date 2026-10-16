"""D74: a call runs on the mart's time (set by Time of day), while records keep the real time.

The worst case before D74: a judge picks "12 h left" (the mart at 11:00) while it is 22:00 in Lahore. The buyer
agrees to collect "aaj 3 baje" (15:00 today) and `confirm_deal` refused it as in the past, on the real clock.
"""

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient

from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import InMemoryStore
from lastcall_voice.call_context import CallContext, get_context, register_context, unregister_context
from lastcall_voice.negotiator.tools import confirm_deal, schedule_callback

PKT = ZoneInfo("Asia/Karachi")
REAL = datetime(2026, 10, 16, 22, 0, tzinfo=PKT)  # the real time in Lahore
MART = datetime(2026, 10, 16, 11, 0, tzinfo=PKT)  # "12 h left": the mart's time
OFFSET_S = (MART - REAL).total_seconds()
KEY = "test-secret-key-12345-at-least-32-chars-long"


class FakeToolContext:
    def __init__(self, call_id: str):
        self.state = {"call_id": call_id}


async def _call_on_mart_time():
    """A call whose brief was made on the mart's time (pickup until 15:00), with both clocks in its context."""
    store = InMemoryStore(clock=lambda: REAL)
    call, batch = build_call("easy_yes", now=MART)  # pickup deadline: MART + 4 h = 15:00
    call.negotiation.approved_prices = [call.negotiation.ladder[0]]
    await store.create_call(call, batch)
    await store.lock_batch(batch.batch_id, call.call_id, REAL + timedelta(minutes=10))
    ctx = CallContext(store=store, call_id=call.call_id, mode="voice", clock=lambda: REAL, mart_clock=lambda: MART)
    register_context(ctx)
    return store, call, ctx


async def _confirm(call) -> dict:
    return await confirm_deal(
        price_per_unit=call.negotiation.ladder[0],
        quantity=call.brief.quantity,
        buyer_confirmed=True,
        tool_context=FakeToolContext(call.call_id),
    )


async def test_confirm_deal_holds_the_stock_until_the_deadline_on_the_mart_day():
    """D76: the pickup is the deadline (mart 15:00), which is past on the real clock (22:00) but not the mart's."""
    store, call, _ = await _call_on_mart_time()
    try:
        result = await _confirm(call)
    finally:
        unregister_context(call.call_id)

    assert result["ok"] is True, result
    deal = await store.get_deal(call.call_id)
    assert deal.pickup_time == call.brief.pickup_deadline == MART.replace(hour=15)
    assert deal.created_at == REAL  # the record keeps the real time
    (outbox,) = await store.get_outbox(call.call_id)
    assert "Pickup: today, by 3 PM" in outbox.payload["text"]  # "today" on the mart's day


async def test_confirm_deal_refuses_once_the_deadline_has_passed_on_the_mart_clock():
    store, call, ctx = await _call_on_mart_time()
    ctx.mart_clock = lambda: MART.replace(hour=15, minute=5)  # the call ran past 15:00
    try:
        result = await _confirm(call)
    finally:
        unregister_context(call.call_id)

    assert result["ok"] is False
    assert "deadline has passed" in result["reasons"][0]
    assert not ctx.outcome_set
    assert await store.get_deal(call.call_id) is None


async def test_schedule_callback_keeps_a_time_later_in_the_mart_day():
    _, call, ctx = await _call_on_mart_time()
    try:
        result = await schedule_callback("17:00", "busy now", tool_context=FakeToolContext(call.call_id))
    finally:
        unregister_context(call.call_id)

    assert result["ok"] is True
    assert ctx.callback_at == MART.replace(hour=17)  # today, not rolled to tomorrow by the real 22:00


@pytest.mark.parametrize(
    "mart_hour,retry",
    [
        (11, datetime(2026, 10, 16, 13, 0, tzinfo=PKT)),  # 2 h later, inside calling hours
        (6, datetime(2026, 10, 16, 9, 0, tzinfo=PKT)),  # before calling hours: at their start
        (20, datetime(2026, 10, 17, 9, 0, tzinfo=PKT)),  # after them: the next morning
    ],
)
def test_a_dropped_calls_retry_is_on_the_mart_day_within_calling_hours(mart_hour, retry):
    call, _ = build_call("easy_yes", now=MART)  # calling hours 09:00–21:00
    ctx = CallContext(
        store=InMemoryStore(), call_id="call_x", clock=lambda: REAL, mart_clock=lambda: MART.replace(hour=mart_hour)
    )
    assert ctx.retry_after_drop(call.brief.calling_hours) == retry


def test_without_a_mart_clock_the_context_uses_its_clock():
    """Text sessions and the simulator set only `clock`: their behaviour is unchanged."""
    ctx = CallContext(store=InMemoryStore(), call_id="call_x", clock=lambda: REAL)
    assert ctx.now() == REAL
    assert ctx.mart_now() == REAL


# --- The live session: the agent's time and a dropped call's retry are on the mart's time ----------------------


@pytest.fixture
def live_call(monkeypatch):
    """A call with the batch at mart 11:00, run by the live session while the real time is 22:00."""
    from lastcall_voice import live_session
    from lastcall_voice.main import app

    class FixedRealTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return REAL.astimezone(tz) if tz else REAL

    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setattr(live_session, "datetime", FixedRealTime)
    store = InMemoryStore(clock=lambda: REAL)
    app.state.store = store
    app.state.signing_key = KEY
    app.state.semaphore = asyncio.Semaphore(4)

    call, batch = build_call("easy_yes", now=MART)
    call.clock_offset_s = OFFSET_S
    asyncio.run(store.create_call(call, batch))
    return app, store, call


def test_live_session_gives_the_agent_the_mart_time_and_retries_a_dropped_call_on_it(monkeypatch, live_call):
    from lastcall_voice import live_session

    app, store, call = live_call
    seen: dict = {}
    build_negotiator = live_session.build_negotiator

    def capture_agent_clock(**kwargs):
        seen["agent_now"] = kwargs["clock"]()
        return build_negotiator(**kwargs)

    class BuyerSpokeThenDropped:
        """The buyer said something, then the connection failed with no outcome: a dropped call."""

        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            ctx = get_context(call.call_id)
            seen["ctx_now"], seen["ctx_mart_now"] = ctx.now(), ctx.mart_now()
            ctx.buyer_spoke = True
            raise RuntimeError("connection lost")
            yield None

    monkeypatch.setattr(live_session, "build_negotiator", capture_agent_clock)
    monkeypatch.setattr(live_session, "Runner", BuyerSpokeThenDropped)

    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY, now=REAL)
    with TestClient(app).websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive()

    assert seen["agent_now"] == MART  # the prompt's "Current time"
    assert seen["ctx_now"] == REAL and seen["ctx_mart_now"] == MART
    result = asyncio.run(store.get_call(call.call_id)).result
    assert result.outcome == "call_back" and "dropped" in result.flags
    # Retry 2 h later in the mart's day (13:00), not after the real 22:00 (which would be tomorrow 09:00)
    assert result.callback_at == MART + timedelta(hours=2)
