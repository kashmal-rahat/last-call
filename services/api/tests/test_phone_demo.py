"""Phone demo (Module 9): /demo/phone/* is off unless switched on, and only ever rings the configured SIM."""

import asyncio
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from lastcall_api.main import app, _IP_REQUEST_HISTORY
from lastcall_api.phone_demo import PhoneDemoConfig
from lastcall_shared.config import get_settings
from lastcall_shared.scenarios.loader import build_call
from lastcall_shared.session_tokens import mint
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345-at-least-32-chars-long"
CODE = "test-judge-access-code"
PKT = ZoneInfo("Asia/Karachi")
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=PKT)
TO_NUMBER = "+923001234567"  # fictional
CONFIG = {
    "account_sid": "AC" + "0" * 32,
    "api_key_sid": "SK" + "1" * 32,
    "api_key_secret": "test-secret",
    "from_number": "+15550001111",
    "to_number": TO_NUMBER,
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    monkeypatch.setenv("VOICE_WS_URL", "wss://voice.example.com/ws/call")
    monkeypatch.setenv("PHONE_DEMO_CONFIG", json.dumps(CONFIG))
    monkeypatch.setenv("PHONE_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    _IP_REQUEST_HISTORY.clear()
    store = InMemoryStore()
    app.state.store = store
    dialed: list[tuple[PhoneDemoConfig, str]] = []

    async def fake_dialer(cfg: PhoneDemoConfig, twiml: str) -> None:
        dialed.append((cfg, twiml))

    app.state.phone_dialer = fake_dialer
    yield store, dialed
    del app.state.phone_dialer
    get_settings.cache_clear()


def _new_call(store: InMemoryStore):
    call, batch = build_call("easy_yes", now=NOW)
    call = call.model_copy(update={"call_id": f"call_{uuid.uuid4().hex}"})
    asyncio.run(store.create_call(call, batch))
    token = mint(call_id=call.call_id, nonce=call.session_nonce, key=KEY)
    return call, token


def _dial(client, call_id, token, code=CODE):
    return client.post(
        "/demo/phone/dial",
        json={"call_id": call_id, "token": token},
        headers={"X-Demo-Access-Code": code} if code else {},
    )


def test_everything_is_404_when_switched_off(monkeypatch, setup):
    store, dialed = setup
    monkeypatch.setenv("PHONE_DEMO_ENABLED", "false")
    get_settings.cache_clear()
    call, token = _new_call(store)
    client = TestClient(app)
    assert client.get("/demo/phone/config").status_code == 404
    assert _dial(client, call.call_id, token).status_code == 404
    assert client.get(f"/demo/phone/calls/{call.call_id}", headers={"X-Demo-Access-Code": CODE}).status_code == 404
    assert dialed == []


def test_dial_rings_the_configured_number_with_the_call_token(setup):
    store, dialed = setup
    call, token = _new_call(store)
    client = TestClient(app)
    assert client.get("/demo/phone/config").json() == {"enabled": True}

    resp = _dial(client, call.call_id, token)
    assert resp.status_code == 200
    assert TO_NUMBER[1:] not in resp.text  # the number never leaves the server

    cfg, twiml = dialed[0]
    assert cfg.to_number == TO_NUMBER
    assert 'url="wss://voice.example.com/phone/stream"' in twiml
    assert f'<Parameter name="token" value="{token}"/>' in twiml
    assert "phone_demo" in asyncio.run(store.get_call(call.call_id)).flags


@pytest.mark.parametrize(
    "case, expected",
    [("no_code", 401), ("bad_call_id", 400), ("bad_token", 403), ("other_calls_token", 403), ("started", 409)],
)
def test_dial_refusals(setup, case, expected):
    store, dialed = setup
    call, token = _new_call(store)
    client = TestClient(app)
    call_id, code = call.call_id, CODE
    if case == "no_code":
        code = None
    elif case == "bad_call_id":
        call_id = "call_NOT-VALID"
    elif case == "bad_token":
        token = "bad.token"
    elif case == "other_calls_token":
        _, token = _new_call(store)
    elif case == "started":
        asyncio.run(store.start_session(call.call_id, call.session_nonce))
    assert _dial(client, call_id, token, code=code).status_code == expected
    assert dialed == []


def test_dial_reports_config_and_twilio_failures(monkeypatch, setup):
    store, _ = setup
    call, token = _new_call(store)
    client = TestClient(app)

    monkeypatch.setenv("PHONE_DEMO_CONFIG", json.dumps({**CONFIG, "to_number": "0300 1234567"}))
    get_settings.cache_clear()
    assert _dial(client, call.call_id, token).status_code == 503

    monkeypatch.setenv("PHONE_DEMO_CONFIG", json.dumps(CONFIG))
    get_settings.cache_clear()

    async def failing_dialer(cfg, twiml):
        raise RuntimeError("Twilio returned HTTP 400")

    app.state.phone_dialer = failing_dialer
    resp = _dial(client, call.call_id, token)
    assert resp.status_code == 502
    assert "phone_demo" not in asyncio.run(store.get_call(call.call_id)).flags


def test_call_status_returns_lines_in_order(setup):
    store, _ = setup
    call, _ = _new_call(store)
    asyncio.run(store.append_live_line(call.call_id, {"i": 1, "speaker": "buyer", "text": "jee"}))
    asyncio.run(store.append_live_line(call.call_id, {"i": 0, "speaker": "agent", "text": "salaam"}))
    client = TestClient(app)
    assert client.get(f"/demo/phone/calls/{call.call_id}").status_code == 401
    resp = client.get(f"/demo/phone/calls/{call.call_id}", headers={"X-Demo-Access-Code": CODE})
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "pending",
        "lines": [
            {"i": 0, "speaker": "agent", "text": "salaam"},
            {"i": 1, "speaker": "buyer", "text": "jee"},
        ],
    }


def test_config_errors_never_echo_numbers_or_secrets(monkeypatch, setup, caplog):
    store, _ = setup
    call, token = _new_call(store)
    bad = {**CONFIG, "to_number": "923001234567", "api_key_secret": "very-secret-value", "extra": 1}
    monkeypatch.setenv("PHONE_DEMO_CONFIG", json.dumps(bad))
    get_settings.cache_clear()
    resp = _dial(TestClient(app), call.call_id, token)
    assert resp.status_code == 503
    errors = " ".join(str(getattr(r, "error", "")) for r in caplog.records)
    logged = caplog.text + errors + resp.text
    assert "923001234567" not in logged and "very-secret-value" not in logged
    assert "to_number" in errors and "extra" in errors  # field names are enough to fix it
