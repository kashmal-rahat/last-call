"""Tests for API demo endpoints (/demo, /demo/scenarios, /demo/sessions) per Step 11 & 13."""

import os
import pytest
from fastapi.testclient import TestClient

from lastcall_api.main import app, _IP_REQUEST_HISTORY
from lastcall_shared.session_tokens import verify
from lastcall_shared.store import InMemoryStore

KEY = "test-signing-key-12345"
CODE = "test-judge-access-code"


@pytest.fixture(autouse=True)
def setup_api_test(monkeypatch):
    monkeypatch.setenv("APP_SIGNING_KEY", KEY)
    monkeypatch.setenv("DEMO_ACCESS_CODE", CODE)
    monkeypatch.setenv("DEMO_DAILY_SESSION_CAP", "5")
    monkeypatch.setenv("VOICE_WS_URL", "wss://voice.example.com/ws/call")
    _IP_REQUEST_HISTORY.clear()
    store = InMemoryStore()
    app.state.store = store
    return store


def test_get_demo_page():
    client = TestClient(app)
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "Last Call" in resp.text
    assert "Gemini 3.8 Live" in resp.text


def test_get_demo_scenarios_auth():
    client = TestClient(app)
    # No access code
    resp1 = client.get("/demo/scenarios")
    assert resp1.status_code == 401

    # Wrong access code
    resp2 = client.get("/demo/scenarios", headers={"X-Demo-Access-Code": "wrong"})
    assert resp2.status_code == 401

    # Valid access code
    resp3 = client.get("/demo/scenarios", headers={"X-Demo-Access-Code": CODE})
    assert resp3.status_code == 200
    data = resp3.json()
    assert "scenarios" in data
    assert len(data["scenarios"]) == 5
    # Scenarios contain floor price for tester
    assert any("floor_price_per_unit" in s for s in data["scenarios"])


def test_post_demo_sessions_success():
    client = TestClient(app)
    # Valid request
    resp = client.post(
        "/demo/sessions",
        headers={"X-Demo-Access-Code": CODE},
        json={"scenario_id": "easy_yes"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "call_id" in data
    assert data["ws_url"] == "wss://voice.example.com/ws/call"
    assert "token" in data

    # Verify minted token
    valid, payload, err = verify(data["token"], key=KEY)
    assert valid is True
    assert payload["call_id"] == data["call_id"]


def test_post_demo_sessions_ip_rate_limit():
    client = TestClient(app)
    headers = {"X-Demo-Access-Code": CODE, "X-Forwarded-For": "203.0.113.195"}

    # 5 allowed sessions
    for _ in range(5):
        r = client.post("/demo/sessions", headers=headers, json={"scenario_id": "easy_yes"})
        assert r.status_code == 200

    # 6th request from same IP is rate limited
    r_blocked = client.post("/demo/sessions", headers=headers, json={"scenario_id": "easy_yes"})
    assert r_blocked.status_code == 429
    assert "Hourly IP limit reached" in r_blocked.json()["detail"]


def test_post_demo_sessions_daily_cap(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_SESSION_CAP", "1")
    client = TestClient(app)

    # 1st session succeeds
    r1 = client.post(
        "/demo/sessions",
        headers={"X-Demo-Access-Code": CODE, "X-Forwarded-For": "10.0.0.1"},
        json={"scenario_id": "easy_yes"},
    )
    assert r1.status_code == 200

    # 2nd session hits daily cap (different IP to avoid IP limiter)
    r2 = client.post(
        "/demo/sessions",
        headers={"X-Demo-Access-Code": CODE, "X-Forwarded-For": "10.0.0.2"},
        json={"scenario_id": "easy_yes"},
    )
    assert r2.status_code == 429
    assert "Daily demo session cap reached" in r2.json()["detail"]
