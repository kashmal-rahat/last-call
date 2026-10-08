"""Live WebSocket session handler for Gemini 3.8 Live (Milestone 2B Step 10).

Manages the real-time audio bridge between the browser WebSocket and Gemini Live 3.8:
- Origin validation
- Auth handshake within 5s using short-lived HMAC tokens
- Instance concurrency control via semaphore (MAX_SESSIONS_PER_INSTANCE)
- Start session and batch locking
- Upstream audio streaming (16 kHz PCM)
- Downstream audio playback, transcription, price-guard verification, and latency metrics
- Call wrap-up & timeout timers (MAX_CALL_SECONDS)
- Exception-safe finally cleanups and background call summaries
- Privacy: Never logs transcript text, audio, or secret floor prices
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo
from pydantic import AwareDatetime
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from google.adk import Runner
from google.adk.agents.run_config import RunConfig
from google.adk.runners import LiveRequestQueue
from google.adk.sessions import InMemorySessionService
from google.genai import types

from lastcall_shared.config import get_settings
from lastcall_shared.firestore_store import FirestoreStore
from lastcall_shared.models import CallResult, TranscriptEntry
from lastcall_shared.session_tokens import verify as verify_session_token
from lastcall_shared.store import CallStore
from lastcall_voice.call_context import CallContext, register_context, unregister_context
from lastcall_voice.negotiator.agent import build_negotiator
from lastcall_voice.negotiator import price_guard
from lastcall_voice.negotiator.prompt import price_words

PKT = ZoneInfo("Asia/Karachi")
logger = logging.getLogger("lastcall_voice.live_session")

CUSTOM_VOCABULARY = [
    "aakhri rate",
    "darjan",
    "kilo",
    "Sindhri",
    "sauda",
    "munasib",
    "wara",
    "daam",
    "bhari",
    "bhai",
    "shukriya",
    "rupay",
    "rupaye",
    "maal",
    "khalis",
    "fresh",
    "bachat",
    "rate",
    "discount",
    "offer",
]


def build_input_transcription_config() -> types.AudioTranscriptionConfig:
    """Builds input transcription config with Urdu/Punjabi/English language hints and market vocabulary."""
    try:
        return types.AudioTranscriptionConfig(
            language_hints=types.LanguageHints(language_codes=["ur", "pa", "en"]),
            custom_vocabulary=CUSTOM_VOCABULARY,
        )
    except Exception as exc:
        logger.info("fallback_input_transcription_config", extra={"reason": str(exc)})
        return types.AudioTranscriptionConfig()


# Concurrency semaphore for the instance
_MAX_SESSIONS_DEFAULT = int(os.getenv("MAX_SESSIONS_PER_INSTANCE", "4"))
_INSTANCE_SEMAPHORE = asyncio.Semaphore(_MAX_SESSIONS_DEFAULT)


def get_instance_semaphore() -> asyncio.Semaphore:
    return _INSTANCE_SEMAPHORE


async def run_call_summary(call_id: str, store: CallStore) -> None:
    """Background task to generate a 2-line Flash summary of the call and save to store."""
    try:
        call = await store.get_call(call_id)
        if not call or not call.transcript:
            return

        from google.genai import Client

        settings = get_settings()
        client = Client(
            project=settings.GOOGLE_CLOUD_PROJECT,
            location=settings.GOOGLE_CLOUD_LOCATION,
        )
        transcript_text = "\n".join(f"{t.speaker}: {t.text}" for t in call.transcript)
        prompt = (
            "Summarize this short negotiation phone call in exactly 2 plain sentences in English. "
            "State whether a deal was reached (with price, quantity, and pickup if applicable) or why it ended.\n\n"
            f"Transcript:\n{transcript_text}"
        )
        coro = client.aio.models.generate_content(
            model=settings.GEMINI_FLASH_MODEL,
            contents=prompt,
        )
        resp = await asyncio.wait_for(coro, timeout=5.0)
        summary = resp.text.strip() if resp and resp.text else ""
        if summary and call.result:
            call.result.summary = summary
            await store.finish_call(call_id, call.result)
            logger.info("call_summary_saved", extra={"call_id": call_id})
    except Exception as exc:
        logger.warning("call_summary_failed", extra={"call_id": call_id, "error": str(exc)})


async def handle_live_call_websocket(
    websocket: WebSocket,
    store: CallStore | None = None,
    signing_key: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
    clock: Callable[[], AwareDatetime] | None = None,
    runner_factory: Callable[..., Any] | None = None,
) -> None:
    """Handles the WebSocket connection for a live call."""
    settings = get_settings()
    actual_store: CallStore = store or getattr(websocket.app.state, "store", None) or FirestoreStore()
    app_key = signing_key or os.getenv("APP_SIGNING_KEY", "")
    sem = semaphore or getattr(websocket.app.state, "semaphore", None) or get_instance_semaphore()
    now_fn = clock or (lambda: datetime.now(PKT))
    start_time = time.time()

    max_call_seconds = int(os.getenv("MAX_CALL_SECONDS", "300"))
    agent_voice = os.getenv("AGENT_VOICE", "Puck")
    agent_gender = os.getenv("AGENT_GENDER", "male")

    # 1. Origin verification
    origin = websocket.headers.get("origin")
    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "")
    if allowed_origins_raw:
        allowed = [o.strip() for o in allowed_origins_raw.split(",") if o.strip()]
        if origin not in allowed:
            logger.warning("ws_rejected_origin", extra={"origin": origin})
            await websocket.close(code=4403)
            return

    await websocket.accept()

    # 2. Auth handshake within 5s
    try:
        auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        auth_data = json.loads(auth_raw)
        if not isinstance(auth_data, dict) or auth_data.get("type") != "auth" or not auth_data.get("token"):
            await websocket.close(code=4401)
            return
        token = auth_data["token"]
    except Exception:
        await websocket.close(code=4401)
        return

    valid, payload, err = verify_session_token(token, key=app_key, now=now_fn())
    if not valid or not payload:
        logger.warning("ws_auth_invalid", extra={"err": err})
        await websocket.close(code=4401)
        return

    call_id = payload["call_id"]
    nonce = payload["nonce"]

    # 3. Capacity check (acquire without waiting)
    if sem._value <= 0:
        logger.warning("ws_instance_busy", extra={"call_id": call_id})
        try:
            await websocket.send_json({"type": "busy"})
        except Exception:
            pass
        await websocket.close(code=1013)
        return

    await sem.acquire()
    semaphore_acquired = True

    call = None
    queue = None
    session_service = None
    transcript_buffer: list[TranscriptEntry] = []
    total_input_tokens = 0
    total_output_tokens = 0

    try:
        # 4. Start session and lock batch
        started = await actual_store.start_session(call_id, nonce)
        if not started:
            logger.warning("ws_session_start_rejected", extra={"call_id": call_id})
            await websocket.close(code=4409)
            return

        call = await actual_store.get_call(call_id)
        if not call:
            await websocket.close(code=4404)
            return

        lock_until = now_fn() + timedelta(seconds=max_call_seconds + 60)
        locked = await actual_store.lock_batch(call.batch_id, call_id, lock_until)
        if not locked:
            logger.warning("ws_lock_batch_rejected", extra={"call_id": call_id, "batch_id": call.batch_id})
            await websocket.close(code=4423)
            return

        # Register CallContext
        ctx = CallContext(
            store=actual_store,
            call_id=call_id,
            mode="voice",
            clock=now_fn,
        )
        register_context(ctx)

        # 5. Agent and ADK Session setup
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name="lastcall_voice",
            user_id=call.brief.buyer.buyer_id,
            session_id=call_id,
            state={"call_id": call_id, "mart_id": call.mart_id},
        )

        city_style = os.getenv("CITY_STYLE", "karachi")
        agent = build_negotiator(
            model=settings.GEMINI_LIVE_MODEL,
            view=call.brief.agent_view(),
            mode="voice",
            agent_gender=agent_gender,  # type: ignore[arg-type]
            city_style=city_style,  # type: ignore[arg-type]
            clock=now_fn,
        )

        if runner_factory:
            runner = runner_factory(agent=agent, session_service=session_service)
        else:
            runner = Runner(agent=agent, session_service=session_service, app_name="lastcall_voice")

        queue = LiveRequestQueue()

        run_config = RunConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=agent_voice)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=build_input_transcription_config(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    silence_duration_ms=700,
                    prefix_padding_ms=100,
                )
            ),
            session_resumption=types.SessionResumptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=100000,
                sliding_window=types.SlidingWindow(target_tokens=80000),
            ),
        )

        # 6. Kick-off prompt
        queue.send_content(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text="[SYSTEM] The buyer has answered. Greet, disclose you are an AI, ask for a minute."
                    )
                ],
            )
        )

        # 7. Concurrent processing: Upstream, Downstream, Timer
        last_buyer_turn_end = 0.0
        measuring_latency = False

        async def upstream_task() -> None:
            """Receives audio and control messages from browser client."""
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"]:
                    data = msg["bytes"]
                    queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=data))
                elif "text" in msg and msg["text"]:
                    try:
                        cmd = json.loads(msg["text"])
                        if isinstance(cmd, dict) and cmd.get("type") == "hangup":
                            break
                    except Exception:
                        pass

        async def downstream_task() -> None:
            """Receives live events from Gemini Live 3.8 and sends to browser client."""
            nonlocal last_buyer_turn_end, measuring_latency, total_input_tokens, total_output_tokens
            last_flush_time = time.time()

            async for event in runner.run_live(
                session_id=call_id,
                user_id=call.brief.buyer.buyer_id,
                live_request_queue=queue,
                run_config=run_config,
            ):
                now_curr = time.time()

                # Handle Audio output
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.inline_data and part.inline_data.data:
                            if measuring_latency and last_buyer_turn_end > 0.0:
                                lat_ms = round((now_curr - last_buyer_turn_end) * 1000, 1)
                                logger.info(
                                    "voice_latency_measured",
                                    extra={"call_id": call_id, "latency_ms": lat_ms},
                                )
                                measuring_latency = False

                            if websocket.client_state == WebSocketState.CONNECTED:
                                await websocket.send_bytes(part.inline_data.data)

                # Buyer speech finished
                if event.input_transcription and event.input_transcription.text:
                    is_final = getattr(event.input_transcription, "finished", None)
                    if is_final is not False:
                        buyer_text = event.input_transcription.text
                        ctx.buyer_spoke = True
                        last_buyer_turn_end = time.time()
                        measuring_latency = True

                        entry = TranscriptEntry(
                            speaker="buyer",
                            text=buyer_text,
                            at=now_fn(),
                        )
                        transcript_buffer.append(entry)
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json(
                                {"type": "transcript", "speaker": "buyer", "text": buyer_text}
                            )

                # Agent speech finished
                if event.output_transcription and event.output_transcription.text:
                    is_final = getattr(event.output_transcription, "finished", None)
                    if is_final is not False:
                        agent_text = event.output_transcription.text
                        entry = TranscriptEntry(
                            speaker="agent",
                            text=agent_text,
                            at=now_fn(),
                        )
                        transcript_buffer.append(entry)
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json(
                                {"type": "transcript", "speaker": "agent", "text": agent_text}
                            )

                        # Price guard verification
                        prices = price_guard.find_prices(agent_text)
                        if prices:
                            ladder = call.negotiation.ladder
                            rung = call.negotiation.rung
                            classification = price_guard.classify(
                                prices=prices,
                                floor=call.brief.floor_price_per_unit,
                                approved_prices=call.negotiation.approved_prices,
                                current_price=ladder[rung],
                            )
                            if classification in ("below_floor", "unapproved"):
                                flag_name = (
                                    "floor_correction"
                                    if classification == "below_floor"
                                    else "unapproved_price"
                                )
                                if flag_name not in ctx.flags:
                                    ctx.flags.append(flag_name)
                                correct_str = price_words(ladder[rung], call.brief.opening_price_unit)
                                queue.send_content(
                                    types.Content(
                                        role="user",
                                        parts=[
                                            types.Part.from_text(
                                                text=(
                                                    f"[SYSTEM] You said a wrong price. Correct yourself now: "
                                                    f"the price is {correct_str}."
                                                )
                                            )
                                        ],
                                    )
                                )

                # Interruption
                if getattr(event, "interrupted", False):
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json({"type": "interrupted"})

                # Usage accumulation
                if event.usage_metadata:
                    total_input_tokens += getattr(event.usage_metadata, "prompt_token_count", 0) or 0
                    total_output_tokens += getattr(event.usage_metadata, "candidates_token_count", 0) or 0

                # Periodic transcript flush (every 5 seconds)
                if now_curr - last_flush_time >= 5.0 and transcript_buffer:
                    to_flush = list(transcript_buffer)
                    transcript_buffer.clear()
                    await actual_store.append_transcript(call_id, to_flush)
                    last_flush_time = now_curr

                # Closing upon turn completion
                if event.turn_complete and ctx.closing:
                    logger.info("live_session_closing_turn_complete", extra={"call_id": call_id})
                    break

        async def timer_task() -> None:
            """Handles call wrap-up notice and maximum duration timeout."""
            if max_call_seconds > 30:
                wrap_delay = max_call_seconds - 30
                rem_delay = 30
                await asyncio.sleep(wrap_delay)
                queue.send_content(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(
                                text="[SYSTEM] Time is almost up; confirm or close politely."
                            )
                        ],
                    )
                )
                await asyncio.sleep(rem_delay)
            else:
                await asyncio.sleep(max_call_seconds)

            if "timeout" not in ctx.flags:
                ctx.flags.append("timeout")

        # Run until any task completes
        tasks = [
            asyncio.create_task(upstream_task(), name="upstream"),
            asyncio.create_task(downstream_task(), name="downstream"),
            asyncio.create_task(timer_task(), name="timer"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc:
                logger.error("task_failed", extra={"task": t.get_name(), "error": str(exc)}, exc_info=exc)
            else:
                logger.info("task_completed", extra={"task": t.get_name()})
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    except (WebSocketDisconnect, Exception) as exc:
        logger.info("live_session_interrupted", extra={"call_id": call_id, "error": str(exc)})
    finally:
        # Every cleanup in its own try/except
        if queue:
            try:
                queue.close()
            except Exception:
                pass

        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:
            pass

        if semaphore_acquired:
            try:
                sem.release()
            except Exception:
                pass

        if transcript_buffer and call:
            try:
                await actual_store.append_transcript(call_id, transcript_buffer)
                transcript_buffer.clear()
            except Exception:
                pass

        ctx = None
        try:
            ctx = CallContext.get_context(call_id) if hasattr(CallContext, "get_context") else None
        except Exception:
            pass
        if not ctx:
            from lastcall_voice.call_context import get_context
            ctx = get_context(call_id)

        if call and ctx:
            try:
                if ctx.outcome not in ("deal", "partial_deal"):
                    await actual_store.release_batch(call.batch_id, call_id)
            except Exception:
                pass

            try:
                now_dt = now_fn()
                if ctx.outcome_set and ctx.outcome:
                    final_outcome = ctx.outcome
                elif not ctx.buyer_spoke:
                    final_outcome = "no_answer"
                else:
                    final_outcome = "call_back"
                    target_dt = now_dt + timedelta(hours=2)
                    ch = call.brief.calling_hours
                    t = target_dt.time()
                    if t < ch.start:
                        target_dt = target_dt.replace(
                            hour=ch.start.hour, minute=ch.start.minute, second=0
                        )
                    elif t > ch.end:
                        target_dt = (target_dt + timedelta(days=1)).replace(
                            hour=ch.start.hour, minute=ch.start.minute, second=0
                        )
                    ctx.callback_at = target_dt
                    if "dropped" not in ctx.flags:
                        ctx.flags.append("dropped")

                updated_call = await actual_store.get_call(call_id)
                final_transcript = updated_call.transcript if updated_call else []

                result = CallResult(
                    call_id=call_id,
                    batch_id=call.batch_id,
                    mart_id=call.mart_id,
                    status="completed",
                    deal_type=call.brief.deal_type,
                    outcome=final_outcome,  # type: ignore[arg-type]
                    agreed_price_per_unit=ctx.agreed_price_per_unit,
                    agreed_price_unit=(
                        call.brief.opening_price_unit
                        if ctx.agreed_price_per_unit is not None
                        else None
                    ),
                    currency=call.brief.currency,
                    agreed_quantity=ctx.agreed_quantity,
                    agreed_quantity_unit=(
                        call.brief.quantity_unit if ctx.agreed_quantity is not None else None
                    ),
                    pickup_time=ctx.pickup_time,
                    callback_at=ctx.callback_at,
                    transcript=final_transcript,
                    summary="",
                    flags=list(set(ctx.flags + (updated_call.flags if updated_call else []))),
                )
                await actual_store.finish_call(call_id, result)
            except Exception as exc:
                logger.warning("finish_call_failed", extra={"call_id": call_id, "error": str(exc)})

        if session_service and call:
            try:
                await session_service.delete_session(
                    app_name="lastcall_voice",
                    user_id=call.brief.buyer.buyer_id,
                    session_id=call_id,
                )
            except Exception:
                pass

        try:
            unregister_context(call_id)
        except Exception:
            pass

        # Trigger background summary
        try:
            asyncio.create_task(run_call_summary(call_id, actual_store))
        except Exception:
            pass

        # Log metrics (Never transcript text, audio, or floor price)
        try:
            dur = max(0.0, time.time() - start_time)
            cost_est = (dur / 60.0) * 0.072
            logger.info(
                "call_metrics_logged",
                extra={
                    "call_id": call_id,
                    "duration_sec": round(dur, 1),
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "estimated_cost_usd": round(cost_est, 4),
                    "flags": ctx.flags if ctx else [],
                },
            )
        except Exception:
            pass
