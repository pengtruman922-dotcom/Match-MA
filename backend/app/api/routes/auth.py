from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.app.api.authn import CurrentUser
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID
from backend.app.db import engine_is_configured, get_session_factory
from backend.app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory failed-login throttle (single API instance). After
# FAILED_LOGIN_LIMIT failures for the same username within the window, the
# username is locked out for LOCKOUT_SECONDS.
FAILED_LOGIN_LIMIT = 5
FAILED_LOGIN_WINDOW_SECONDS = 300
LOCKOUT_SECONDS = 300
_failed_logins: dict[str, list[float]] = {}
_lockouts: dict[str, float] = {}


def _throttle_key(username: str) -> str:
    return username.strip().lower()


def _check_login_throttle(username: str) -> None:
    if _lockouts.get(_throttle_key(username), 0.0) > time.time():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts; try again later.",
        )


def _record_login_failure(username: str) -> None:
    key = _throttle_key(username)
    now = time.time()
    attempts = [t for t in _failed_logins.get(key, []) if now - t < FAILED_LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    if len(attempts) >= FAILED_LOGIN_LIMIT:
        _lockouts[key] = now + LOCKOUT_SECONDS
        _failed_logins.pop(key, None)
    else:
        _failed_logins[key] = attempts


def _clear_login_failures(username: str) -> None:
    key = _throttle_key(username)
    _failed_logins.pop(key, None)
    _lockouts.pop(key, None)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthUserOut(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str
    auth_enabled: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserOut


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> dict[str, object]:
    settings = get_settings()
    _check_login_throttle(payload.username)

    # Legacy shared admin credentials stay valid and map to the seed admin
    # account; this doubles as the recovery path if account passwords break.
    # This path must not touch the database.
    if secrets.compare_digest(payload.username, settings.admin_username) and secrets.compare_digest(
        payload.password, settings.admin_password
    ):
        _clear_login_failures(payload.username)
        return {
            "access_token": settings.effective_admin_token,
            "token_type": "bearer",
            "user": _seed_admin_user(),
        }

    if not engine_is_configured():
        _record_login_failure(payload.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    with get_session_factory()() as db:
        row = (
            db.execute(
                text(
                    """
                    select id, name, username, role, status, password_hash
                    from app_user
                    where lower(username) = lower(:username)
                    """
                ),
                {"username": payload.username},
            )
            .mappings()
            .first()
        )
    if (
        not row
        or row["status"] != "active"
        or not row["password_hash"]
        or not verify_password(payload.password, row["password_hash"])
    ):
        _record_login_failure(payload.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    _clear_login_failures(payload.username)
    token = create_access_token(
        secret=settings.effective_auth_jwt_secret,
        user_id=str(row["id"]),
        role=row["role"],
        name=row["name"],
        expires_in_seconds=settings.auth_token_ttl_seconds,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "user_id": str(row["id"]),
            "username": row["username"],
            "display_name": row["name"],
            "role": row["role"],
            "auth_enabled": settings.auth_enabled,
        },
    }


@router.get("/me", response_model=AuthUserOut)
def me(current_user: CurrentUser) -> dict[str, object]:
    settings = get_settings()
    return {
        "user_id": str(current_user.user_id),
        "username": current_user.username or "",
        "display_name": current_user.name,
        "role": current_user.role,
        "auth_enabled": settings.auth_enabled,
    }


def _seed_admin_user() -> dict[str, object]:
    settings = get_settings()
    return {
        "user_id": str(DEFAULT_ADMIN_USER_ID),
        "username": settings.admin_username,
        "display_name": "系统管理员",
        "role": "admin",
        "auth_enabled": settings.auth_enabled,
    }
