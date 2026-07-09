from decimal import Decimal
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
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
    applied_by: UUID | None = None,
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
            "applied_by": applied_by or DEFAULT_ADMIN_USER_ID,
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
    applied_by: UUID | None = None,
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
            applied_by=applied_by,
        )


def owner_filter_condition(
    owner: str | None,
    *,
    column: str = "owner_user_id",
) -> tuple[str, UUID | None] | None:
    """Parse a list-endpoint owner filter: a user UUID or the literal 'unassigned'."""
    if not owner:
        return None
    if owner == "unassigned":
        return (f"{column} is null", None)
    try:
        return (f"{column} = :owner_user_id", UUID(owner))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无效的负责人筛选值。",
        ) from exc


def ensure_active_user(db: Session, user_id: UUID) -> None:
    row = db.execute(
        text("select 1 from app_user where id = :user_id and status = 'active'"),
        {"user_id": user_id},
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="指定的负责人不存在或已停用。",
        )


def owner_filter_options(db: Session, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Owner filter choices for a list page: one row per owner plus 'unassigned'."""
    rows = db.execute(
        text(
            f"""
            select
              coalesce(t.owner_user_id::text, 'unassigned') as value,
              coalesce(au.name, '未指派') as label,
              count(*) as count
            from {table} t
            left join app_user au on au.id = t.owner_user_id
            where t.team_id = :team_id
              and t.workspace_id = :workspace_id
              and t.deleted_at is null
            group by t.owner_user_id, au.name
            order by count desc, label asc
            """
        ),
        params,
    ).mappings().all()
    return [
        {"value": row["value"], "label": row["label"], "count": int(row["count"])}
        for row in rows
    ]


def assign_owner_bulk(
    db: Session,
    *,
    table: str,
    entity_type: str,
    entity_ids: list[UUID],
    new_owner_user_id: UUID | None,
    actor_user_id: UUID,
) -> list[UUID]:
    """Reassign owner on the given rows and log each change to action_application_log."""
    if not entity_ids:
        return []
    rows = db.execute(
        text(
            f"""
            select id, owner_user_id
            from {table}
            where id in :entity_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "entity_ids": entity_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    changed = [row for row in rows if row["owner_user_id"] != new_owner_user_id]
    if not changed:
        return []

    changed_ids = [row["id"] for row in changed]
    db.execute(
        text(
            f"""
            update {table}
            set owner_user_id = :owner_user_id, updated_at = now(), updated_by = :updated_by
            where id in :entity_ids
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "owner_user_id": new_owner_user_id,
            "updated_by": actor_user_id,
            "entity_ids": changed_ids,
        },
    )
    for row in changed:
        write_action_log(
            db,
            entity_type=entity_type,
            entity_id=row["id"],
            field_path="owner_user_id",
            old_value=row["owner_user_id"],
            new_value=new_owner_user_id,
            source_type="owner_assignment",
            applied_by=actor_user_id,
        )
    return changed_ids


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
