"""Tests for live voice WebSocket endpoint (/ws/call) per Step 10 & 13."""

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lastcall_shared.models import CallRecord
from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import InMemoryStore
from lastcall_voice.live_session import get_instance_semaphore
from lastcall_voice.main import app

from lastcall_shared.config import get_settings

PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 7, 14, 0, 0, tzinfo=PKT)
KEY = "test-secret-key-12345-at-least-32-chars-long"


@pytest.fixture(autouse=True)
def setup_test_app(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    get_settings.cache_clear()
    store = InMemoryStore()
    app.state.store = store
    app.state.signing_key = KEY
    app.state.semaphore = asyncio.Semaphore(4)
    return store


def test_ws_bad_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://trusted.example.com")
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/call", headers={"origin": "https://attacker.example.com"}):
            pass
    assert exc_info.value.code == 4403


def test_ws_no_auth():
    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_text("not-json")
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4401


def test_ws_bad_token():
    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": "bad.token.signature"})
        msg = ws.receive()
        assert msg["type"] == "websocket.close"
        assert msg["code"] == 4401


def test_ws_busy_and_retry(monkeypatch):
    store = app.state.store
    call, batch = build_call("easy_yes", now=NOW)
    asyncio.run(store.create_call(call, batch))

    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    # Simulate full capacity by setting semaphore to 0
    test_sem = asyncio.Semaphore(0)
    app.state.semaphore = test_sem

    client = TestClient(app)
    # 1. First attempt when busy
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg == {"type": "busy"}
        close_msg = ws.receive()
        assert close_msg["type"] == "websocket.close"
        assert close_msg["code"] == 1013

    # Check store: call is still pending, nonce not consumed!
    fetched = asyncio.run(store.get_call(call.call_id))
    assert fetched.status == "pending"

    # 2. Release capacity and retry with the SAME token
    app.state.semaphore = asyncio.Semaphore(1)

    # Use a dummy runner so we don't call external Vertex in this unit test
    class DummyRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            yield type(
                "DummyEvent",
                (),
                {
                    "content": None,
                    "input_transcription": None,
                    "output_transcription": None,
                    "turn_complete": True,
                    "interrupted": False,
                    "usage_metadata": None,
                },
            )()

    from lastcall_voice import live_session
    monkeypatch.setattr(live_session, "Runner", DummyRunner)

    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.send_json({"type": "hangup"})

    # Now the call session was started and finished
    updated = asyncio.run(store.get_call(call.call_id))
    assert updated.status == "completed"

    # 3. Reusing the same token now yields 4409
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        close_msg = ws.receive()
        assert close_msg["type"] == "websocket.close"
        assert close_msg["code"] == 4409


def test_ws_finally_runs_on_exception(monkeypatch):
    store = app.state.store
    call, batch = build_call("hard_bargainer", now=NOW)
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    class FailingRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            raise RuntimeError("Downstream Live session exploded!")
            yield None

    from lastcall_voice import live_session
    monkeypatch.setattr(live_session, "Runner", FailingRunner)

    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        # Runner raises, websocket closes, finally runs
        ws.receive()

    # Verify finally executed: call completed, batch released (since no deal)
    updated_call = asyncio.run(store.get_call(call.call_id))
    assert updated_call.status == "completed"
    updated_batch = asyncio.run(store.get_batch(batch.batch_id))
    assert updated_batch.locked_by_call is None


def test_ws_timeout_and_flags(monkeypatch):
    store = app.state.store
    call, batch = build_call("quality_sceptic", now=NOW)
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    # Set MAX_CALL_SECONDS small for test
    monkeypatch.setenv("MAX_CALL_SECONDS", "1")

    sent_system_notices = []

    class MockQueue:
        def __init__(self):
            pass

        def send_content(self, content):
            for part in content.parts:
                sent_system_notices.append(part.text)

        def send_realtime(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class HangingRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            # Hang until timeout cancels
            await asyncio.sleep(10)
            yield None

    from lastcall_voice import live_session
    monkeypatch.setattr(live_session, "Runner", HangingRunner)
    monkeypatch.setattr(live_session, "LiveRequestQueue", MockQueue)

    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive()

    updated = asyncio.run(store.get_call(call.call_id))
    assert updated.status == "completed"
    assert "timeout" in updated.result.flags


def test_ws_privacy_logging(caplog, monkeypatch):
    store = app.state.store
    call, batch = build_call("easy_yes", now=NOW)
    floor_price = call.brief.floor_price_per_unit  # Secret floor price
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    secret_buyer_utterance = "SECRET_BUYER_TEXT_DO_NOT_LOG"
    secret_agent_utterance = "SECRET_AGENT_REPLY_DO_NOT_LOG"

    class MockLiveRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            # Buyer spoke event
            yield type(
                "Ev1",
                (),
                {
                    "content": None,
                    "input_transcription": type("IT", (), {"text": secret_buyer_utterance})(),
                    "output_transcription": None,
                    "turn_complete": False,
                    "interrupted": False,
                    "usage_metadata": None,
                },
            )()
            # Agent replied event
            yield type(
                "Ev2",
                (),
                {
                    "content": None,
                    "input_transcription": None,
                    "output_transcription": type("OT", (), {"text": secret_agent_utterance})(),
                    "turn_complete": True,
                    "interrupted": False,
                    "usage_metadata": None,
                },
            )()

    from lastcall_voice import live_session
    monkeypatch.setattr(live_session, "Runner", MockLiveRunner)

    caplog.clear()
    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.send_json({"type": "hangup"})

    # Inspect all logs produced
    log_text = caplog.text
    assert secret_buyer_utterance not in log_text
    assert secret_agent_utterance not in log_text
    assert f"floor={floor_price}" not in log_text
    assert f"floor_price={floor_price}" not in log_text


def test_ws_transcription_entries_saved(monkeypatch):
    store = app.state.store
    call, batch = build_call("easy_yes", now=NOW)
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    class MockLiveRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            yield type(
                "Ev1",
                (),
                {
                    "content": None,
                    "input_transcription": type("IT", (), {"text": "Aam kitnay kay hain?"})(),
                    "output_transcription": None,
                    "turn_complete": False,
                    "interrupted": False,
                    "usage_metadata": None,
                },
            )()
            yield type(
                "Ev2",
                (),
                {
                    "content": None,
                    "input_transcription": None,
                    "output_transcription": type("OT", (), {"text": "Assalam-o-Alaikum, 150 rupay."})(),
                    "turn_complete": True,
                    "interrupted": False,
                    "usage_metadata": None,
                },
            )()

    from lastcall_voice import live_session
    monkeypatch.setattr(live_session, "Runner", MockLiveRunner)

    client = TestClient(app)
    with client.websocket_connect("/ws/call") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg1 = ws.receive_json()
        assert msg1 == {"type": "transcript", "speaker": "buyer", "text": "Aam kitnay kay hain?"}
        msg2 = ws.receive_json()
        assert msg2 == {"type": "transcript", "speaker": "agent", "text": "Assalam-o-Alaikum, 150 rupay."}
        ws.send_json({"type": "hangup"})

    updated = asyncio.run(store.get_call(call.call_id))
    assert len(updated.transcript) == 2
    assert updated.transcript[0].speaker == "buyer"
    assert updated.transcript[0].text == "Aam kitnay kay hain?"
    assert updated.transcript[1].speaker == "agent"

