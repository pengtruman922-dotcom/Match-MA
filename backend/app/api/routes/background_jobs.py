from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser, require_admin
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.services.background_job_governance import (
    _archive_metadata,
    _compact_failure_job,
    _compact_queue_job,
    _debug_ref,
    _failure_category,
    _failure_group_item,
    _failure_job_type_item,
    _failure_summary_text,
    _failure_summary_totals,
    _ignore_metadata,
    _int_value,
    _job_archived,
    _job_failure_ignored,
    _job_test_data,
    _not_archived_sql,
    _not_failure_ignored_sql,
    _not_test_data_sql,
    _queue_health_status,
    _queue_summary_names,
    _queue_summary_totals,
    _retry_metadata,
    _test_data_metadata,
    _truncate_text,
    _unarchive_metadata,
    _unignore_metadata,
    _untest_data_metadata,
    _utc_now_text,
)


def _require_admin_route(current_user: CurrentUser) -> None:
    require_admin(current_user)


router = APIRouter(
    prefix="/background-jobs",
    tags=["background-jobs"],
    dependencies=[Depends(_require_admin_route)],
)


class BackgroundJobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=0, le=1000)
    queue_name: str = Field(default="default", min_length=1, max_length=80)
    entity_type: str | None = None
    entity_id: UUID | None = None
    idempotency_key: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class BackgroundJobIgnoreRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BackgroundJobArchiveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BackgroundJobTestDataRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=500)


class BackgroundJobOut(BaseModel):
    id: UUID
    job_type: str
    status: str
    priority: int
    queue_name: str
    entity_type: str | None
    entity_id: UUID | None
    idempotency_key: str | None
    payload_json: dict[str, Any]
    result_json: dict[str, Any]
    error_code: str | None
    error_message: str | None
    error_detail_json: dict[str, Any]
    attempt_count: int
    max_attempts: int
    run_after: str
    locked_by: str | None
    locked_at: str | None
    started_at: str | None
    finished_at: str | None
    parent_job_id: UUID | None
    correlation_id: UUID | None
    created_by: UUID | None
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class AiTraceOut(BaseModel):
    id: UUID
    trace_type: str
    node_name: str
    job_id: UUID | None
    correlation_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    provider_name: str | None
    model_name: str | None
    prompt_version: str | None
    status: str
    input_json: dict[str, Any]
    prompt_messages_json: list[Any]
    raw_output_text: str | None
    parsed_output_json: dict[str, Any] | None
    schema_validation_json: dict[str, Any]
    retrieval_output_json: dict[str, Any]
    tool_calls_json: list[Any]
    error_code: str | None
    error_message: str | None
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_json: dict[str, Any]
    started_at: str
    finished_at: str | None
    metadata_json: dict[str, Any]


class QueueSummaryOut(BaseModel):
    generated_at: str
    totals: dict[str, Any]
    queues: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class FailureSummaryOut(BaseModel):
    generated_at: str
    lookback_hours: int
    include_ignored: bool = False
    include_archived: bool = False
    include_test_data: bool = False
    totals: dict[str, Any]
    by_queue: list[dict[str, Any]]
    by_job_type: list[dict[str, Any]]
    recent_failures: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class BackgroundJobRetryPreviewOut(BaseModel):
    job: dict[str, Any]
    retry: dict[str, Any]
    related: dict[str, Any]
    effects: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class TaskCenterJobOut(BaseModel):
    id: UUID
    job_type: str
    task_display_name: str
    status: str
    priority: int | None
    queue_name: str | None
    entity_type: str | None
    entity_id: UUID | None
    related_object_name: str
    related_object_route: str | None
    initiated_by_user_id: UUID | None
    initiated_by_name: str
    initiated_by_username: str | None
    run_after: str | None
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    error_message: str | None
    failure_category: str
    failure_summary: str
    attempt_count: int | None
    max_attempts: int | None
    ignored: bool
    ignore_reason: str | None
    ignored_at: str | None
    archived: bool
    archive_reason: str | None
    archived_at: str | None
    is_test_data: bool
    test_data_label: str | None
    can_retry: bool
    retry_route: str | None
    ignore_route: str | None
    unignore_route: str | None
    debug_ref: dict[str, Any]
    related_entity_ref: dict[str, Any] | None


class TaskCenterOut(BaseModel):
    generated_at: str
    status_group: str
    lookback_hours: int
    limit: int
    offset: int
    totals: dict[str, Any]
    tasks: list[TaskCenterJobOut]


