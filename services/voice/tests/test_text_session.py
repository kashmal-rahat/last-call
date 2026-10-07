"""Tests for Negotiator text session lifecycle and agent setup."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from lastcall_shared.store import InMemoryStore
from lastcall_voice.call_context import get_context
from lastcall_voice.text_session import (
    start_text_call,
    end_text_call,
)

PKT = ZoneInfo("Asia/Karachi")


@pytest.mark.asyncio
async def test_text_session_start_and_early_end():
    store = InMemoryStore()
    fixed_now = datetime(2026, 10, 7, 10, 0, 0, tzinfo=PKT)

    call_id = await start_text_call(store, "easy_yes", now=fixed_now)
    assert call_id is not None
    assert get_context(call_id) is not None

    call = await store.get_call(call_id)
    assert call is not None
    assert call.status == "in_progress"

    batch = await store.get_batch(call.batch_id)
    assert batch is not None
    assert batch.locked_by_call == call_id

    # Ending without buyer speaking -> outcome is no_answer
    result = await end_text_call(call_id)
    assert result.status == "completed"
    assert result.outcome == "no_answer"
    assert get_context(call_id) is None

    # Batch lock released
    batch_after = await store.get_batch(call.batch_id)
    assert batch_after.locked_by_call is None


@pytest.mark.asyncio
async def test_text_session_dropped_callback():
    store = InMemoryStore()
    fixed_now = datetime(2026, 10, 7, 10, 0, 0, tzinfo=PKT)

    call_id = await start_text_call(store, "hard_bargainer", now=fixed_now)
    ctx = get_context(call_id)
    # Simulate buyer having spoken
    ctx.buyer_spoke = True

    result = await end_text_call(call_id)
    assert result.outcome == "call_back"
    assert result.callback_at is not None
    assert "dropped" in result.flags
