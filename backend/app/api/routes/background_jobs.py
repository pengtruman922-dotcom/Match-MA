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