@router.post("", response_model=BackgroundJobOut, status_code=status.HTTP_201_CREATED)
def create_background_job(
    payload: BackgroundJobCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.execute(
        _job_returning_statement(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :job_type, :priority, :queue_name,
              :entity_type, :entity_id, :idempotency_key, :payload_json,
              :max_attempts, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": payload.job_type,
            "priority": payload.priority,
            "queue_name": payload.queue_name,
            "entity_type": payload.entity_type,
            "entity_id": payload.entity_id,
            "idempotency_key": payload.idempotency_key,
            "payload_json": payload.payload_json,
            "max_attempts": payload.max_attempts,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=list[BackgroundJobOut])
def list_background_jobs(
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    job_type: str | None = None,
    queue_name: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    include_ignored: bool = Query(default=False),
    include_archived: bool = Query(default=False),
    include_test_data: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if status_filter:
        where.append("status = :status")
        params["status"] = status_filter
        if status_filter == "failed" and not include_ignored:
            where.append(_not_failure_ignored_sql())
        if status_filter == "failed" and not include_archived:
            where.append(_not_archived_sql())
        if status_filter == "failed" and not include_test_data:
            where.append(_not_test_data_sql())
    if job_type:
        where.append("job_type = :job_type")
        params["job_type"] = job_type
    if queue_name:
        where.append("queue_name = :queue_name")
        params["queue_name"] = queue_name
    if entity_type:
        where.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if entity_id:
        where.append("entity_id = :entity_id")
        params["entity_id"] = entity_id

    rows = db.execute(
        text(
            f"""
            select {_job_select_columns()}
            from background_job
            where {' and '.join(where)}
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/summary/queues", response_model=QueueSummaryOut)
def get_background_job_queue_summary(
    db: Session = Depends(get_db),
    include_empty: bool = Query(default=True),
    include_ignored: bool = Query(default=False),
    include_archived: bool = Query(default=False),
    include_test_data: bool = Query(default=False),
    lookback_hours: int = Query(default=24, ge=1, le=168),
) -> dict[str, Any]:
    summary = _queue_summary(
        db,
        include_empty=include_empty,
        include_ignored=include_ignored,
        include_archived=include_archived,
        include_test_data=include_test_data,
        lookback_hours=lookback_hours,
    )
    return summary


@router.get("/summary/failures", response_model=FailureSummaryOut)
def get_background_job_failure_summary(
    db: Session = Depends(get_db),
    lookback_hours: int = Query(default=168, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=100),
    include_ignored: bool = Query(default=False),
    include_archived: bool = Query(default=False),
    include_test_data: bool = Query(default=False),
) -> dict[str, Any]:
    return _failure_summary(
        db,
        lookback_hours=lookback_hours,
        limit=limit,
        include_ignored=include_ignored,
        include_archived=include_archived,
        include_test_data=include_test_data,
    )


@router.get("/task-center", response_model=TaskCenterOut)
def get_task_center_jobs(
    db: Session = Depends(get_db),
    status_group: Literal["needs_attention", "active", "ignored", "archived", "failed", "all"] = Query(
        default="needs_attention"
    ),
    initiated_by_user_id: UUID | None = None,
    queue_name: str | None = None,
    job_type: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    lookback_hours: int = Query(default=720, ge=1, le=2160),
    include_test_data: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    where, params = _task_center_filter_clauses(
        initiated_by_user_id=initiated_by_user_id,
        queue_name=queue_name,
        job_type=job_type,
        q=q,
        lookback_hours=lookback_hours,
        include_test_data=include_test_data,
    )
    status_clause = _task_center_status_clause(status_group, include_test_data=include_test_data)
    rows = db.execute(
        text(
            f"""
            select {_task_center_select_columns()}
            from background_job bj
            {_task_center_joins()}
            where {' and '.join([*where, status_clause])}
            order by bj.updated_at desc, bj.created_at desc
            limit :limit offset :offset
            """
        ),
        {**params, "limit": limit, "offset": offset},
    ).mappings().all()
    generated_at = db.execute(text("select now()::text")).scalar_one()
    return {
        "generated_at": generated_at,
        "status_group": status_group,
        "lookback_hours": lookback_hours,
        "limit": limit,
        "offset": offset,
        "totals": _task_center_totals(db, where, params, include_test_data=include_test_data),
        "tasks": [_task_center_item(dict(row)) for row in rows],
    }


@router.get("/{job_id}", response_model=BackgroundJobOut)
def get_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_job_or_404(db, job_id)


@router.get("/{job_id}/retry-preview", response_model=BackgroundJobRetryPreviewOut)
def preview_background_job_retry(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    return _retry_preview(db, current)


@router.post("/{job_id}/cancel", response_model=BackgroundJobOut)
def cancel_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    if current["status"] == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Running jobs cannot be cancelled by the API yet.",
        )
    if current["status"] in {"succeeded", "cancelled"}:
        return current

    row = db.execute(
        _job_returning_statement(
            """
            update background_job
            set status = 'cancelled',
                locked_by = null,
                locked_at = null,
                updated_at = now(),
                finished_at = coalesce(finished_at, now())
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.post("/{job_id}/ignore", response_model=BackgroundJobOut)
def ignore_background_job(
    job_id: UUID,
    payload: BackgroundJobIgnoreRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = payload or BackgroundJobIgnoreRequest()
    current = _get_job_or_404(db, job_id)
    if current["status"] not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed or cancelled jobs can be marked ignored.",
        )

    metadata_json = _ignore_metadata(current.get("metadata_json"), reason=payload.reason)
    row = db.execute(
        _job_returning_statement(
            """
            update background_job
            set metadata_json = :metadata_json,
                updated_at = now()
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_json": metadata_json,
        },
    ).mappings().one()
    row_dict = dict(row)
    _mark_related_business_update_ignored(db, row_dict)
    db.commit()
    return row_dict


@router.post("/{job_id}/unignore", response_model=BackgroundJobOut)
def unignore_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    metadata_json = _unignore_metadata(current.get("metadata_json"))
    row = db.execute(
        _job_returning_statement(
            """
            update background_job
            set metadata_json = :metadata_json,
                updated_at = now()
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_json": metadata_json,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.post("/{job_id}/archive", response_model=BackgroundJobOut)
def archive_background_job(
    job_id: UUID,
    payload: BackgroundJobArchiveRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = payload or BackgroundJobArchiveRequest()
    current = _get_job_or_404(db, job_id)
    metadata_json = _archive_metadata(current.get("metadata_json"), reason=payload.reason)
    row = _update_job_metadata(db, job_id, metadata_json)
    db.commit()
    return row


@router.post("/{job_id}/unarchive", response_model=BackgroundJobOut)
def unarchive_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    metadata_json = _unarchive_metadata(current.get("metadata_json"))
    row = _update_job_metadata(db, job_id, metadata_json)
    db.commit()
    return row


@router.post("/{job_id}/mark-test-data", response_model=BackgroundJobOut)
def mark_background_job_test_data(
    job_id: UUID,
    payload: BackgroundJobTestDataRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = payload or BackgroundJobTestDataRequest()
    current = _get_job_or_404(db, job_id)
    metadata_json = _test_data_metadata(
        current.get("metadata_json"),
        label=payload.label,
        reason=payload.reason,
    )
    row = _update_job_metadata(db, job_id, metadata_json)
    db.commit()
    return row


@router.post("/{job_id}/unmark-test-data", response_model=BackgroundJobOut)
def unmark_background_job_test_data(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    metadata_json = _untest_data_metadata(current.get("metadata_json"))
    row = _update_job_metadata(db, job_id, metadata_json)
    db.commit()
    return row


@router.post("/{job_id}/retry", response_model=BackgroundJobOut)
def retry_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    if current["status"] not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed or cancelled jobs can be retried.",
        )

    metadata_json = _retry_metadata(current)
    row = db.execute(
        _job_returning_statement(
            """
            update background_job
            set status = 'queued',
                attempt_count = 0,
                run_after = now(),
                locked_by = null,
                locked_at = null,
                started_at = null,
                finished_at = null,
                error_code = null,
                error_message = null,
                error_detail_json = '{}'::jsonb,
                metadata_json = :metadata_json,
                updated_at = now()
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_json": metadata_json,
        },
    ).mappings().one()
    _mark_related_business_update_retrying(db, dict(row))
    db.commit()
    return dict(row)


@router.get("/{job_id}/traces", response_model=list[AiTraceOut])
def list_job_traces(
    job_id: UUID,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    _get_job_or_404(db, job_id)
    rows = db.execute(
        text(
            """
            select
              id, trace_type, node_name, job_id, correlation_id, entity_type, entity_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text, parsed_output_json,
              schema_validation_json, retrieval_output_json, tool_calls_json,
              error_code, error_message, latency_ms, prompt_tokens, completion_tokens,
              total_tokens, cost_json, started_at::text as started_at,
              finished_at::text as finished_at, metadata_json
            from ai_trace
            where job_id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by started_at desc
            limit :limit offset :offset
            """
        ),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _get_job_or_404(db: Session, job_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_job_select_columns()}
            from background_job
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Background job not found.")
    return dict(row)


def _retry_preview(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    can_retry = job.get("status") in {"failed", "cancelled"}
    related = _retry_preview_related(db, job)
    warnings = _retry_preview_warnings(job, related)
    effects = [
        {
            "key": "reset_job_state",
            "label": "Reset job to queued",
            "description": "Retry will set status=queued, attempt_count=0, run_after=now, and clear locks.",
        },
        {
            "key": "clear_current_error",
            "label": "Clear current error fields",
            "description": "The current error_code/error_message/error_detail_json will move into metadata as last_retry_previous_*.",
        },
    ]
    if _job_failure_ignored(job):
        effects.append(
            {
                "key": "clear_ignore_marker",
                "label": "Clear ignore marker",
                "description": "Retry removes failure_ignored metadata so the retried job can surface again if it fails.",
            }
        )
    if job.get("job_type") == "business_update_extract_actions":
        effects.append(
            {
                "key": "business_update_processing",
                "label": "Mark business update processing",
                "description": "The related business_update is marked processing so review-page actions are enabled while retry runs.",
            }
        )
    if job.get("job_type") in {
        "business_update_extract_actions",
        "seller_target_parse",
        "buyer_intent_parse",
    }:
        effects.append(
            {
                "key": "may_auto_apply",
                "label": "May auto-apply parsed fields",
                "description": "This job type can write entity fields automatically when extraction is valid and target binding is safe.",
            }
        )

    compact = _compact_failure_job(job) if job.get("status") in {"failed", "cancelled"} else _compact_queue_job(job)
    compact["payload_json"] = job.get("payload_json") or {}
    compact["metadata_json"] = job.get("metadata_json") or {}
    compact["result_json"] = job.get("result_json") or {}
    compact["error_detail_json"] = job.get("error_detail_json") or {}
    return {
        "job": compact,
        "retry": {
            "eligible": can_retry,
            "route": f"/background-jobs/{job['id']}/retry" if can_retry else None,
            "method": "POST" if can_retry else None,
            "queue_name": job.get("queue_name"),
            "will_reset_attempt_count_to": 0 if can_retry else None,
            "will_run_after": "now" if can_retry else None,
        },
        "related": related,
        "effects": effects,
        "warnings": warnings,
        "debug_ref": _debug_ref("background_job", job["id"]),
    }


def _retry_preview_related(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    entity_type = job.get("entity_type")
    entity_id = job.get("entity_id")
    related: dict[str, Any] = {
        "entity_ref": _debug_ref(entity_type, entity_id) if entity_type and entity_id else None,
        "same_entity_job_count": 0,
        "active_same_entity_job_count": 0,
        "trace_count": _count_job_traces(db, job["id"]),
    }
    if entity_type and entity_id:
        counts = _same_entity_job_counts(db, entity_type, entity_id)
        related.update(counts)
    if entity_type == "business_update" and entity_id:
        related["business_update"] = _business_update_retry_context(db, entity_id)
    return related


def _retry_preview_warnings(job: dict[str, Any], related: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if job.get("status") not in {"failed", "cancelled"}:
        warnings.append(
            {
                "key": "not_retryable_status",
                "severity": "blocker",
                "message": "Only failed or cancelled jobs can be retried.",
            }
        )
    if int(related.get("active_same_entity_job_count") or 0) > 0:
        warnings.append(
            {
                "key": "active_related_jobs",
                "severity": "warning",
                "message": "The related entity already has queued/running/retry_waiting jobs.",
            }
        )
    if related.get("trace_count") == 0:
        warnings.append(
            {
                "key": "no_trace",
                "severity": "info",
                "message": "No ai_trace exists for this job; retry may overwrite the visible failure state.",
            }
        )
    business_update = related.get("business_update") or {}
    if int(business_update.get("application_log_count") or 0) > 0:
        warnings.append(
            {
                "key": "existing_application_logs",
                "severity": "warning",
                "message": "The related business update already has application logs; review duplicate effects before retry.",
            }
        )
    return warnings


def _same_entity_job_counts(db: Session, entity_type: str, entity_id: UUID) -> dict[str, int]:
    row = db.execute(
        text(
            """
            select count(*)::int as same_entity_job_count,
                   count(*) filter (
                     where status in ('queued', 'running', 'retry_waiting')
                   )::int as active_same_entity_job_count
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ).mappings().one()
    return {
        "same_entity_job_count": int(row["same_entity_job_count"] or 0),
        "active_same_entity_job_count": int(row["active_same_entity_job_count"] or 0),
    }


def _business_update_retry_context(db: Session, business_update_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              bu.id,
              bu.processing_status,
              bu.created_at::text as created_at,
              bu.metadata_json,
              (select count(*)::int from extracted_action action
               where action.team_id = bu.team_id
                 and action.workspace_id = bu.workspace_id
                 and action.business_update_id = bu.id) as action_count,
              (select count(*)::int from action_application_log log
               where log.team_id = bu.team_id
                 and log.workspace_id = bu.workspace_id
                 and log.business_update_id = bu.id) as application_log_count
            from business_update bu
            where bu.id = :business_update_id
              and bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        return None
    item = dict(row)
    item["action_count"] = int(item.get("action_count") or 0)
    item["application_log_count"] = int(item.get("application_log_count") or 0)
    return item


def _count_job_traces(db: Session, job_id: UUID) -> int:
    return int(
        db.execute(
            text(
                """
                select count(*)::int
                from ai_trace
                where job_id = :job_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                """
            ),
            {
                "job_id": job_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).scalar_one()
        or 0
    )


def _update_job_metadata(db: Session, job_id: UUID, metadata_json: dict[str, Any]) -> dict[str, Any]:
    row = db.execute(
        _job_returning_statement(
            """
            update background_job
            set metadata_json = :metadata_json,
                updated_at = now()
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "job_id": job_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_json": metadata_json,
        },
    ).mappings().one()
    return dict(row)


def _mark_related_business_update_retrying(db: Session, job: dict[str, Any]) -> None:
    if job.get("job_type") != "business_update_extract_actions" or job.get("entity_type") != "business_update":
        return
    business_update_id = job.get("entity_id")
    if not business_update_id:
        return
    metadata_patch = {
        "last_retry_job_id": str(job["id"]),
        "last_retry_at": _utc_now_text(),
    }
    db.execute(
        text(
            """
            update business_update
            set processing_status = 'processing',
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": metadata_patch,
        },
    )


def _mark_related_business_update_ignored(db: Session, job: dict[str, Any]) -> None:
    if job.get("job_type") != "business_update_extract_actions" or job.get("entity_type") != "business_update":
        return
    business_update_id = job.get("entity_id")
    if not business_update_id:
        return
    metadata_patch = {
        "last_ignored_failed_job_id": str(job["id"]),
        "last_ignored_failed_job_at": _utc_now_text(),
    }
    db.execute(
        text(
            """
            update business_update
            set processing_status = case
                  when processing_status = 'processing' then 'failed'
                  else processing_status
                end,
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": metadata_patch,
        },
    )


def _queue_summary(
    db: Session,
    *,
    include_empty: bool,
    include_ignored: bool = False,
    include_archived: bool = False,
    include_test_data: bool = False,
    lookback_hours: int,
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            select
              coalesce(queue_name, 'default') as queue_name,
              count(*)::int as total_count,
              count(*) filter (where status = 'queued')::int as queued_count,
              count(*) filter (where status = 'retry_waiting')::int as retry_waiting_count,
              count(*) filter (where status = 'running')::int as running_count,
              count(*) filter (
                where status = 'failed'
                  and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
                  and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
                  and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
              )::int as failed_count,
              count(*) filter (
                where status = 'failed'
                  and coalesce(metadata_json ->> 'failure_ignored', 'false') = 'true'
              )::int as ignored_failed_count,
              count(*) filter (where status = 'succeeded')::int as succeeded_count,
              count(*) filter (where status = 'cancelled')::int as cancelled_count,
              count(*) filter (
                where created_at >= now() - (:lookback_hours * interval '1 hour')
              )::int as recent_created_count,
              count(*) filter (
                where finished_at >= now() - (:lookback_hours * interval '1 hour')
                  and status = 'succeeded'
              )::int as recent_succeeded_count,
              count(*) filter (
                where finished_at >= now() - (:lookback_hours * interval '1 hour')
                  and status = 'failed'
                  and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
                  and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
                  and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
              )::int as recent_failed_count,
              min(run_after) filter (where status in ('queued', 'retry_waiting'))::text as next_run_after,
              max(updated_at)::text as last_updated_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
            group by coalesce(queue_name, 'default')
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "lookback_hours": lookback_hours,
            "include_ignored": include_ignored,
            "include_archived": include_archived,
            "include_test_data": include_test_data,
        },
    ).mappings().all()
    queue_map = {str(row["queue_name"]): dict(row) for row in rows}
    queue_names = _queue_summary_names(queue_map.keys(), include_empty=include_empty)
    queues = [
        _queue_summary_item(
            db,
            queue_name=queue_name,
            row=queue_map.get(queue_name),
            include_ignored=include_ignored,
            include_archived=include_archived,
            include_test_data=include_test_data,
            lookback_hours=lookback_hours,
        )
        for queue_name in queue_names
    ]
    totals = _queue_summary_totals(queues)
    generated_at = db.execute(text("select now()::text")).scalar_one()
    return {
        "generated_at": generated_at,
        "totals": totals,
        "queues": queues,
        "debug_ref": {"route": "/debug/entities/background_job", "entity_type": "background_job"},
    }


def _failure_summary(
    db: Session,
    *,
    lookback_hours: int,
    limit: int,
    include_ignored: bool = False,
    include_archived: bool = False,
    include_test_data: bool = False,
) -> dict[str, Any]:
    params = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "lookback_hours": lookback_hours,
        "limit": limit,
        "include_ignored": include_ignored,
        "include_archived": include_archived,
        "include_test_data": include_test_data,
    }
    by_queue_rows = db.execute(
        text(
            """
            select queue_name, count(*)::int as failed_count, max(updated_at)::text as latest_failed_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status = 'failed'
              and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
              and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
              and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
              and updated_at >= now() - (:lookback_hours * interval '1 hour')
            group by queue_name
            order by failed_count desc, latest_failed_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    by_job_type_rows = db.execute(
        text(
            """
            select job_type, queue_name, count(*)::int as failed_count, max(updated_at)::text as latest_failed_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status = 'failed'
              and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
              and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
              and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
              and updated_at >= now() - (:lookback_hours * interval '1 hour')
            group by job_type, queue_name
            order by failed_count desc, latest_failed_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    recent_rows = db.execute(
        text(
            """
            select id, job_type, status, priority, queue_name, entity_type, entity_id,
                   run_after::text as run_after, created_at::text as created_at,
                   updated_at::text as updated_at, error_code, error_message,
                   attempt_count, max_attempts, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status = 'failed'
              and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
              and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
              and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
              and updated_at >= now() - (:lookback_hours * interval '1 hour')
            order by updated_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    by_queue = [_failure_group_item(dict(row), group_key="queue_name") for row in by_queue_rows]
    by_job_type = [_failure_job_type_item(dict(row)) for row in by_job_type_rows]
    recent_failures = [_compact_failure_job(dict(row)) for row in recent_rows]
    totals = _failure_summary_totals(by_queue=by_queue, by_job_type=by_job_type, recent_failures=recent_failures)
    generated_at = db.execute(text("select now()::text")).scalar_one()
    return {
        "generated_at": generated_at,
        "lookback_hours": lookback_hours,
        "include_ignored": include_ignored,
        "include_archived": include_archived,
        "include_test_data": include_test_data,
        "totals": totals,
        "by_queue": by_queue,
        "by_job_type": by_job_type,
        "recent_failures": recent_failures,
        "debug_ref": {"route": "/debug/entities/background_job", "entity_type": "background_job"},
    }


def _queue_summary_item(
    db: Session,
    *,
    queue_name: str,
    row: dict[str, Any] | None,
    include_ignored: bool,
    include_archived: bool,
    include_test_data: bool,
    lookback_hours: int,
) -> dict[str, Any]:
    counts = {
        "total": _int_value(row, "total_count"),
        "queued": _int_value(row, "queued_count"),
        "retry_waiting": _int_value(row, "retry_waiting_count"),
        "running": _int_value(row, "running_count"),
        "failed": _int_value(row, "failed_count"),
        "ignored_failed": _int_value(row, "ignored_failed_count"),
        "succeeded": _int_value(row, "succeeded_count"),
        "cancelled": _int_value(row, "cancelled_count"),
        "recent_created": _int_value(row, "recent_created_count"),
        "recent_succeeded": _int_value(row, "recent_succeeded_count"),
        "recent_failed": _int_value(row, "recent_failed_count"),
    }
    active_count = counts["queued"] + counts["retry_waiting"] + counts["running"]
    health_status = _queue_health_status(active_count=active_count, failed_count=counts["failed"])
    return {
        "queue_name": queue_name,
        "health_status": health_status,
        "active_count": active_count,
        "counts": counts,
        "lookback_hours": lookback_hours,
        "next_run_after": row.get("next_run_after") if row else None,
        "last_updated_at": row.get("last_updated_at") if row else None,
        "next_job": _queue_next_job(db, queue_name),
        "latest_failed_job": _queue_latest_failed_job(
            db,
            queue_name,
            include_ignored=include_ignored,
            include_archived=include_archived,
            include_test_data=include_test_data,
        ),
        "debug_ref": {
            "route": f"/background-jobs?queue_name={queue_name}",
            "entity_type": "background_job_queue",
            "entity_id": queue_name,
        },
    }


def _queue_next_job(db: Session, queue_name: str) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, priority, queue_name, entity_type, entity_id,
                   run_after::text as run_after, created_at::text as created_at,
                   updated_at::text as updated_at, error_message
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and queue_name = :queue_name
              and status in ('queued', 'retry_waiting')
            order by priority desc, run_after asc, created_at asc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "queue_name": queue_name,
        },
    ).mappings().one_or_none()
    return _compact_queue_job(dict(row)) if row else None


def _queue_latest_failed_job(
    db: Session,
    queue_name: str,
    *,
    include_ignored: bool = False,
    include_archived: bool = False,
    include_test_data: bool = False,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, priority, queue_name, entity_type, entity_id,
                   run_after::text as run_after, created_at::text as created_at,
                   updated_at::text as updated_at, error_message, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and queue_name = :queue_name
              and status = 'failed'
              and (:include_ignored or coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true')
              and (:include_archived or coalesce(metadata_json ->> 'archived', 'false') <> 'true')
              and (:include_test_data or coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true')
            order by updated_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "queue_name": queue_name,
            "include_ignored": include_ignored,
            "include_archived": include_archived,
            "include_test_data": include_test_data,
        },
    ).mappings().one_or_none()
    return _compact_queue_job(dict(row)) if row else None


def _task_center_filter_clauses(
    *,
    initiated_by_user_id: UUID | None,
    queue_name: str | None,
    job_type: str | None,
    q: str | None,
    lookback_hours: int,
    include_test_data: bool,
) -> tuple[list[str], dict[str, Any]]:
    where = [
        "bj.team_id = :team_id",
        "bj.workspace_id = :workspace_id",
        "bj.updated_at >= now() - (:lookback_hours * interval '1 hour')",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "lookback_hours": lookback_hours,
    }
    if initiated_by_user_id:
        where.append("bj.created_by = :initiated_by_user_id")
        params["initiated_by_user_id"] = initiated_by_user_id
    if queue_name:
        where.append("bj.queue_name = :queue_name")
        params["queue_name"] = queue_name
    if job_type:
        where.append("bj.job_type = :job_type")
        params["job_type"] = job_type
    if not include_test_data:
        where.append("coalesce(bj.metadata_json ->> 'is_test_data', 'false') <> 'true'")
    if q and q.strip():
        where.append(
            """
            (
              bj.id::text ilike :q
              or bj.job_type ilike :q
              or coalesce(st.target_name, '') ilike :q
              or coalesce(bp.buyer_name, '') ilike :q
              or coalesce(bi.intent_name, '') ilike :q
              or coalesce(bip.buyer_name, '') ilike :q
              or coalesce(a.file_name, '') ilike :q
              or coalesce(bu.raw_text, '') ilike :q
              or coalesce(au.name, '') ilike :q
              or coalesce(au.username, '') ilike :q
            )
            """
        )
        params["q"] = f"%{q.strip()}%"
    return where, params


def _task_center_status_clause(
    status_group: str,
    *,
    include_test_data: bool,
) -> str:
    test_data_clause = "" if include_test_data else "and coalesce(bj.metadata_json ->> 'is_test_data', 'false') <> 'true'"
    if status_group == "needs_attention":
        return f"""
          bj.status = 'failed'
          and coalesce(bj.metadata_json ->> 'failure_ignored', 'false') <> 'true'
          and coalesce(bj.metadata_json ->> 'archived', 'false') <> 'true'
          {test_data_clause}
        """
    if status_group == "active":
        return "bj.status in ('queued', 'running', 'retry_waiting')"
    if status_group == "ignored":
        return "bj.status = 'failed' and coalesce(bj.metadata_json ->> 'failure_ignored', 'false') = 'true'"
    if status_group == "archived":
        return "coalesce(bj.metadata_json ->> 'archived', 'false') = 'true'"
    if status_group == "failed":
        return f"bj.status = 'failed' {test_data_clause}"
    return "true"


def _task_center_joins() -> str:
    return """
      left join app_user au on au.id = bj.created_by
      left join seller_target st on bj.entity_type = 'seller_target' and st.id = bj.entity_id
      left join buyer_party bp on bj.entity_type = 'buyer_party' and bp.id = bj.entity_id
      left join buyer_intent bi on bj.entity_type = 'buyer_intent' and bi.id = bj.entity_id
      left join buyer_party bip on bip.id = bi.buyer_party_id
      left join attachment a on bj.entity_type = 'attachment' and a.id = bj.entity_id
      left join business_update bu on bj.entity_type = 'business_update' and bu.id = bj.entity_id
      left join recommendation_session rs on bj.entity_type = 'recommendation_session' and rs.id = bj.entity_id
      left join buyer_intent rs_bi on rs_bi.id = rs.buyer_intent_id
      left join buyer_party rs_bp on rs_bp.id = rs.buyer_party_id
      left join seller_target rs_st on rs_st.id = rs.seller_target_id
    """


def _task_center_select_columns() -> str:
    return """
      bj.id, bj.job_type, bj.status, bj.priority, bj.queue_name, bj.entity_type, bj.entity_id,
      bj.run_after::text as run_after, bj.created_at::text as created_at,
      bj.updated_at::text as updated_at, bj.started_at::text as started_at,
      bj.finished_at::text as finished_at, bj.error_code, bj.error_message,
      bj.attempt_count, bj.max_attempts, bj.metadata_json,
      bj.created_by as initiated_by_user_id,
      au.name as initiated_by_name,
      au.username as initiated_by_username,
      coalesce(
        st.target_name,
        bp.buyer_name,
        nullif(concat_ws(' / ', bip.buyer_name, bi.intent_name), ''),
        a.file_name,
        nullif(trim(left(bu.raw_text, 80)), ''),
        nullif(concat_ws(' / ', rs_bp.buyer_name, rs_bi.intent_name), ''),
        rs_st.target_name
      ) as related_object_name
    """


def _task_center_totals(
    db: Session,
    where: list[str],
    params: dict[str, Any],
    *,
    include_test_data: bool,
) -> dict[str, Any]:
    base_where = " and ".join(where)
    test_data_clause = "" if include_test_data else "and coalesce(bj.metadata_json ->> 'is_test_data', 'false') <> 'true'"
    row = db.execute(
        text(
            f"""
            select
              count(*)::int as total_count,
              count(*) filter (
                where bj.status = 'failed'
                  and coalesce(bj.metadata_json ->> 'failure_ignored', 'false') <> 'true'
                  and coalesce(bj.metadata_json ->> 'archived', 'false') <> 'true'
                  {test_data_clause}
              )::int as needs_attention_count,
              count(*) filter (where bj.status in ('queued', 'running', 'retry_waiting'))::int as active_count,
              count(*) filter (
                where bj.status = 'failed'
                  and coalesce(bj.metadata_json ->> 'failure_ignored', 'false') = 'true'
              )::int as ignored_count,
              count(*) filter (
                where coalesce(bj.metadata_json ->> 'archived', 'false') = 'true'
              )::int as archived_count,
              count(*) filter (where bj.status = 'failed' {test_data_clause})::int as failed_count
            from background_job bj
            {_task_center_joins()}
            where {base_where}
            """
        ),
        params,
    ).mappings().one()
    return {key: int(value or 0) for key, value in dict(row).items()}


def _task_center_item(row: dict[str, Any]) -> dict[str, Any]:
    metadata_json = row.get("metadata_json") or {}
    ignored = _job_failure_ignored(row)
    archived = _job_archived(row)
    is_test_data = _job_test_data(row)
    can_retry = row.get("status") in {"failed", "cancelled"}
    failure_category = _failure_category(row.get("error_code"), row.get("error_message"))
    entity_type = row.get("entity_type")
    entity_id = row.get("entity_id")
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "task_display_name": _task_display_name(row.get("job_type")),
        "status": row["status"],
        "priority": row.get("priority"),
        "queue_name": row.get("queue_name"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "related_object_name": _related_object_display_name(row),
        "related_object_route": _related_object_route(entity_type, entity_id),
        "initiated_by_user_id": row.get("initiated_by_user_id"),
        "initiated_by_name": _initiated_by_name(row),
        "initiated_by_username": row.get("initiated_by_username"),
        "run_after": row.get("run_after"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "error_code": row.get("error_code"),
        "error_message": _truncate_text(row.get("error_message"), 2000),
        "failure_category": failure_category,
        "failure_summary": _failure_summary_text(failure_category, row.get("error_message")),
        "attempt_count": row.get("attempt_count"),
        "max_attempts": row.get("max_attempts"),
        "ignored": ignored,
        "ignore_reason": metadata_json.get("failure_ignore_reason"),
        "ignored_at": metadata_json.get("failure_ignored_at"),
        "archived": archived,
        "archive_reason": metadata_json.get("archive_reason"),
        "archived_at": metadata_json.get("archived_at"),
        "is_test_data": is_test_data,
        "test_data_label": metadata_json.get("test_data_label"),
        "can_retry": can_retry,
        "retry_route": f"/background-jobs/{row['id']}/retry" if can_retry else None,
        "ignore_route": None if ignored else f"/background-jobs/{row['id']}/ignore",
        "unignore_route": f"/background-jobs/{row['id']}/unignore" if ignored else None,
        "debug_ref": _debug_ref("background_job", row["id"]),
        "related_entity_ref": _debug_ref(entity_type, entity_id) if entity_type and entity_id else None,
    }


def _task_display_name(job_type: Any) -> str:
    labels = {
        "business_update_extract_actions": "业务更新解析",
        "seller_target_parse": "标的解析",
        "buyer_intent_parse": "买家意向解析",
        "attachment_ocr_parse": "附件 OCR 解析",
        "attachment_ocr_poll": "OCR 结果轮询",
        "seller_search_doc_rebuild": "标的搜索索引重建",
        "buyer_intent_search_doc_rebuild": "买家意向搜索索引重建",
        "embedding_generate": "向量生成",
        "recommendation_report_generate": "推荐报告生成",
        "recommendation_rerank": "推荐重排",
        "model_node_test": "模型节点测试",
    }
    job_type_text = str(job_type or "unknown")
    return labels.get(job_type_text, job_type_text)


def _related_object_display_name(row: dict[str, Any]) -> str:
    name = _truncate_text(row.get("related_object_name"), 120)
    if name:
        return name
    entity_type = row.get("entity_type")
    entity_id = row.get("entity_id")
    if entity_type and entity_id:
        return f"{entity_type} / {str(entity_id)[:8]}"
    return "未关联对象"


def _related_object_route(entity_type: Any, entity_id: Any) -> str | None:
    if not entity_type or not entity_id:
        return None
    entity_id_text = str(entity_id)
    routes = {
        "seller_target": f"/targets/{entity_id_text}",
        "buyer_party": f"/buyers/{entity_id_text}",
        "buyer_intent": f"/buyer-intents/{entity_id_text}",
        "business_update": f"/updates/{entity_id_text}",
        "recommendation_session": "/recommendations",
    }
    return routes.get(str(entity_type))


def _initiated_by_name(row: dict[str, Any]) -> str:
    if row.get("initiated_by_name"):
        return str(row["initiated_by_name"])
    if row.get("initiated_by_user_id"):
        return "系统/历史"
    return "未知"


def _job_select_columns() -> str:
    return """
      id, job_type, status, priority, queue_name, entity_type, entity_id,
      idempotency_key, payload_json, result_json, error_code, error_message,
      error_detail_json, attempt_count, max_attempts, run_after::text as run_after,
      locked_by, locked_at::text as locked_at, started_at::text as started_at,
      finished_at::text as finished_at, parent_job_id, correlation_id, created_by,
      created_at::text as created_at, updated_at::text as updated_at, metadata_json
    """


def _job_returning_statement(prefix_sql: str):
    return text(
        f"""
        {prefix_sql}
        returning {_job_select_columns()}
        """
    )
