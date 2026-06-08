from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class AuthUserOut(BaseModel):
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
    if not (
        secrets.compare_digest(payload.username, settings.admin_username)
        and secrets.compare_digest(payload.password, settings.admin_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")

    return {
        "access_token": settings.effective_admin_token,
        "token_type": "bearer",
        "user": _admin_user(),
    }


@router.get("/me", response_model=AuthUserOut)
def me() -> dict[str, object]:
    return _admin_user()


def _admin_user() -> dict[str, object]:
    settings = get_settings()
    return {
        "username": settings.admin_username,
        "display_name": "Match-MA Admin",
        "role": "admin",
        "auth_enabled": settings.auth_enabled,
    }
