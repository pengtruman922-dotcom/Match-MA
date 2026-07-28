from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.api.routes.utils import (
    ensure_entity_visible,
    ensure_entity_writable,
    owner_scope_required,
    relation_visible_sql,
    visible_scope_sql,
)
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.profile_sections import (
    PROFILE_SECTION_CODES,
    PROFILE_SECTION_FIELD_PREFIX,
)
from backend.app.services.search_docs import create_search_doc_rebuild_job

router = APIRouter(prefix="/update-logs", tags=["update-logs"])


class UpdateLogOut(BaseModel):
    id: UUID
    extracted_action_id: UUID | None = None
    business_update_id: UUID | None = None
    entity_type: str
    entity_id: UUID
    field_path: str
    old_value_json: Any
    new_value_json: Any
    source_type: str | None
    source_id: UUID | None = None
    applied_by: UUID | None
    applied_at: str
    edited_before_apply: bool
    can_rollback: bool
    rollback_at: str | None


class UpdateLogRollbackRequest(BaseModel):
    force: bool = False
    reason: str | None = None


class UpdateLogRollbackOut(BaseModel):
    status: str
    rollback_count: int
    rolled_back_logs: list[dict[str, Any]]
    skipped_logs: list[dict[str, Any]]
    extracted_action_id: UUID | None = None
    business_update_id: UUID | None = None


class UpdateBatchAttachmentOut(BaseModel):
    id: UUID
    file_name: str
    mime_type: str | None = None
    file_size: int | None = None
    uploaded_at: str
    download_route: str


class UpdateBatchChangeOut(BaseModel):
    log_id: UUID
    field_path: str
    old_value: Any
    new_value: Any
    applied_at: str
    rollback_at: str | None = None


class UpdateBatchOut(BaseModel):
    batch_key: str
    entity_type: str
    entity_id: UUID
    source_type: str
    batch_category: Literal["business_update", "management_operation", "rollback"]
    source_id: UUID | None = None
    input_type: str | None = None
    input_summary: str | None = None
    raw_input: str | None = None
    attachments: list[UpdateBatchAttachmentOut]
    operator_user_id: UUID | None = None
    operator_name: str
    submitted_at: str
    applied_at: str | None = None
    status: str
    changes: list[UpdateBatchChangeOut]
    changed_field_count: int
    is_latest_effective_batch: bool
    can_rollback: bool
    rollback_block_reason: str | None = None


class UpdateBatchListOut(BaseModel):
    items: list[UpdateBatchOut]
    total: int
    limit: int
    offset: int


class UpdateBatchRollbackRequest(BaseModel):
    entity_type: Literal["seller_target", "buyer_intent"]
    entity_id: UUID
    reason: str | None = None


