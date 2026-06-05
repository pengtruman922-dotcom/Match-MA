from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/background-jobs", tags=["background-jobs"])


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


def _retry_metadata(job: dict[str, Any]) -> dict[str, Any]:
    metadata = _without_keys(
        job.get("metadata_json"),
        {"failure_ignored", "failure_ignored_at", "failure_ignored_by", "failure_ignore_reason"},
    )
    metadata.update(
        {
            "last_retry_at": _utc_now_text(),
            "last_retry_by": str(DEFAULT_ADMIN_USER_ID),
            "last_retry_previous_status": job.get("status"),
            "last_retry_previous_error_code": job.get("error_code"),
            "last_retry_previous_error_message": _truncate_text(job.get("error_message"), 2000) or "",
            "last_retry_previous_attempt_count": job.get("attempt_count"),
        }
    )
    return metadata


def _ignore_metadata(metadata_json: Any, *, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "failure_ignored": True,
            "failure_ignored_at": _utc_now_text(),
            "failure_ignored_by": str(DEFAULT_ADMIN_USER_ID),
            "failure_ignore_reason": reason,
        }
    )
    return metadata


def _unignore_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(
        metadata_json,
        {"failure_ignored", "failure_ignored_at", "failure_ignored_by", "failure_ignore_reason"},
    )
    metadata.update(
        {
            "failure_unignored_at": _utc_now_text(),
            "failure_unignored_by": str(DEFAULT_ADMIN_USER_ID),
        }
    )
    return metadata


def _archive_metadata(metadata_json: Any, *, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "archived": True,
            "archived_at": _utc_now_text(),
            "archived_by": str(DEFAULT_ADMIN_USER_ID),
            "archive_reason": reason,
        }
    )
    return metadata


def _unarchive_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(metadata_json, {"archived", "archived_at", "archived_by", "archive_reason"})
    metadata.update({"unarchived_at": _utc_now_text(), "unarchived_by": str(DEFAULT_ADMIN_USER_ID)})
    return metadata


def _test_data_metadata(metadata_json: Any, *, label: str | None, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "is_test_data": True,
            "test_data_marked_at": _utc_now_text(),
            "test_data_marked_by": str(DEFAULT_ADMIN_USER_ID),
            "test_data_label": label,
            "test_data_reason": reason,
        }
    )
    return metadata


def _untest_data_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(
        metadata_json,
        {
            "is_test_data",
            "test_data_marked_at",
            "test_data_marked_by",
            "test_data_label",
            "test_data_reason",
        },
    )
    metadata.update({"test_data_unmarked_at": _utc_now_text(), "test_data_unmarked_by": str(DEFAULT_ADMIN_USER_ID)})
    return metadata


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


def _without_keys(metadata_json: Any, keys: set[str]) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    for key in keys:
        metadata.pop(key, None)
    return metadata


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


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


def _failure_group_item(row: dict[str, Any], *, group_key: str) -> dict[str, Any]:
    group_value = str(row.get(group_key) or "unknown")
    return {
        group_key: group_value,
        "failed_count": int(row.get("failed_count") or 0),
        "latest_failed_at": row.get("latest_failed_at"),
        "list_route": f"/background-jobs?status=failed&{group_key}={group_value}",
    }


def _failure_job_type_item(row: dict[str, Any]) -> dict[str, Any]:
    item = _failure_group_item(row, group_key="job_type")
    item["queue_name"] = row.get("queue_name")
    item["list_route"] = f"/background-jobs?status=failed&job_type={item['job_type']}"
    return item


