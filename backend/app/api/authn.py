"""Request-scoped auth context: who is calling, and role gates for routes."""

import time
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text

from backend.app.constants import DEFAULT_ADMIN_USER_ID
from backend.app.db import get_session_factory


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    role: str
    name: str
    username: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


ADMIN_CONTEXT = AuthContext(
    user_id=DEFAULT_ADMIN_USER_ID,
    role="admin",
    name="系统管理员",
    username="admin",
)

_USER_CACHE_TTL_SECONDS = 60
_user_context_cache: dict[str, tuple[float, AuthContext | None]] = {}


def resolve_user_context(token_payload: dict[str, Any]) -> AuthContext | None:
    """Resolve a verified token payload to an active app_user.

    Role and status come from the database (with a short cache) so that
    disabling an account or changing its role takes effect without waiting
    for the token to expire.
    """
    user_id_text = str(token_payload.get("sub") or "")
    try:
        user_id = UUID(user_id_text)
    except ValueError:
        return None

    cached = _user_context_cache.get(user_id_text)
    now = time.monotonic()
    if cached and now - cached[0] < _USER_CACHE_TTL_SECONDS:
        return cached[1]

    with get_session_factory()() as db:
        row = (
            db.execute(
                text(
                    """
                    select id, name, username, role, status
                    from app_user
                    where id = :user_id
                    """
                ),
                {"user_id": user_id},
            )
            .mappings()
            .first()
        )

    context: AuthContext | None = None
    if row and row["status"] == "active":
        context = AuthContext(
            user_id=row["id"],
            role=row["role"],
            name=row["name"],
            username=row["username"],
        )
    _user_context_cache[user_id_text] = (now, context)
    return context


def invalidate_user_context_cache(user_id: UUID | str | None = None) -> None:
    if user_id is None:
        _user_context_cache.clear()
    else:
        _user_context_cache.pop(str(user_id), None)


def get_auth_context(request: Request) -> AuthContext:
    context = getattr(request.state, "auth", None)
    if isinstance(context, AuthContext):
        return context
    # Auth disabled (local development): behave as the seed admin.
    return ADMIN_CONTEXT


CurrentUser = Annotated[AuthContext, Depends(get_auth_context)]


def require_admin(context: AuthContext) -> None:
    if not context.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可执行此操作。")