@router.get("", response_model=list[UpdateLogOut])
def list_update_logs(
    current_user: CurrentUser,
    entity_type: str = Query(pattern="^(seller_target|buyer_intent|buyer_party|buyer_seller_relation)$"),
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
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        if entity_type == "seller_target":
            where.append(
                f"""
                exists (
                  select 1 from seller_target scope_st
                  where scope_st.id = action_application_log.entity_id
                    and scope_st.deleted_at is null
                    and {visible_scope_sql("seller_target", "scope_st")}
                )
                """
            )
        elif entity_type == "buyer_intent":
            where.append(
                f"""
                exists (
                  select 1 from buyer_intent scope_bi
                  where scope_bi.id = action_application_log.entity_id
                    and scope_bi.deleted_at is null
                    and {visible_scope_sql("buyer_intent", "scope_bi")}
                )
                """
            )
        elif entity_type == "buyer_party":
            where.append(
                f"""
                exists (
                  select 1 from buyer_party scope_bp
                  where scope_bp.id = action_application_log.entity_id
                    and scope_bp.deleted_at is null
                    and {visible_scope_sql("buyer_party", "scope_bp")}
                )
                """
            )
        elif entity_type == "buyer_seller_relation":
            where.append(
                f"""
                exists (
                  select 1 from buyer_seller_relation scope_r
                  where scope_r.id = action_application_log.entity_id
                    and scope_r.deleted_at is null
                    and {relation_visible_sql("scope_r")}
                )
                """
            )

    if entity_id is not None:
        where.append("entity_id = :entity_id")
        params["entity_id"] = entity_id

    rows = db.execute(
        text(
            f"""
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id, applied_by,
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


@router.get("/batches", response_model=UpdateBatchListOut)
def list_update_batches(
    current_user: CurrentUser,
    entity_type: Literal["seller_target", "buyer_intent"] = Query(),
    entity_id: UUID = Query(),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_visible(db, current_user, entity_type=entity_type, entity_id=entity_id)
    batches = _build_update_batches(db, entity_type=entity_type, entity_id=entity_id)
    return {
        "items": [_public_update_batch(item) for item in batches[offset : offset + limit]],
        "total": len(batches),
        "limit": limit,
        "offset": offset,
    }


@router.post("/batches/{batch_key}/rollback", response_model=UpdateLogRollbackOut)
def rollback_update_batch(
    batch_key: str,
    payload: UpdateBatchRollbackRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_writable(
        db,
        current_user,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )
    batch = next(
        (
            item
            for item in _build_update_batches(
                db,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
            )
            if item["batch_key"] == batch_key
        ),
        None,
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update batch not found.")
    if not batch["can_rollback"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=batch.get("rollback_block_reason") or "This update batch cannot be rolled back.",
        )

    logs = batch.get("_active_logs") or []
    if not logs:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This update batch has no active changes.")
    result = _rollback_logs(
        db,
        logs,
        force=False,
        reason=payload.reason,
        actor_user_id=current_user.user_id,
    )
    extracted_action_ids = {
        log.get("extracted_action_id") for log in logs if log.get("extracted_action_id") is not None
    }
    for extracted_action_id in extracted_action_ids:
        _mark_action_rejected_after_rollback(db, extracted_action_id, actor_user_id=current_user.user_id)
    db.commit()
    return result


@router.post("/{log_id}/rollback", response_model=UpdateLogRollbackOut)
def rollback_update_log(
    log_id: UUID,
    current_user: CurrentUser,
    payload: UpdateLogRollbackRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    request = payload or UpdateLogRollbackRequest()
    log = _get_update_log_or_404(db, log_id)
    result = _rollback_logs(
        db,
        [log],
        force=request.force,
        reason=request.reason,
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return result


@router.post("/actions/{extracted_action_id}/rollback", response_model=UpdateLogRollbackOut)
def rollback_extracted_action_logs(
    extracted_action_id: UUID,
    current_user: CurrentUser,
    payload: UpdateLogRollbackRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    request = payload or UpdateLogRollbackRequest()
    logs = _get_rollbackable_logs_for_action(db, extracted_action_id)
    if not logs:
        return {
            "status": "noop",
            "rollback_count": 0,
            "rolled_back_logs": [],
            "skipped_logs": [],
            "extracted_action_id": extracted_action_id,
            "business_update_id": None,
        }
    result = _rollback_logs(
        db,
        logs,
        force=request.force,
        reason=request.reason,
        actor_user_id=current_user.user_id,
    )
    _mark_action_rejected_after_rollback(db, extracted_action_id, actor_user_id=current_user.user_id)
    db.commit()
    return {**result, "extracted_action_id": extracted_action_id}


def _build_update_batches(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
) -> list[dict[str, Any]]:
    logs = _update_batch_logs(db, entity_type=entity_type, entity_id=entity_id)
    business_update_ids = {
        row["business_update_id"] for row in logs if row.get("business_update_id") is not None
    }
    business_updates = _entity_business_updates(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        extra_ids=business_update_ids,
    )
    business_updates_by_id = {str(row["id"]): row for row in business_updates}
    attachments_by_update = _business_update_attachments(db, [row["id"] for row in business_updates])
    parse_jobs = _entity_parse_jobs(db, entity_type=entity_type, entity_id=entity_id)
    parse_jobs_by_id = {str(row["id"]): row for row in parse_jobs}

    grouped_logs: dict[str, list[dict[str, Any]]] = {}
    manual_key_by_signature: dict[tuple[str, str, str], str] = {}
    for row in logs:
        batch_key = _batch_key_for_log(row, manual_key_by_signature)
        grouped_logs.setdefault(batch_key, []).append(row)

    batches: list[dict[str, Any]] = []
    consumed_keys: set[str] = set()
    for update in business_updates:
        update_id = str(update["id"])
        batch_key = f"business-update-{update_id}"
        batch_logs = grouped_logs.get(batch_key, [])
        batches.append(
            _business_update_batch(
                update,
                batch_logs,
                attachments_by_update.get(update_id, []),
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
        consumed_keys.add(batch_key)

    for job in parse_jobs:
        business_update_id = _payload_uuid_text(job.get("payload_json"), "business_update_id")
        if business_update_id and business_update_id in business_updates_by_id:
            continue
        job_id = str(job["id"])
        batch_key = f"parse-job-{job_id}"
        batches.append(
            _parse_job_batch(
                job,
                grouped_logs.get(batch_key, []),
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
        consumed_keys.add(batch_key)

    for batch_key, batch_logs in grouped_logs.items():
        if batch_key in consumed_keys:
            continue
        source_job = None
        if batch_key.startswith("parse-job-"):
            source_job = parse_jobs_by_id.get(batch_key.removeprefix("parse-job-"))
        if source_job is not None:
            batches.append(
                _parse_job_batch(
                    source_job,
                    batch_logs,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            )
            continue
        batches.append(
            _log_only_batch(
                batch_key,
                batch_logs,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )

    latest = _latest_effective_batch(batches)
    for batch in batches:
        active_logs = batch.get("_active_logs") or []
        batch["is_latest_effective_batch"] = batch is latest
        batch["can_rollback"] = False
        batch["rollback_block_reason"] = _batch_rollback_block_reason(batch, latest)
        if batch is latest and active_logs and batch["rollback_block_reason"] is None:
            current_values_match = all(
                _values_match_for_rollback(_get_current_field_value(db, log), log.get("new_value_json"))
                for log in active_logs
            )
            if current_values_match:
                batch["can_rollback"] = True
            else:
                batch["rollback_block_reason"] = "字段已发生后续变化，请手工修正"

    return sorted(batches, key=_batch_sort_value, reverse=True)


def _update_batch_logs(db: Session, *, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              al.id, al.extracted_action_id, al.business_update_id,
              al.entity_type, al.entity_id, al.field_path,
              al.old_value_json, al.new_value_json, al.source_type, al.source_id,
              al.applied_by, al.applied_at::text as applied_at,
              al.edited_before_apply, al.can_rollback,
              al.rollback_at::text as rollback_at, al.metadata_json,
              applied_user.name as applied_by_name
            from action_application_log al
            left join app_user applied_user on applied_user.id = al.applied_by
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = :entity_type
              and al.entity_id = :entity_id
            order by al.applied_at desc, al.id desc
            limit 1000
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _entity_business_updates(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    extra_ids: set[UUID],
) -> list[dict[str, Any]]:
    bound_column = {
        "seller_target": "bound_seller_target_ids_json",
        "buyer_intent": "bound_buyer_intent_ids_json",
    }[entity_type]
    extra_clause = ""
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "entity_id_text": str(entity_id),
    }
    statement = f"""
        select
          bu.id, bu.raw_text, bu.input_type, bu.processing_status,
          bu.created_by, bu.created_at::text as created_at, bu.metadata_json,
          creator.name as created_by_name
        from business_update bu
        left join app_user creator on creator.id = bu.created_by
        where bu.team_id = :team_id
          and bu.workspace_id = :workspace_id
          and (
            bu.{bound_column} ? :entity_id_text
            {{extra_clause}}
          )
        order by bu.created_at desc
        limit 200
    """
    if extra_ids:
        extra_clause = "or bu.id in :extra_ids"
        params["extra_ids"] = tuple(extra_ids)
        query = text(statement.format(extra_clause=extra_clause)).bindparams(bindparam("extra_ids", expanding=True))
    else:
        query = text(statement.format(extra_clause=""))
    rows = db.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def _business_update_attachments(
    db: Session,
    business_update_ids: list[UUID],
) -> dict[str, list[dict[str, Any]]]:
    if not business_update_ids:
        return {}
    rows = db.execute(
        text(
            """
            select
              al.entity_id as business_update_id,
              a.id, a.file_name, a.mime_type, a.file_size,
              a.uploaded_at::text as uploaded_at
            from attachment_link al
            join attachment a on a.id = al.attachment_id
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.entity_id in :business_update_ids
              and a.deleted_at is null
            order by a.uploaded_at asc
            """
        ).bindparams(bindparam("business_update_ids", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_ids": tuple(business_update_ids),
        },
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        update_id = str(item.pop("business_update_id"))
        item["download_route"] = f"/attachments/{item['id']}/download"
        grouped.setdefault(update_id, []).append(item)
    return grouped


def _entity_parse_jobs(db: Session, *, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
    job_type = {"seller_target": "seller_target_parse", "buyer_intent": "buyer_intent_parse"}[entity_type]
    rows = db.execute(
        text(
            """
            select
              job.id, job.job_type, job.status, job.entity_type, job.entity_id,
              job.payload_json, job.result_json, job.error_code, job.error_message,
              job.created_by, job.created_at::text as created_at,
              job.started_at::text as started_at, job.finished_at::text as finished_at,
              creator.name as created_by_name
            from background_job job
            left join app_user creator on creator.id = job.created_by
            where job.team_id = :team_id
              and job.workspace_id = :workspace_id
              and job.job_type = :job_type
              and job.entity_type = :entity_type
              and job.entity_id = :entity_id
            order by job.created_at desc
            limit 100
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": job_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _batch_key_for_log(
    row: dict[str, Any],
    manual_key_by_signature: dict[tuple[str, str, str], str],
) -> str:
    if row.get("source_type") == "rollback":
        signature = (
            "rollback",
            str(row.get("applied_by") or "system"),
            str(row.get("applied_at") or ""),
        )
        if signature not in manual_key_by_signature:
            manual_key_by_signature[signature] = f"rollback-{row['id']}"
        return manual_key_by_signature[signature]
    if row.get("business_update_id"):
        return f"business-update-{row['business_update_id']}"
    if row.get("source_type") in {"seller_target_parse", "buyer_intent_parse"} and row.get("source_id"):
        return f"parse-job-{row['source_id']}"
    signature = (
        str(row.get("source_type") or "direct_api"),
        str(row.get("applied_by") or "system"),
        str(row.get("applied_at") or ""),
    )
    if signature not in manual_key_by_signature:
        prefix = "rollback" if row.get("source_type") == "rollback" else "manual"
        manual_key_by_signature[signature] = f"{prefix}-{row['id']}"
    return manual_key_by_signature[signature]


def _business_update_batch(
    update: dict[str, Any],
    logs: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    *,
    entity_type: str,
    entity_id: UUID,
) -> dict[str, Any]:
    active_logs = _active_batch_logs(logs)
    status_value = str(update.get("processing_status") or "pending")
    if status_value in {"pending", "processing"}:
        batch_status = "parsing"
    elif status_value == "failed":
        batch_status = "failed"
    elif logs and not active_logs:
        batch_status = "rolled_back"
    else:
        batch_status = "applied"
    return _batch_record(
        batch_key=f"business-update-{update['id']}",
        entity_type=entity_type,
        entity_id=entity_id,
        source_type="business_update",
        source_id=update["id"],
        input_type=update.get("input_type"),
        raw_input=update.get("raw_text"),
        attachments=attachments,
        operator_user_id=update.get("created_by"),
        operator_name=update.get("created_by_name"),
        submitted_at=update["created_at"],
        status_value=batch_status,
        logs=logs,
    )


def _parse_job_batch(
    job: dict[str, Any],
    logs: list[dict[str, Any]],
    *,
    entity_type: str,
    entity_id: UUID,
) -> dict[str, Any]:
    status_value = str(job.get("status") or "queued")
    if status_value in {"queued", "running", "retry_waiting"}:
        batch_status = "parsing"
    elif status_value == "failed":
        batch_status = "failed"
    elif logs and not _active_batch_logs(logs):
        batch_status = "rolled_back"
    else:
        batch_status = "applied"
    raw_key = "raw_target_text" if entity_type == "seller_target" else "raw_requirement_text"
    return _batch_record(
        batch_key=f"parse-job-{job['id']}",
        entity_type=entity_type,
        entity_id=entity_id,
        source_type=job.get("job_type") or "parser",
        source_id=job["id"],
        input_type="text",
        raw_input=(job.get("payload_json") or {}).get(raw_key),
        attachments=[],
        operator_user_id=job.get("created_by"),
        operator_name=job.get("created_by_name"),
        submitted_at=job["created_at"],
        status_value=batch_status,
        logs=logs,
    )


def _log_only_batch(
    batch_key: str,
    logs: list[dict[str, Any]],
    *,
    entity_type: str,
    entity_id: UUID,
) -> dict[str, Any]:
    first = logs[0]
    is_rollback = first.get("source_type") == "rollback"
    return _batch_record(
        batch_key=batch_key,
        entity_type=entity_type,
        entity_id=entity_id,
        source_type=first.get("source_type") or "direct_api",
        source_id=first.get("source_id"),
        input_type=None,
        raw_input=None,
        attachments=[],
        operator_user_id=first.get("applied_by"),
        operator_name=first.get("applied_by_name"),
        submitted_at=first["applied_at"],
        status_value="rolled_back" if is_rollback else "applied",
        logs=logs,
    )


def _batch_record(
    *,
    batch_key: str,
    entity_type: str,
    entity_id: UUID,
    source_type: str,
    source_id: UUID | None,
    input_type: str | None,
    raw_input: Any,
    attachments: list[dict[str, Any]],
    operator_user_id: UUID | None,
    operator_name: str | None,
    submitted_at: str,
    status_value: str,
    logs: list[dict[str, Any]],
) -> dict[str, Any]:
    active_logs = _active_batch_logs(logs)
    visible_logs = logs if source_type == "rollback" else [row for row in logs if row.get("source_type") != "rollback"]
    changes = [
        {
            "log_id": row["id"],
            "field_path": row["field_path"],
            "old_value": row.get("old_value_json"),
            "new_value": row.get("new_value_json"),
            "applied_at": row["applied_at"],
            "rollback_at": row.get("rollback_at"),
        }
        for row in visible_logs
    ]
    applied_at = max((row["applied_at"] for row in logs), default=None)
    raw_input_text = str(raw_input).strip() if raw_input is not None else None
    return {
        "batch_key": batch_key,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source_type": source_type,
        "batch_category": _batch_category(source_type, logs),
        "source_id": source_id,
        "input_type": input_type,
        "input_summary": _truncate_text(raw_input_text, 180),
        "raw_input": raw_input_text,
        "attachments": attachments,
        "operator_user_id": operator_user_id,
        "operator_name": operator_name or "系统助手",
        "submitted_at": submitted_at,
        "applied_at": applied_at,
        "status": status_value,
        "changes": changes,
        "changed_field_count": len(changes),
        "is_latest_effective_batch": False,
        "can_rollback": False,
        "rollback_block_reason": None,
        "_active_logs": active_logs,
    }


def _active_batch_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in logs
        if row.get("source_type") != "rollback" and row.get("rollback_at") is None
    ]


def _latest_effective_batch(batches: list[dict[str, Any]]) -> dict[str, Any] | None:
    effective = [
        item
        for item in batches
        if item.get("_active_logs") and item.get("batch_category") == "business_update"
    ]
    if not effective:
        return None
    return max(effective, key=_batch_effective_value)


def _batch_effective_value(batch: dict[str, Any]) -> str:
    active_logs = batch.get("_active_logs") or []
    return max((row["applied_at"] for row in active_logs), default="")


def _batch_sort_value(batch: dict[str, Any]) -> str:
    return str(batch.get("applied_at") or batch.get("submitted_at") or "")


def _batch_rollback_block_reason(
    batch: dict[str, Any],
    latest: dict[str, Any] | None,
) -> str | None:
    active_logs = batch.get("_active_logs") or []
    if batch.get("batch_category") == "management_operation":
        return "管理操作，不参与撤回"
    if batch.get("batch_category") == "rollback":
        return "本次更新已撤回"
    if batch.get("status") == "failed":
        return "本次更新未写入字段"
    if batch.get("status") == "parsing":
        return "本次更新仍在解析中"
    if not active_logs:
        if batch.get("status") == "rolled_back":
            return "本次更新已撤回"
        return "本次更新未写入字段"
    if batch is not latest:
        return "仅最近一次有效更新可以撤回"
    unsupported = next((_rollbackability(log)["reason"] for log in active_logs if not _rollbackability(log)["ok"]), None)
    if unsupported:
        return "本次更新包含不可撤回字段"
    return None


MANAGEMENT_FIELDS_BY_ENTITY = {
    "seller_target": {"owner_user_id", "lifecycle_status"},
    "buyer_party": {"owner_user_id", "status"},
    "buyer_intent": {"owner_user_id", "status", "pause_reason"},
}


def _batch_category(source_type: str, logs: list[dict[str, Any]]) -> str:
    if source_type == "rollback":
        return "rollback"
    if source_type in {"business_update", "seller_target_parse", "buyer_intent_parse"}:
        return "business_update"
    if source_type == "owner_assignment":
        return "management_operation"

    relevant_logs = [row for row in logs if row.get("source_type") != "rollback"]
    if relevant_logs and all(
        row.get("field_path") in MANAGEMENT_FIELDS_BY_ENTITY.get(str(row.get("entity_type")), set())
        for row in relevant_logs
    ):
        return "management_operation"
    return "business_update"


def _public_update_batch(batch: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in batch.items() if not key.startswith("_")}


def _payload_uuid_text(payload: Any, key: str) -> str | None:
    if not isinstance(payload, dict) or not payload.get(key):
        return None
    try:
        return str(UUID(str(payload[key])))
    except (TypeError, ValueError):
        return None


def _truncate_text(value: str | None, max_length: int) -> str | None:
    if not value:
        return None
    if len(value) <= max_length:
        return value
    return value[: max_length - 1] + "…"


ROLLBACK_TABLE_BY_ENTITY = {
    "seller_target": "seller_target",
    "buyer_intent": "buyer_intent",
    "buyer_party": "buyer_party",
    "buyer_seller_relation": "buyer_seller_relation",
}

ROLLBACK_FIELDS_BY_ENTITY = {
    "seller_target": {
        "target_name",
        "target_type",
        "target_subject_name",
        "industry_l1",
        "industry_l2",
        "industry_pairs_json",
        "location_province",
        "location_city",
        "location_district",
        "listed_status",
        "market_cap_yuan",
        "current_revenue_yuan",
        "current_net_profit_yuan",
        "current_total_profit_yuan",
        "current_assets_yuan",
        "current_debt_ratio",
        "current_operating_cash_flow_yuan",
        "financial_period_label",
        "profitability_status",
        "cash_flow_status",
        "operation_stability_status",
        "valuation_yuan",
        "valuation_date",
        "asking_price_yuan",
        "asking_price_date",
        "pe_ratio",
        "pe_source_type",
        "premium_rate",
        "is_for_sale",
        "can_control",
        "can_consolidate",
        "accepts_minority_investment",
        "transfer_ratio_min",
        "transfer_ratio_max",
        "transfer_ratio_text",
        "transfer_flexibility_type",
        "consolidation_path_summary",
        "accepts_relocation",
        "accepts_return_investment",
        "management_team_summary",
        "management_retention_possible",
        "earnout_dependency_status",
        # recommendation_status 已随 0727 状态合并删除；历史日志里仍有该 field_path，
        # 不在此白名单意味着它们被标为不可回滚，而不是回滚时炸在缺列上。
        "information_status",
        "business_summary",
        "transaction_summary",
        "risk_summary",
        "gap_summary",
    },
    "buyer_intent": {
        "intent_name",
        "status",
        "pause_reason",
        "contact_name",
        "contact_info_json",
        "raw_requirement_text",
        "intent_summary",
        "parsed_requirement_json",
        "industry_primary",
        "industry_secondary",
        "industries_json",
        "excluded_industries_json",
        "industry_focus_tags_json",
        "region_scope_summary",
        "region_constraints_json",
        "min_revenue_yuan",
        "min_net_profit_yuan",
        "min_total_profit_yuan",
        "max_pe",
        "max_ps",
        "min_net_margin",
        "min_gross_margin",
        "min_valuation_yuan",
        "max_valuation_yuan",
        "min_market_cap_yuan",
        "max_market_cap_yuan",
        "market_cap_range_summary",
        "industry_l2_json",
        "budget_min_yuan",
        "budget_max_yuan",
        "acceptable_cash_flow_status_json",
        "acceptable_profitability_status_json",
        "requires_relocation",
        "relocation_target_regions_json",
        "requires_return_investment",
        "return_investment_multiple",
        "requires_team_retention",
        "earnout_requirement",
        "listing_market_region",
        "requires_control",
        "requires_consolidation",
        "accepts_minority_investment",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "equity_ratio_summary",
        "equity_requirement_type",
        "acceptable_control_paths_json",
        "preferred_listed_status",
        "listing_board_requirement_summary",
        "financing_stage_requirement_summary",
        "transaction_type",
        "transaction_types_json",
        "premium_tolerance_summary",
        "max_premium_rate",
        "max_debt_ratio",
        "debt_ratio_requirement_summary",
        "major_risk_tolerance_summary",
        "buyer_industry_advantage_summary",
        "negative_summary",
        "priority_summary",
        "preference_summary",
        "unknown_summary",
        "follow_up_record",
    },
    "buyer_party": {
        "buyer_name",
        "legal_name",
        "aliases_json",
        "buyer_type",
        "group_name",
        "listed_status",
        "region_province",
        "region_city",
        "main_business",
        "capital_strength_summary",
        "profile_summary",
        "notes",
        "status",
    },
    "buyer_seller_relation": {
        "status",
        "status_reason",
        "first_recommended_at",
        "last_contact_at",
        "last_event_at",
        "last_event_summary",
    },
}

JSONB_ROLLBACK_FIELDS = {
    ("seller_target", "industry_pairs_json"),
    ("buyer_intent", "contact_info_json"),
    ("buyer_intent", "parsed_requirement_json"),
    ("buyer_intent", "region_constraints_json"),
    ("buyer_intent", "acceptable_control_paths_json"),
    ("buyer_intent", "transaction_types_json"),
    ("buyer_intent", "industries_json"),
    ("buyer_intent", "excluded_industries_json"),
    ("buyer_intent", "industry_l2_json"),
    ("buyer_intent", "acceptable_cash_flow_status_json"),
    ("buyer_intent", "acceptable_profitability_status_json"),
    ("buyer_intent", "relocation_target_regions_json"),
    ("buyer_intent", "industry_focus_tags_json"),
    ("buyer_party", "aliases_json"),
}


def _get_update_log_or_404(db: Session, log_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            from action_application_log
            where id = :log_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"log_id": log_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update log not found.")
    return dict(row)


def _get_rollbackable_logs_for_action(db: Session, extracted_action_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            from action_application_log
            where extracted_action_id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and can_rollback = true
              and rollback_at is null
              and coalesce(source_type, '') <> 'rollback'
            order by applied_at desc
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _rollback_logs(
    db: Session,
    logs: list[dict[str, Any]],
    *,
    force: bool,
    reason: str | None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    rolled_back_logs: list[dict[str, Any]] = []
    skipped_logs: list[dict[str, Any]] = []
    business_update_id = logs[0].get("business_update_id") if logs else None
    extracted_action_id = logs[0].get("extracted_action_id") if logs else None

    for log in logs:
        rollbackability = _rollbackability(log)
        if not rollbackability["ok"]:
            if len(logs) == 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=rollbackability["reason"])
            skipped_logs.append({"id": log["id"], "reason": rollbackability["reason"]})
            continue

        current_value = _get_current_field_value(db, log)
        if not force and not _values_match_for_rollback(current_value, log.get("new_value_json")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Current field value no longer matches this update log. "
                    "Refresh the page or retry with force=true after manual review."
                ),
            )

        _apply_field_rollback(db, log, actor_user_id=actor_user_id)
        rollback_log = _insert_rollback_log(
            db,
            log,
            current_value=current_value,
            reason=reason,
            actor_user_id=actor_user_id,
        )
        _mark_field_sources_ignored_after_rollback(db, log)
        _mark_log_rolled_back(db, log["id"])
        rolled_back_logs.append(rollback_log)

    rebuild_entities = {
        (log["entity_type"], log["entity_id"])
        for log in logs
        if log["entity_type"] in {"seller_target", "buyer_intent"}
    }
    for entity_type, entity_id in rebuild_entities:
        _enqueue_rebuild_after_rollback(db, entity_type=entity_type, entity_id=entity_id)

    return {
        "status": "rolled_back" if rolled_back_logs else "noop",
        "rollback_count": len(rolled_back_logs),
        "rolled_back_logs": rolled_back_logs,
        "skipped_logs": skipped_logs,
        "extracted_action_id": extracted_action_id,
        "business_update_id": business_update_id,
    }


def _rollbackability(log: dict[str, Any]) -> dict[str, Any]:
    entity_type = log.get("entity_type")
    field_path = log.get("field_path")
    if not log.get("can_rollback"):
        return {"ok": False, "reason": "This update log is marked as not rollbackable."}
    if log.get("rollback_at") is not None:
        return {"ok": False, "reason": "This update log has already been rolled back."}
    if log.get("source_type") == "rollback":
        return {"ok": False, "reason": "Rollback logs cannot be rolled back again."}
    if entity_type not in ROLLBACK_TABLE_BY_ENTITY:
        return {"ok": False, "reason": f"Rollback is not supported for entity_type={entity_type}."}
    if _profile_section_code(field_path):
        return {"ok": True, "reason": None}
    if field_path not in ROLLBACK_FIELDS_BY_ENTITY.get(entity_type, set()):
        return {"ok": False, "reason": f"Rollback is not supported for field_path={field_path}."}
    return {"ok": True, "reason": None}


def _rollback_profile_section(db: Session, log: dict[str, Any], *, actor_user_id: UUID) -> None:
    """Undo one section write by reviving the revision it superseded.

    entity_profile_section keeps every revision, so rolling back is retiring
    the row this log created and un-deleting the row it replaced — no value has
    to be reconstructed from the log, which is what makes the restored text
    exactly what was there before rather than an approximation of it.
    """
    metadata = log.get("metadata_json") or {}
    section_id = metadata.get("profile_section_id")
    if not section_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This profile section log predates rollback support and cannot be undone.",
        )
    db.execute(
        text(
            """
            update entity_profile_section
            set deleted_at = now(), updated_at = now(), updated_by = :user_id
            where id = cast(:section_id as uuid) and deleted_at is null
            """
        ),
        {"section_id": section_id, "user_id": actor_user_id},
    )
    superseded_id = metadata.get("superseded_profile_section_id")
    if superseded_id:
        db.execute(
            text(
                """
                update entity_profile_section
                set deleted_at = null, updated_at = now(), updated_by = :user_id
                where id = cast(:section_id as uuid)
                """
            ),
            {"section_id": superseded_id, "user_id": actor_user_id},
        )


def _profile_section_code(field_path: Any) -> str | None:
    """Profile sections are rows in their own table, not columns on the entity."""
    value = str(field_path or "")
    if not value.startswith(PROFILE_SECTION_FIELD_PREFIX):
        return None
    code = value[len(PROFILE_SECTION_FIELD_PREFIX) :]
    return code if code in PROFILE_SECTION_CODES else None


def _get_current_field_value(db: Session, log: dict[str, Any]) -> Any:
    entity_type = log["entity_type"]
    field_path = log["field_path"]
    if _profile_section_code(field_path):
        row = db.execute(
            text(
                """
                select info_status, content_text
                from entity_profile_section
                where id = cast(:section_id as uuid) and deleted_at is null
                """
            ),
            {"section_id": (log.get("metadata_json") or {}).get("profile_section_id")},
        ).mappings().one_or_none()
        return dict(row) if row else None
    if entity_type == "buyer_intent" and field_path == "follow_up_record":
        follow_up_id = (log.get("metadata_json") or {}).get("follow_up_id")
        row = db.execute(
            text(
                """
                select id
                from buyer_intent_follow_up
                where id = cast(:follow_up_id as uuid) and deleted_at is null
                """
            ),
            {"follow_up_id": follow_up_id},
        ).mappings().one_or_none()
        return log.get("new_value_json") if row else None
    table_name = ROLLBACK_TABLE_BY_ENTITY[entity_type]
    row = db.execute(
        text(
            f"""
            select {field_path} as value
            from {table_name}
            where id = :entity_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "entity_id": log["entity_id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollback target entity not found.")
    return row["value"]


def _apply_field_rollback(db: Session, log: dict[str, Any], *, actor_user_id: UUID) -> None:
    entity_type = log["entity_type"]
    field_path = log["field_path"]
    if _profile_section_code(field_path):
        _rollback_profile_section(db, log, actor_user_id=actor_user_id)
        return
    if entity_type == "buyer_intent" and field_path == "follow_up_record":
        follow_up_id = (log.get("metadata_json") or {}).get("follow_up_id")
        result = db.execute(
            text(
                """
                update buyer_intent_follow_up
                set deleted_at = now(), deleted_by = :deleted_by
                where id = cast(:follow_up_id as uuid) and deleted_at is null
                """
            ),
            {"follow_up_id": follow_up_id, "deleted_by": actor_user_id},
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Follow-up record not found.")
        return
    table_name = ROLLBACK_TABLE_BY_ENTITY[entity_type]
    statement = text(
        f"""
        update {table_name}
        set {field_path} = :rollback_value,
            updated_at = now(),
            updated_by = :updated_by
        where id = :entity_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    if (entity_type, field_path) in JSONB_ROLLBACK_FIELDS:
        statement = statement.bindparams(bindparam("rollback_value", type_=JSONB))
    result = db.execute(
        statement,
        {
            "rollback_value": log.get("old_value_json"),
            "updated_by": actor_user_id,
            "entity_id": log["entity_id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rollback target entity not found.")


def _insert_rollback_log(
    db: Session,
    original_log: dict[str, Any],
    *,
    current_value: Any,
    reason: str | None,
    actor_user_id: UUID,
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            insert into action_application_log (
              team_id, workspace_id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, edited_before_apply, can_rollback, metadata_json
            )
            values (
              :team_id, :workspace_id, :extracted_action_id, :business_update_id,
              :entity_type, :entity_id, :field_path,
              :old_value_json, :new_value_json, 'rollback', :source_id,
              :applied_by, false, false, :metadata_json
            )
            returning
              id, extracted_action_id, business_update_id,
              entity_type, entity_id, field_path,
              old_value_json, new_value_json, source_type, source_id,
              applied_by, applied_at::text as applied_at,
              edited_before_apply, can_rollback,
              rollback_at::text as rollback_at, metadata_json
            """
        ).bindparams(
            bindparam("old_value_json", type_=JSONB),
            bindparam("new_value_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "extracted_action_id": original_log.get("extracted_action_id"),
            "business_update_id": original_log.get("business_update_id"),
            "entity_type": original_log["entity_type"],
            "entity_id": original_log["entity_id"],
            "field_path": original_log["field_path"],
            "old_value_json": _json_safe(current_value),
            "new_value_json": original_log.get("old_value_json"),
            "source_id": original_log["id"],
            "applied_by": actor_user_id,
            "metadata_json": {
                "source": "update_log_rollback",
                "rolled_back_log_id": str(original_log["id"]),
                "rollback_reason": reason,
            },
        },
    ).mappings().one()
    return dict(row)


def _mark_log_rolled_back(db: Session, log_id: UUID) -> None:
    db.execute(
        text(
            """
            update action_application_log
            set rollback_at = now()
            where id = :log_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"log_id": log_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _mark_field_sources_ignored_after_rollback(db: Session, log: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            update field_value_source
            set review_status = 'ignored'
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
              and field_path = :field_path
              and source_type = :source_type
              and source_id = :source_id
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": log["entity_type"],
            "entity_id": log["entity_id"],
            "field_path": log["field_path"],
            "source_type": log.get("source_type"),
            "source_id": log.get("source_id"),
        },
    )


def _mark_action_rejected_after_rollback(
    db: Session,
    extracted_action_id: UUID,
    *,
    actor_user_id: UUID,
) -> None:
    db.execute(
        text(
            """
            update extracted_action
            set review_status = 'rejected',
                reviewed_by = :reviewed_by,
                reviewed_at = now()
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "reviewed_by": actor_user_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


def _enqueue_rebuild_after_rollback(db: Session, *, entity_type: str, entity_id: UUID) -> None:
    create_search_doc_rebuild_job(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        source="update_log_rollback",
    )


def _values_match_for_rollback(current_value: Any, logged_new_value: Any) -> bool:
    return _rollback_comparable(current_value) == _rollback_comparable(logged_new_value)


def _rollback_comparable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _rollback_comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rollback_comparable(item) for item in value]
    if isinstance(value, (Decimal, int, float)) and not isinstance(value, bool):
        try:
            return Decimal(str(value)).normalize()
        except InvalidOperation:
            return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return str(value) if value.__class__.__name__ == "Decimal" else value
