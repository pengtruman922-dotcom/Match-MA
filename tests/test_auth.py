from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.main import create_app


def test_auth_disabled_allows_health_without_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_auth_enabled_requires_token_and_allows_login(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    get_settings.cache_clear()
    client = TestClient(create_app())

    assert client.get("/api/v1/meta/enums").status_code == 401

    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token == "test-token"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"

    get_settings.cache_clear()
