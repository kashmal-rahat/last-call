"""Text session runner for automated and simulated negotiation turns."""

import re
from datetime import datetime, timedelta
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow._retry_config import RetryConfig
from google.genai import types
from pydantic import AwareDatetime

from lastcall_shared.clock import PKT
from lastcall_shared.config import get_settings
from lastcall_shared.models import (
    CallResult,
    TranscriptEntry,
)
from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.store import CallStore
from lastcall_voice.call_context import (
    CallContext,
    get_context,
    register_context,
    unregister_context,
)
from lastcall_voice.negotiator.agent import build_negotiator
from lastcall_voice.negotiator.price_guard import (
    classify as classify_price,
)
from lastcall_voice.negotiator.price_guard import (
    find_prices,
)

GEMINI_FLASH_MODEL = get_settings().GEMINI_FLASH_MODEL
APP_NAME = "lastcall_voice"

_ACTIVE_SESSIONS: dict[str, dict[str, Any]] = {}


async def start_text_call(
    store: CallStore,
    scenario: dict[str, Any] | str,
    now: AwareDatetime | None = None,
    agent_gender: str = "male",
    city_style: str = "karachi",
) -> str:
    """Initializes and locks a text-based negotiation session.

    Steps:
    1. build_call -> CallRecord, BatchRecord
    2. store.create_call, store.create_batch
    3. store.start_session with unique nonce
    4. store.lock_batch for call duration
    5. Register CallContext
    6. Create ADK session with state={"call_id", "mart_id"} and Runner
    """
    now_dt = now or datetime.now(PKT)
    call, batch = build_call(scenario, now_dt)
    call_id = call.call_id

    if hasattr(store, "clock") and getattr(store, "clock", None) is None:
        store.clock = lambda: now_dt

    await store.create_call(call, batch)
    await store.start_session(call_id, call.session_nonce)

    locked_until = now_dt + timedelta(seconds=call.policy.max_call_seconds)
    await store.lock_batch(batch.batch_id, call_id, locked_until)

    # Register in-memory context for tools and callbacks
    ctx = CallContext(
        store=store,
        call_id=call_id,
        mode="text",
        clock=lambda: now_dt,
    )
    register_context(ctx)

    # Initialize ADK session & runner
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=call.brief.buyer.buyer_id,
        session_id=call_id,
        state={"call_id": call_id, "mart_id": call.mart_id},
    )

    retry_cfg = RetryConfig(max_attempts=5, initial_delay=2.0, backoff_factor=2.0)
    flash_model = get_settings().GEMINI_FLASH_MODEL
    agent = build_negotiator(
        model=flash_model,
        view=call.brief.agent_view(),
        mode="text",
        agent_gender=agent_gender,  # type: ignore[arg-type]
        city_style=city_style,  # type: ignore[arg-type]
        clock=lambda: now_dt,
    )
    agent.retry_config = retry_cfg

    runner = Runner(agent=agent, session_service=session_service, app_name=APP_NAME)

    _ACTIVE_SESSIONS[call_id] = {
        "runner": runner,
        "session_service": session_service,
        "first_turn": True,
        "now": now_dt,
    }

    return call_id


