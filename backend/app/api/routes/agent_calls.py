"""外部 Agent 的调用日志（仅管理员）：谁、几点、哪个工具、什么参数、命中几条。

401 也在这里，actor_label 是 ``unauthenticated``，参数里只有 key 前缀与 User-Agent。
排「wegent 连不上」先看这里：没有记录 = 请求没到；unauthenticated = 到了但没带对 key。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/agent-calls", tags=["api-keys"])


class AgentCallOut(BaseModel):
    id: UUID
    created_at: str
    actor_label: str
    api_key_name: str | None = None
    tool_name: str
    arguments_json: dict[str, Any]
    matched: int | None = None
    returned: int | None = None
    duration_ms: int | None = None
    error_text: str | None = None


@router.get("", response_model=list[AgentCallOut])
def list_agent_calls(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    require_admin(current_user)
    rows = (
        db.execute(
            text(
                """
                select l.id, l.created_at::text as created_at, l.actor_label,
                       k.name as api_key_name, l.tool_name, l.arguments_json,
                       l.matched, l.returned, l.duration_ms, l.error_text
                from agent_call_log l
                left join api_key k on k.id = l.api_key_id
                where l.team_id = :team_id and l.workspace_id = :workspace_id
                order by l.created_at desc
                limit :limit
                """
            ),
            {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
