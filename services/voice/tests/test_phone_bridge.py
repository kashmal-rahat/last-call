"""Phone demo (Module 9): telephone audio conversion and the Twilio Media Stream bridge."""

import asyncio
import base64
import json
from array import array
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from lastcall_shared.config import get_settings
from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import InMemoryStore
from lastcall_voice.main import app
from lastcall_voice.phone.audio import InboundConverter, OutboundConverter, _DECODE, _ENCODE
from lastcall_voice.phone.bridge import TwilioStreamAdapter

PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=PKT)
KEY = "test-secret-key-12345-at-least-32-chars-long"


# --- Audio -------------------------------------------------------------------------


def test_mulaw_round_trip_stays_close():
    for sample in (-32000, -8000, -1000, -100, 0, 100, 1000, 8000, 32000):
        back = _DECODE[_ENCODE[sample + 32768]]
        assert abs(back - sample) <= max(16, abs(sample) * 0.07)
    assert _ENCODE[32768] == 0xFF  # silence is 0xFF in mu-law


def test_inbound_doubles_the_rate():
    conv = InboundConverter()
    pcm = conv.convert(bytes([0xFF] * 160))  # one 20 ms Twilio frame
    assert len(pcm) == 160 * 2 * 2  # 320 samples at 16 kHz, 2 bytes each


def test_outbound_thirds_the_rate_and_carries_leftovers():
    conv = OutboundConverter()
    tone = array("h", [1000, 1000, 1000] * 100).tobytes()  # 300 samples at 24 kHz
    assert len(conv.convert(tone[:301])) == 50  # odd split: the rest is carried over
    assert len(conv.convert(tone[301:])) == 50
    out = conv.convert(array("h", [3000, 3000, 3000]).tobytes())
    assert abs(_DECODE[out[0]] - 3000) < 150


# --- Adapter on its own ------------------------------------------------------------


class FakeTwilioSocket:
    def __init__(self, incoming: list[dict]):
        self.incoming = [json.dumps(m) for m in incoming]
        self.sent: list[dict] = []
        self.client_state = WebSocketState.CONNECTED
        self.app = None
        self.headers: dict[str, str] = {}

    async def receive_text(self) -> str:
        if not self.incoming:
            raise WebSocketDisconnect(code=1000)
        return self.incoming.pop(0)

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.client_state = WebSocketState.DISCONNECTED


def _start(token: str) -> dict:
    return {"event": "start", "start": {"streamSid": "MZ1", "customParameters": {"token": token}}}


async def test_adapter_handshake_audio_and_lines():
    store = InMemoryStore()
    call, batch = build_call("easy_yes", now=NOW)
    await store.create_call(call, batch)
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)
    media = {"event": "media", "media": {"payload": base64.b64encode(bytes([0xFF] * 160)).decode()}}
    ws = FakeTwilioSocket([{"event": "connected"}, _start(token), media, {"event": "stop"}])
    adapter = TwilioStreamAdapter(ws, store=store, signing_key=KEY)

    assert json.loads(await adapter.receive_text()) == {"type": "auth", "token": token}
    msg = await adapter.receive()
    assert msg["type"] == "websocket.receive" and len(msg["bytes"]) == 640
    assert (await adapter.receive())["type"] == "websocket.disconnect"

    await adapter.send_bytes(bytes(4800))  # 100 ms of agent audio at 24 kHz
    assert ws.sent[-1]["event"] == "media" and ws.sent[-1]["streamSid"] == "MZ1"
    assert len(base64.b64decode(ws.sent[-1]["media"]["payload"])) == 800

    await adapter.send_json({"type": "interrupted"})
    assert ws.sent[-1] == {"event": "clear", "streamSid": "MZ1"}

    await adapter.send_json({"type": "transcript", "speaker": "agent", "text": "salaam"})
    await adapter.send_json({"type": "transcript", "speaker": "buyer", "text": "jee"})
    await adapter.close()  # Twilio already hung up: no mark wait, lines drained
    assert await store.get_live_lines(call.call_id) == [
        {"i": 0, "speaker": "agent", "text": "salaam"},
        {"i": 1, "speaker": "buyer", "text": "jee"},
    ]


async def test_adapter_ignores_lines_for_an_invalid_token():
    store = InMemoryStore()
    ws = FakeTwilioSocket([_start("bad.token")])
    adapter = TwilioStreamAdapter(ws, store=store, signing_key=KEY)
    await adapter.receive_text()
    await adapter.send_json({"type": "transcript", "speaker": "agent", "text": "x"})
    await adapter.close()
    assert store.live_lines == {}


# --- Through the real handler ------------------------------------------------------


@pytest.fixture
def voice_app(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://demo.example.com")
    get_settings.cache_clear()
    store = InMemoryStore()
    app.state.store = store
    app.state.semaphore = asyncio.Semaphore(4)
    yield store
    get_settings.cache_clear()


def test_stream_is_closed_when_switched_off(voice_app, monkeypatch):
    monkeypatch.delenv("PHONE_DEMO_ENABLED", raising=False)
    get_settings.cache_clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/phone/stream"):
            pass
    assert exc.value.code == 4404


def test_phone_call_runs_through_the_unchanged_handler(voice_app, monkeypatch):
    monkeypatch.setenv("PHONE_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    store = voice_app
    call, batch = build_call("easy_yes", now=NOW)
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)

    class Part:
        def __init__(self, data):
            self.inline_data = type("Blob", (), {"data": data})()

    class Event:
        def __init__(self, audio=None, agent_text=None):
            self.content = type("Content", (), {"parts": [Part(audio)]})() if audio else None
            self.input_transcription = None
            self.output_transcription = (
                type("T", (), {"text": agent_text, "finished": True})() if agent_text else None
            )
            self.turn_complete = False
            self.interrupted = False
            self.usage_metadata = None

    class DummyRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run_live(self, *args, **kwargs):
            yield Event(audio=bytes(4800))
            yield Event(agent_text="Assalam o alaikum")
            await asyncio.sleep(30)  # stay on the line until the buyer hangs up

    from lastcall_voice import live_session

    monkeypatch.setattr(live_session, "Runner", DummyRunner)

    with TestClient(app).websocket_connect("/phone/stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(_start(token))
        media = ws.receive_json()
        assert media["event"] == "media" and media["streamSid"] == "MZ1"
        ws.send_json({"event": "media", "media": {"payload": base64.b64encode(bytes([0xFF] * 160)).decode()}})
        ws.send_json({"event": "stop"})  # buyer hangs up
        mark = ws.receive_json()  # bridge waits for the goodbye audio to finish
        assert mark == {"event": "mark", "streamSid": "MZ1", "mark": {"name": "end"}}
        ws.send_json({"event": "mark", "streamSid": "MZ1", "mark": {"name": "end"}})

    finished = asyncio.run(store.get_call(call.call_id))
    assert finished.status == "completed"
    assert asyncio.run(store.get_live_lines(call.call_id)) == [
        {"i": 0, "speaker": "agent", "text": "Assalam o alaikum"}
    ]


def test_browser_route_still_checks_origin(voice_app, monkeypatch):
    """The phone demo turns the origin check off only for /phone/stream."""
    monkeypatch.setenv("PHONE_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/ws/call", headers={"origin": "https://attacker.example.com"}):
            pass
    assert exc.value.code == 4403
