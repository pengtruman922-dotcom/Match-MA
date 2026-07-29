import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, invalidate_user_context_cache, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.db import get_db
from backend.app.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{2,50}$")


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=200)
    role: Literal["admin", "consultant"] = "consultant"


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["admin", "consultant"] | None = None
    status: Literal["active", "disabled"] | None = None


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=200)


class UserOut(BaseModel):
    id: UUID
    username: str | None
    name: str
    role: str
    status: str
    created_at: str
    owned_seller_targets: int
    owned_buyer_parties: int
    owned_buyer_intents: int
    latest_activity_at: str | None


class UserOptionOut(BaseModel):
    id: UUID
    name: str
    username: str | None
    role: str
    status: str


# 最近活跃只统计**人主动做的事**。标的/买家/意向的 updated_at 会被 AI 解析和
# 调研回填刷新，把它算进来等于把机器的动作记在负责人头上——旧数据看板正是
# 这么算的，所以那张表上的「最近活跃」测的是对象活跃度，不是人的活跃度。
USER_ACTIVITY_SOURCES = (
    ("business_update", "created_by", "created_at", ""),
    ("relation_event", "created_by", "created_at", "and deleted_at is null"),
    ("action_application_log", "applied_by", "applied_at", ""),
    ("recommendation_message", "created_by", "created_at", ""),
)


def _latest_activity_sql(user_expr: str) -> str:
    parts = [
        f"coalesce((select max({column}) from {table} "
        f"where {owner} = {user_expr} {extra}), '-infinity'::timestamptz)"
        for table, owner, column, extra in USER_ACTIVITY_SOURCES
    ]
    return "greatest(\n" + ",\n".join(f"        {part}" for part in parts) + "\n      )::text"


USER_LIST_SQL = f"""
    select
      u.id,
      u.username,
      u.name,
      u.role,
      u.status,
      u.created_at::text as created_at,
      (
        select count(*) from seller_target t
        where t.owner_user_id = u.id and t.deleted_at is null
      ) as owned_seller_targets,
      (
        select count(*) from buyer_party b
        where b.owner_user_id = u.id and b.deleted_at is null
      ) as owned_buyer_parties,
      (
        select count(*) from buyer_intent i
        where i.owner_user_id = u.id and i.deleted_at is null
      ) as owned_buyer_intents,
      {_latest_activity_sql("u.id")} as latest_activity_at
    from app_user u
    where u.team_id = :team_id and u.id <> :system_user_id
    order by u.created_at asc
"""


@router.get("", response_model=list[UserOut])
def list_users(current_user: CurrentUser, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    require_admin(current_user)
    rows = db.execute(
        text(USER_LIST_SQL),
        {"team_id": DEFAULT_TEAM_ID, "system_user_id": SYSTEM_USER_ID},
    ).mappings()
    return [_user_row(row) for row in rows]


def _user_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    # greatest() over four '-infinity' floors means the account has never acted.
    if item.get("latest_activity_at") == "-infinity":
        item["latest_activity_at"] = None
    return item


@router.get("/options", response_model=list[UserOptionOut])
def list_user_options(current_user: CurrentUser, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    require_admin(current_user)
    rows = db.execute(
        text(
            """
            select id, name, username, role, status
            from app_user
            where team_id = :team_id and id <> :system_user_id
            order by created_at asc
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "system_user_id": SYSTEM_USER_ID},
    ).mappings()
    return [dict(row) for row in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    require_admin(current_user)
    if not USERNAME_PATTERN.match(payload.username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="用户名只能包含字母、数字、点、下划线和短横线（2-50 位）。",
        )

    existing = db.execute(
        text("select 1 from app_user where lower(username) = lower(:username)"),
        {"username": payload.username},
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在。")

    row = (
        db.execute(
            text(
                """
                insert into app_user (team_id, default_workspace_id, name, username, password_hash, role, status)
                values (:team_id, :workspace_id, :name, :username, :password_hash, :role, 'active')
                returning id, username, name, role, status, created_at::text as created_at
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "name": payload.name.strip(),
                "username": payload.username,
                "password_hash": hash_password(payload.password),
                "role": payload.role,
            },
        )
        .mappings()
        .one()
    )
    db.commit()
    return {
        **dict(row),
        "owned_seller_targets": 0,
        "owned_buyer_parties": 0,
        "owned_buyer_intents": 0,
        "latest_activity_at": None,
    }


@router.patch("/{user_id:uuid}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    _guard_managed_user(user_id)
    if user_id == current_user.user_id and (payload.status == "disabled" or payload.role == "consultant"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用或降级自己的账号。")

    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有需要更新的字段。")

    assignments = ", ".join(f"{field} = :{field}" for field in changes)
    row = (
        db.execute(
            text(
                f"""
                update app_user
                set {assignments}, updated_at = now()
                where id = :user_id and team_id = :team_id
                returning id, username, name, role, status, created_at::text as created_at
                """
            ),
            {**changes, "user_id": user_id, "team_id": DEFAULT_TEAM_ID},
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在。")
    db.commit()
    invalidate_user_context_cache(user_id)
    counts = _owned_counts(db, user_id)
    return {**dict(row), **counts}


@router.post("/{user_id:uuid}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: UUID,
    payload: ResetPasswordRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    require_admin(current_user)
    _guard_managed_user(user_id)
    result = db.execute(
        text(
            """
            update app_user
            set password_hash = :password_hash, updated_at = now()
            where id = :user_id and team_id = :team_id
            """
        ),
        {"password_hash": hash_password(payload.password), "user_id": user_id, "team_id": DEFAULT_TEAM_ID},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在。")
    db.commit()
    invalidate_user_context_cache(user_id)


def _guard_managed_user(user_id: UUID) -> None:
    if user_id == SYSTEM_USER_ID:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="系统助手账号不可修改。")


def _owned_counts(db: Session, user_id: UUID) -> dict[str, Any]:
    row = (
        db.execute(
            text(
                f"""
                select
                  (select count(*) from seller_target t where t.owner_user_id = :user_id and t.deleted_at is null) as owned_seller_targets,
                  (select count(*) from buyer_party b where b.owner_user_id = :user_id and b.deleted_at is null) as owned_buyer_parties,
                  (select count(*) from buyer_intent i where i.owner_user_id = :user_id and i.deleted_at is null) as owned_buyer_intents,
                  {_latest_activity_sql(":user_id")} as latest_activity_at
                """
            ),
            {"user_id": user_id},
        )
        .mappings()
        .one()
    )
    return _user_row(row)
