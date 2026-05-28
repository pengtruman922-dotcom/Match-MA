from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def write_action_log(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    field_path: str,
    old_value: Any,
    new_value: Any,
    source_type: str = "direct_api",
) -> None:
    db.execute(
        text(
            """
            insert into action_application_log (
              team_id, workspace_id, entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, applied_by, edited_before_apply
            )
            values (
              :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
              to_jsonb(:old_value::text), to_jsonb(:new_value::text),
              :source_type, :applied_by, false
            )
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_path": field_path,
            "old_value": json_safe(old_value),
            "new_value": json_safe(new_value),
            "source_type": source_type,
            "applied_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def diff_payload(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    diff: dict[str, tuple[Any, Any]] = {}
    for key, new_value in changes.items():
        old_value = original.get(key)
        if json_safe(old_value) != json_safe(new_value):
            diff[key] = (old_value, new_value)
    return diff

