from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/update-logs", tags=["update-logs"])


class UpdateLogOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    field_path: str
    old_value_json: Any
    new_value_json: Any
    source_type: str | None
    applied_by: UUID | None
    applied_at: str
    edited_before_apply: bool
    can_rollback: bool
    rollback_at: str | None


@router.get("", response_model=list[UpdateLogOut])
def list_update_logs(
    entity_type: str = Query(pattern="^(seller_target|buyer_intent)$"),
    entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    where = [
        "team_id = :team_id",
        "workspace_id = :workspace_id",
        "entity_type = :entity_type",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "entity_type": entity_type,
        "limit": limit,
        "offset": offset,
    }

    if entity_id is not None:
        where.append("entity_id = :entity_id")
        params["entity_id"] = entity_id

    rows = db.execute(
        text(
            f"""
            select
              id, entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, applied_by,
              applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at
            from action_application_log
            where {' and '.join(where)}
            order by applied_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()

    return [dict(row) for row in rows]

