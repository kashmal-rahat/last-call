"""Health endpoint tests for Last Call Voice service."""

from fastapi.testclient import TestClient

from lastcall_voice.main import app


def test_voice_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "voice"
    assert data["status"] == "healthy"