def _compact_failure_job(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_queue_job(row)
    ignored = _job_failure_ignored(row)
    archived = _job_archived(row)
    test_data = _job_test_data(row)
    metadata_json = row.get("metadata_json") or {}
    can_retry = row.get("status") in {"failed", "cancelled"}
    failure_category = _failure_category(row.get("error_code"), row.get("error_message"))
    compact["error_code"] = row.get("error_code")
    compact["failure_category"] = failure_category
    compact["failure_summary"] = _failure_summary_text(failure_category, row.get("error_message"))
    compact["attempt_count"] = row.get("attempt_count")
    compact["max_attempts"] = row.get("max_attempts")
    compact["error_message"] = _truncate_text(row.get("error_message"), 500)
    compact["related_entity_ref"] = _debug_ref(row.get("entity_type"), row.get("entity_id")) if row.get("entity_type") and row.get("entity_id") else None
    compact["ignored"] = ignored
    compact["ignore_reason"] = metadata_json.get("failure_ignore_reason")
    compact["ignored_at"] = metadata_json.get("failure_ignored_at")
    compact["archived"] = archived
    compact["archive_reason"] = metadata_json.get("archive_reason")
    compact["archived_at"] = metadata_json.get("archived_at")
    compact["is_test_data"] = test_data
    compact["test_data_label"] = metadata_json.get("test_data_label")
    compact["test_data_reason"] = metadata_json.get("test_data_reason")
    compact["can_retry"] = can_retry
    compact["retry_route"] = f"/background-jobs/{row['id']}/retry" if can_retry else None
    compact["retry_preview_route"] = f"/background-jobs/{row['id']}/retry-preview" if can_retry else None
    compact["ignore_route"] = None if ignored else f"/background-jobs/{row['id']}/ignore"
    compact["unignore_route"] = f"/background-jobs/{row['id']}/unignore" if ignored else None
    compact["archive_route"] = None if archived else f"/background-jobs/{row['id']}/archive"
    compact["unarchive_route"] = f"/background-jobs/{row['id']}/unarchive" if archived else None
    compact["mark_test_data_route"] = None if test_data else f"/background-jobs/{row['id']}/mark-test-data"
    compact["unmark_test_data_route"] = f"/background-jobs/{row['id']}/unmark-test-data" if test_data else None
    compact["recommended_actions"] = _failure_recommended_actions(compact)
    return compact


def _failure_category(error_code: Any, error_message: Any) -> str:
    code = str(error_code or "").lower()
    message = str(error_message or "").lower()
    if "checkviolation" in message or "violates check constraint" in message:
        return "db_constraint"
    if "not defined" in message or "nameerror" in message or code in {"name_error", "code_error"}:
        return "code_error"
    if "schema" in message or "invalid" in message or code in {"schema_validation_failed", "invalid_output"}:
        return "schema_validation"
    if (
        "unauthorized" in message
        or "authentication" in message
        or "认证失败" in message
        or "http 401" in message
        or code in {"auth_failed", "unauthorized"}
    ):
        return "provider_auth"
    if "llm" in message or "provider" in message or "http " in message or code in {"llm_failed", "provider_failed"}:
        return "provider_or_llm"
    if code:
        return code
    return "unknown"


def _failure_summary_text(category: str, error_message: Any) -> str:
    message = _truncate_text(error_message, 240)
    if category == "db_constraint":
        return "Database constraint failed while applying extracted data. Check enum/normalized field values."
    if category == "code_error":
        return "Backend code error occurred while running the job. Check deploy version and stack trace."
    if category == "schema_validation":
        return "AI output or extracted action payload failed validation. Check trace output and prompt/schema."
    if category == "provider_auth":
        return "Provider authentication failed. Check API key formatting, secret binding, and provider account status."
    if category == "provider_or_llm":
        return "Model provider call failed or returned an unusable response. Check model config and trace."
    return message or "Job failed without a detailed error message."


def _failure_recommended_actions(job: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "key": "open_debug",
            "label": "Open Debug",
            "route": job["debug_ref"]["route"],
        }
    ]
    if job.get("related_entity_ref"):
        actions.append(
            {
                "key": "open_related_entity",
                "label": "Open Related Entity",
                "route": job["related_entity_ref"]["route"],
            }
        )
    if job.get("can_retry"):
        actions.append(
            {
                "key": "preview_retry",
                "label": "Preview Retry",
                "route": job.get("retry_preview_route"),
                "method": "GET",
            }
        )
    if job.get("can_retry"):
        actions.append(
            {
                "key": "retry_job",
                "label": "Retry Job",
                "route": job.get("retry_route"),
                "method": "POST",
            }
        )
    if job.get("ignored"):
        actions.append(
            {
                "key": "unignore_job",
                "label": "Unignore Job",
                "route": job.get("unignore_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "ignore_job",
                "label": "Ignore Job",
                "route": job.get("ignore_route"),
                "method": "POST",
            }
        )
    if job.get("archived"):
        actions.append(
            {
                "key": "unarchive_job",
                "label": "Unarchive Job",
                "route": job.get("unarchive_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "archive_job",
                "label": "Archive Job",
                "route": job.get("archive_route"),
                "method": "POST",
            }
        )
    if job.get("is_test_data"):
        actions.append(
            {
                "key": "unmark_test_data",
                "label": "Unmark Test Data",
                "route": job.get("unmark_test_data_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "mark_test_data",
                "label": "Mark Test Data",
                "route": job.get("mark_test_data_route"),
                "method": "POST",
            }
        )
    return actions


def _failure_summary_totals(
    *,
    by_queue: list[dict[str, Any]],
    by_job_type: list[dict[str, Any]],
    recent_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "failed_job_count": sum(int(item.get("failed_count") or 0) for item in by_queue),
        "failed_queue_count": len(by_queue),
        "failed_job_type_count": len(by_job_type),
        "recent_failure_count": len(recent_failures),
    }


def _queue_summary_names(queue_names: Any, *, include_empty: bool) -> list[str]:
    defaults = ["llm", "ocr", "embedding", "rerank", "default"]
    names = list(dict.fromkeys([*defaults, *[str(item) for item in queue_names]]))
    return names if include_empty else [name for name in names if name not in defaults or name in queue_names]


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


def _queue_health_status(*, active_count: int, failed_count: int) -> str:
    if failed_count:
        return "has_failures"
    if active_count:
        return "active"
    return "idle"


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


def _compact_queue_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "priority": row.get("priority"),
        "queue_name": row.get("queue_name"),
        "entity_type": row.get("entity_type"),
        "entity_id": row.get("entity_id"),
        "run_after": row.get("run_after"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "error_message": row.get("error_message"),
        "debug_ref": _debug_ref("background_job", row["id"]),
    }


def _job_failure_ignored(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("failure_ignored") is True


def _job_archived(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("archived") is True


def _job_test_data(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("is_test_data") is True


def _not_failure_ignored_sql() -> str:
    return "coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true'"


def _not_archived_sql() -> str:
    return "coalesce(metadata_json ->> 'archived', 'false') <> 'true'"


def _not_test_data_sql() -> str:
    return "coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true'"


def _queue_summary_totals(queues: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "queue_count": len(queues),
        "active_queue_count": 0,
        "failed_queue_count": 0,
        "active_job_count": 0,
        "failed_job_count": 0,
        "ignored_failed_job_count": 0,
        "queued_job_count": 0,
        "running_job_count": 0,
        "retry_waiting_job_count": 0,
    }
    for queue in queues:
        counts = queue.get("counts") or {}
        if queue.get("active_count"):
            totals["active_queue_count"] += 1
        if counts.get("failed"):
            totals["failed_queue_count"] += 1
        totals["active_job_count"] += int(queue.get("active_count") or 0)
        totals["failed_job_count"] += int(counts.get("failed") or 0)
        totals["ignored_failed_job_count"] += int(counts.get("ignored_failed") or 0)
        totals["queued_job_count"] += int(counts.get("queued") or 0)
        totals["running_job_count"] += int(counts.get("running") or 0)
        totals["retry_waiting_job_count"] += int(counts.get("retry_waiting") or 0)
    return totals


def _int_value(row: dict[str, Any] | None, key: str) -> int:
    if row is None:
        return 0
    value = row.get(key)
    return int(value) if value is not None else 0


def _debug_ref(entity_type: str, entity_id: Any) -> dict[str, str]:
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."


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
