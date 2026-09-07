"""API key 管理：签发、列表、停用。仅管理员。

明文 key 只在 ``POST /api-keys`` 的响应里出现一次。列表接口只回前缀。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.api_keys import (
    KNOWN_SCOPES,
    SCOPE_AGENT_READ,
    generate_api_key,
    normalize_scopes,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: [SCOPE_AGENT_READ])


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    created_by_name: str | None = None
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None


class ApiKeyCreatedOut(ApiKeyOut):
    # 只在这里出现一次。列表接口拿不到它。
    api_key: str


_SELECT = """
    select
      k.id, k.name, k.key_prefix, k.scopes,
      (select au.name from app_user au where au.id = k.created_by) as created_by_name,
      k.created_at::text as created_at,
      k.last_used_at::text as last_used_at,
      k.revoked_at::text as revoked_at
    from api_key k
"""


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(current_user: CurrentUser, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    require_admin(current_user)
    rows = (
        db.execute(
            text(
                _SELECT
                + """
            where k.team_id = :team_id and k.workspace_id = :workspace_id
            order by k.revoked_at is not null, k.created_at desc
            """
            ),
            {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


@router.get("/scopes", response_model=list[str])
def list_api_key_scopes(current_user: CurrentUser) -> list[str]:
    require_admin(current_user)
    return sorted(KNOWN_SCOPES)


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreate, current_user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_admin(current_user)
    try:
        scopes = normalize_scopes(payload.scopes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    plaintext, prefix, key_hash = generate_api_key()
    row = (
        db.execute(
            text(
                """
            insert into api_key (
              team_id, workspace_id, name, key_prefix, key_hash, scopes, created_by
            )
            values (:team_id, :workspace_id, :name, :key_prefix, :key_hash, :scopes, :created_by)
            returning id
            """
            ).bindparams(bindparam("scopes", type_=JSONB)),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "name": payload.name.strip(),
                "key_prefix": prefix,
                "key_hash": key_hash,
                "scopes": scopes,
                "created_by": current_user.user_id,
            },
        )
        .mappings()
        .one()
    )
    db.commit()
    created = db.execute(text(_SELECT + " where k.id = :id"), {"id": row["id"]}).mappings().one()
    return {**dict(created), "api_key": plaintext}


@router.post("/{api_key_id}/revoke", response_model=ApiKeyOut)
def revoke_api_key(
    api_key_id: UUID, current_user: CurrentUser, db: Session = Depends(get_db)
) -> dict[str, Any]:
    require_admin(current_user)
    updated = (
        db.execute(
            text(
                """
            update api_key
            set revoked_at = coalesce(revoked_at, now()),
                revoked_by = coalesce(revoked_by, :revoked_by)
            where id = :id and team_id = :team_id and workspace_id = :workspace_id
            returning id
            """
            ),
            {
                "id": api_key_id,
                "revoked_by": current_user.user_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        )
        .mappings()
        .one_or_none()
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    db.commit()
    row = db.execute(text(_SELECT + " where k.id = :id"), {"id": api_key_id}).mappings().one()
    return dict(row)
