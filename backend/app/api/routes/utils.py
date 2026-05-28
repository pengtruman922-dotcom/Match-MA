from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
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
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
) -> None:
    statement = text(
        """
        insert into action_application_log (
          team_id, workspace_id, entity_type, entity_id, field_path,
          old_value_json, new_value_json, source_type, business_update_id,
          extracted_action_id, applied_by, edited_before_apply
        )
        values (
          :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
          :old_value_json, :new_value_json,
          :source_type, :business_update_id,
          :extracted_action_id, :applied_by, false
        )
        """
    ).bindparams(
        bindparam("old_value_json", type_=JSONB),
        bindparam("new_value_json", type_=JSONB),
    )

    db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_path": field_path,
            "old_value_json": json_safe(old_value),
            "new_value_json": json_safe(new_value),
            "source_type": source_type,
            "business_update_id": business_update_id,
            "extracted_action_id": extracted_action_id,
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


def write_action_logs_for_diff(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    diff: dict[str, tuple[Any, Any]],
    source_type: str = "direct_api",
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
) -> None:
    for field_path, (old_value, new_value) in diff.items():
        write_action_log(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            source_type=source_type,
            business_update_id=business_update_id,
            extracted_action_id=extracted_action_id,
        )
