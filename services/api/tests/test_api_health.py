"""Health endpoint tests for Last Call API service."""

from fastapi.testclient import TestClient
from lastcall_api.main import app


def test_api_health():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "api"
    assert data["status"] == "healthy"
