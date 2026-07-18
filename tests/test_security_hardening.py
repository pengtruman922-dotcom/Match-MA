import pytest
from fastapi.testclient import TestClient

from backend.app.api.routes import auth as auth_routes
from backend.app.config import Settings, get_settings
from backend.app.main import create_app, enforce_startup_auth_security

AUTH_ENV_VARS = [
    "AUTH_ENABLED",
    "AUTH_STRICT",
    "APP_ENV",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "ADMIN_TOKEN",
    "MATCH_MA_ADMIN_TOKEN",
    "MATCH_MA_ACCESS_TOKEN",
    "AUTH_JWT_SECRET",
    "MATCH_MA_AUTH_JWT_SECRET",
]


@pytest.fixture(autouse=True)
def _clean_auth_state(monkeypatch):
    for name in AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    auth_routes._failed_logins.clear()
    auth_routes._lockouts.clear()
    yield
    get_settings.cache_clear()
    auth_routes._failed_logins.clear()
    auth_routes._lockouts.clear()


def test_default_settings_report_all_auth_warnings() -> None:
    warnings = Settings(_env_file=None).auth_security_warnings

    assert len(warnings) == 4
    joined = "\n".join(warnings)
    assert "AUTH_ENABLED" in joined
    assert "ADMIN_PASSWORD" in joined
    assert "ADMIN_TOKEN" in joined
    assert "AUTH_JWT_SECRET" in joined


def test_fully_configured_settings_report_no_warnings() -> None:
    settings = Settings(
        _env_file=None,
        auth_enabled=True,
        admin_password="a-real-password",
        admin_token="a-real-token",
        auth_jwt_secret="a-real-secret",
    )

    assert settings.auth_security_warnings == []


def test_strict_mode_refuses_start_with_warnings() -> None:
    strict = Settings(_env_file=None, auth_strict=True)
    lenient = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="insecure auth configuration"):
        enforce_startup_auth_security(strict)
    enforce_startup_auth_security(lenient)


def test_production_app_env_implies_strict() -> None:
    assert Settings(_env_file=None, app_env="production").auth_strict_effective is True
    assert Settings(_env_file=None, app_env="staging").auth_strict_effective is False


def test_secure_settings_start_in_strict_mode() -> None:
    settings = Settings(
        _env_file=None,
        auth_strict=True,
        auth_enabled=True,
        admin_password="a-real-password",
        admin_token="a-real-token",
        auth_jwt_secret="a-real-secret",
    )

    enforce_startup_auth_security(settings)


def _login_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret")
    get_settings.cache_clear()
    return TestClient(create_app())


def test_login_locks_out_after_repeated_failures(monkeypatch) -> None:
    client = _login_client(monkeypatch)

    for _ in range(auth_routes.FAILED_LOGIN_LIMIT):
        response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    locked = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert locked.status_code == 429


def test_successful_login_resets_failure_counter(monkeypatch) -> None:
    client = _login_client(monkeypatch)

    for _ in range(auth_routes.FAILED_LOGIN_LIMIT - 1):
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401

    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert ok.status_code == 200

    # Counter reset: the next failure starts a fresh window instead of locking.
    retry = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert retry.status_code == 401


def test_lockout_is_per_username(monkeypatch) -> None:
    client = _login_client(monkeypatch)

    for _ in range(auth_routes.FAILED_LOGIN_LIMIT):
        client.post("/api/v1/auth/login", json={"username": "someone-else", "password": "wrong"})

    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "secret"})
    assert ok.status_code == 200
