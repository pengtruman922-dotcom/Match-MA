from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID


@dataclass(frozen=True)
class JobClaim:
    id: UUID
    job_type: str
    queue_name: str
    payload_json: dict[str, Any]
    attempt_count: int
    max_attempts: int


def claim_next_job(db: Session, *, worker_id: str, queue_name: str = "default") -> JobClaim | None:
    # Row locking lets multiple workers poll PostgreSQL without claiming the same job.
    row = db.execute(
        text(
            """
            select id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and queue_name = :queue_name
              and status in ('queued', 'retry_waiting')
              and run_after <= now()
            order by priority asc, created_at asc
            limit 1
            for update skip locked
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "queue_name": queue_name,
        },
    ).mappings().one_or_none()
    if row is None:
        return None

    claimed = db.execute(
        text(
            """
            update background_job
            set status = 'running',
                locked_by = :worker_id,
                locked_at = now(),
                started_at = coalesce(started_at, now()),
                attempt_count = attempt_count + 1,
                updated_at = now()
            where id = :job_id
            returning id, job_type, queue_name, payload_json, attempt_count, max_attempts
            """
        ),
        {"worker_id": worker_id, "job_id": row["id"]},
    ).mappings().one()
    db.commit()
    return JobClaim(**dict(claimed))


def mark_job_succeeded(db: Session, *, job_id: UUID, result_json: dict[str, Any] | None = None) -> None:
    db.execute(
        text(
            """
            update background_job
            set status = 'succeeded',
                result_json = :result_json,
                locked_by = null,
                locked_at = null,
                finished_at = now(),
                updated_at = now(),
                error_code = null,
                error_message = null,
                error_detail_json = '{}'::jsonb
            where id = :job_id
            """
        ).bindparams(bindparam("result_json", type_=JSONB)),
        {"job_id": job_id, "result_json": result_json or {}},
    )
    db.commit()


def mark_job_failed(
    db: Session,
    *,
    job_id: UUID,
    error_message: str,
    error_code: str = "job_failed",
    error_detail_json: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            """
            update background_job
            set status = case
                  when attempt_count < max_attempts then 'retry_waiting'
                  else 'failed'
                end,
                run_after = case
                  when attempt_count < max_attempts then now() + interval '60 seconds'
                  else run_after
                end,
                locked_by = null,
                locked_at = null,
                finished_at = case
                  when attempt_count < max_attempts then null
                  else now()
                end,
                updated_at = now(),
                error_code = :error_code,
                error_message = :error_message,
                error_detail_json = :error_detail_json
            where id = :job_id
            """
        ).bindparams(bindparam("error_detail_json", type_=JSONB)),
        {
            "job_id": job_id,
            "error_code": error_code,
            "error_message": error_message,
            "error_detail_json": error_detail_json or {},
        },
    )
    db.commit()
