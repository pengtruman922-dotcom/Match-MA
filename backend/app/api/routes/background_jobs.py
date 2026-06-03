from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    lookback_hours: int = Query(default=24, ge=1, le=168),
) -> dict[str, Any]:
    summary = _queue_summary(db, include_empty=include_empty, lookback_hours=lookback_hours)
    return summary


@router.get("/{job_id}", response_model=BackgroundJobOut)
def get_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_job_or_404(db, job_id)


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


@router.post("/{job_id}/retry", response_model=BackgroundJobOut)
def retry_background_job(job_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_job_or_404(db, job_id)
    if current["status"] not in {"failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed or cancelled jobs can be retried.",
        )

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
                updated_at = now()
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


def _queue_summary(db: Session, *, include_empty: bool, lookback_hours: int) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            select
              coalesce(queue_name, 'default') as queue_name,
              count(*)::int as total_count,
              count(*) filter (where status = 'queued')::int as queued_count,
              count(*) filter (where status = 'retry_waiting')::int as retry_waiting_count,
              count(*) filter (where status = 'running')::int as running_count,
              count(*) filter (where status = 'failed')::int as failed_count,
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
        },
    ).mappings().all()
    queue_map = {str(row["queue_name"]): dict(row) for row in rows}
    queue_names = _queue_summary_names(queue_map.keys(), include_empty=include_empty)
    queues = [
        _queue_summary_item(
            db,
            queue_name=queue_name,
            row=queue_map.get(queue_name),
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


def _queue_summary_names(queue_names: Any, *, include_empty: bool) -> list[str]:
    defaults = ["llm", "ocr", "embedding", "rerank", "default"]
    names = list(dict.fromkeys([*defaults, *[str(item) for item in queue_names]]))
    return names if include_empty else [name for name in names if name not in defaults or name in queue_names]


def _queue_summary_item(
    db: Session,
    *,
    queue_name: str,
    row: dict[str, Any] | None,
    lookback_hours: int,
) -> dict[str, Any]:
    counts = {
        "total": _int_value(row, "total_count"),
        "queued": _int_value(row, "queued_count"),
        "retry_waiting": _int_value(row, "retry_waiting_count"),
        "running": _int_value(row, "running_count"),
        "failed": _int_value(row, "failed_count"),
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
        "latest_failed_job": _queue_latest_failed_job(db, queue_name),
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


def _queue_latest_failed_job(db: Session, queue_name: str) -> dict[str, Any] | None:
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
              and status = 'failed'
            order by updated_at desc
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


def _queue_summary_totals(queues: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "queue_count": len(queues),
        "active_queue_count": 0,
        "failed_queue_count": 0,
        "active_job_count": 0,
        "failed_job_count": 0,
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
