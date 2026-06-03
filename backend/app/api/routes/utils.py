from decimal import Decimal
from datetime import date, datetime
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
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
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
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> None:
    statement = text(
        """
        insert into action_application_log (
          team_id, workspace_id, entity_type, entity_id, field_path,
          old_value_json, new_value_json, source_type, source_id, evidence_id,
          business_update_id, extracted_action_id, applied_by, edited_before_apply,
          metadata_json
        )
        values (
          :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
          :old_value_json, :new_value_json,
          :source_type, :source_id, :evidence_id,
          :business_update_id, :extracted_action_id, :applied_by, false,
          :metadata_json
        )
        """
    ).bindparams(
        bindparam("old_value_json", type_=JSONB),
        bindparam("new_value_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
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
            "source_id": source_id,
            "evidence_id": evidence_id,
            "business_update_id": business_update_id,
            "extracted_action_id": extracted_action_id,
            "applied_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": json_safe(metadata_json or {}),
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
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
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
            source_id=source_id,
            evidence_id=evidence_id,
            business_update_id=business_update_id,
            extracted_action_id=extracted_action_id,
            metadata_json=metadata_json,
        )


def write_field_value_sources_for_diff(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    source_type: str,
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    source_label: str | None = None,
    confidence: Any = None,
    review_status: str = "auto_accepted",
    source_context: dict[str, Any] | None = None,
) -> None:
    for field_path in diff:
        db.execute(
            text(
                """
                insert into field_value_source (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  value_snapshot_json, source_type, source_id, evidence_id,
                  source_label, confidence, review_status, created_by
                )
                values (
                  :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
                  :value_snapshot_json, :source_type, :source_id, :evidence_id,
                  :source_label, :confidence, :review_status, :created_by
                )
                """
            ).bindparams(bindparam("value_snapshot_json", type_=JSONB)),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_path": field_path,
                "value_snapshot_json": {
                    "value": json_safe(changes.get(field_path)),
                    "source_context": json_safe(source_context or {}),
                },
                "source_type": source_type,
                "source_id": source_id,
                "evidence_id": evidence_id,
                "source_label": source_label,
                "confidence": confidence,
                "review_status": review_status,
                "created_by": DEFAULT_ADMIN_USER_ID,
            },
        )