async def run_text_turn(
    call_id: str,
    buyer_text: str,
    turn_time: AwareDatetime | None = None,
) -> str:
    """Executes a single dialogue turn with the negotiator agent.

    - First turn ignores buyer_text and sends the system kick-off prompt.
    - Subsequent turns strip leading '[SYSTEM]' prefix from buyer_text.
    - Inspects agent response for price guard breaches and logs transcripts.
    """
    session_data = _ACTIVE_SESSIONS.get(call_id)
    if not session_data:
        raise ValueError(f"No active text session found for call_id {call_id}")

    ctx = get_context(call_id)
    if not ctx:
        raise ValueError(f"No CallContext registered for call_id {call_id}")

    call = await ctx.store.get_call(call_id)
    if not call:
        raise ValueError(f"Call {call_id} not found in store")

    at_time = turn_time or ctx.now()
    runner: Runner = session_data["runner"]

    if session_data["first_turn"]:
        input_text = "[SYSTEM] The buyer has answered. Greet, disclose you are an AI, ask for a minute."
        session_data["first_turn"] = False
    else:
        clean_text = re.sub(r"^\[SYSTEM\]\s*", "", buyer_text).strip()
        input_text = clean_text
        ctx.buyer_spoke = True
        call.transcript.append(TranscriptEntry(speaker="buyer", text=clean_text, at=at_time))

    msg = types.Content(role="user", parts=[types.Part(text=input_text)])
    agent_text = ""

    async for event in runner.run_async(
        user_id=call.brief.buyer.buyer_id,
        session_id=call_id,
        new_message=msg,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    agent_text += part.text

    agent_text = agent_text.strip()

    # Price guard classification
    prices = find_prices(agent_text)
    current_price = call.negotiation.ladder[call.negotiation.rung]
    classification = classify_price(
        prices=prices,
        floor=call.negotiation.ladder[-1],
        approved_prices=call.negotiation.approved_prices,
        current_price=current_price,
    )
    if classification == "below_floor":
        if "floor_correction" not in ctx.flags:
            ctx.flags.append("floor_correction")
    elif classification == "unapproved":
        if "unapproved_price" not in ctx.flags:
            ctx.flags.append("unapproved_price")

    # Record agent turn in transcript
    call.transcript.append(TranscriptEntry(speaker="agent", text=agent_text, at=at_time))

    return agent_text


async def end_text_call(call_id: str) -> CallResult:
    """Finalizes a text call session, stores the CallResult, and cleans up resources.

    - Resolves outcome ('deal', 'call_back', 'declined', etc.)
    - Releases batch lock if no deal was agreed
    - Finishes call in store
    - Cleans up session and unregisters context
    """
    session_data = _ACTIVE_SESSIONS.pop(call_id, None)
    ctx = get_context(call_id)
    if not ctx:
        raise ValueError(f"No active context for call_id {call_id}")

    call = await ctx.store.get_call(call_id)
    if not call:
        raise ValueError(f"Call {call_id} not found in store")

    # Determine final outcome
    if ctx.outcome_set and ctx.outcome:
        outcome = ctx.outcome
    else:
        if not ctx.buyer_spoke:
            outcome = "no_answer"
        else:
            outcome = "call_back"
            ctx.callback_at = ctx.retry_after_drop(call.brief.calling_hours)
            if "dropped" not in ctx.flags:
                ctx.flags.append("dropped")

    # Always release batch lock at the end of the call
    await ctx.store.release_batch(call.batch_id, call_id)

    # Build CallResult
    result = CallResult(
        call_id=call_id,
        batch_id=call.batch_id,
        mart_id=call.mart_id,
        status="completed",
        deal_type=call.brief.deal_type,
        outcome=outcome,  # type: ignore[arg-type]
        agreed_price_per_unit=ctx.agreed_price_per_unit,
        agreed_price_unit=call.brief.opening_price_unit if ctx.agreed_price_per_unit is not None else None,
        currency=call.brief.currency,
        agreed_quantity=ctx.agreed_quantity,
        agreed_quantity_unit=call.brief.quantity_unit if ctx.agreed_quantity is not None else None,
        pickup_time=ctx.pickup_time,
        callback_at=ctx.callback_at,
        transcript=call.transcript,
        summary="",
        flags=list(set(ctx.flags + call.flags)),
    )

    await ctx.store.finish_call(call_id, result)

    # Cleanup ADK session and registry
    if session_data:
        sess_service: InMemorySessionService = session_data["session_service"]
        try:
            await sess_service.delete_session(
                app_name=APP_NAME,
                user_id=call.brief.buyer.buyer_id,
                session_id=call_id,
            )
        except Exception:
            pass

    unregister_context(call_id)
    return result
