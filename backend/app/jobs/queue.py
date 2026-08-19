from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.json_values import json_safe_value


@dataclass(frozen=True)
class JobClaim:
    id: UUID
    job_type: str
    queue_name: str
    entity_type: str | None
    entity_id: UUID | None
    correlation_id: UUID | None
    payload_json: dict[str, Any]
    attempt_count: int
    max_attempts: int




def requeue_stale_running_jobs(
    db: Session,
    *,
    queue_name: str = "default",
    stale_after_seconds: int = 300,
) -> int:
    result = db.execute(
        text(
            """
            update background_job
            set status = case
                  when attempt_count < max_attempts then 'retry_waiting'
                  else 'failed'
                end,
                run_after = case
                  when attempt_count < max_attempts then now()
                  else run_after
                end,
                locked_by = null,
                locked_at = null,
                finished_at = case
                  when attempt_count < max_attempts then null
                  else now()
                end,
                updated_at = now(),
                error_code = case
                  when attempt_count < max_attempts then error_code
                  else coalesce(error_code, 'stale_running_job')
                end,
                error_message = case
                  when attempt_count < max_attempts then error_message
                  else coalesce(error_message, 'Running job exceeded stale lock timeout.')
                end,
                error_detail_json = error_detail_json || jsonb_build_object(
                  'stale_requeued_at', now()::text,
                  'stale_after_seconds', :stale_after_seconds
                )
            where team_id = :team_id
              and workspace_id = :workspace_id
              and queue_name = :queue_name
              and status = 'running'
              and locked_at < now() - (:stale_after_seconds * interval '1 second')
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "queue_name": queue_name,
            "stale_after_seconds": stale_after_seconds,
        },
    )
    db.commit()
    return int(result.rowcount or 0)


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
            returning
              id, job_type, queue_name, entity_type, entity_id, correlation_id,
              payload_json, attempt_count, max_attempts
            """
        ),
        {"worker_id": worker_id, "job_id": row["id"]},
    ).mappings().one()
    db.commit()
    return JobClaim(**dict(claimed))


def mark_job_succeeded(
    db: Session,
    *,
    job_id: UUID,
    result_json: dict[str, Any] | None = None,
) -> None:
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
                -- 成功会清空 error_message，于是"重试过、上一次为什么失败"就此
                -- 失传，只剩 attempt_count 一个光秃秃的数字。失败历史必须留下。
                error_detail_json = case
                  when error_detail_json ? 'previous_failures'
                  then jsonb_build_object(
                    'previous_failures', error_detail_json -> 'previous_failures'
                  )
                  else '{}'::jsonb
                end
            where id = :job_id
            """
        ).bindparams(bindparam("result_json", type_=JSONB)),
        {"job_id": job_id, "result_json": json_safe_value(result_json or {})},
    )
    db.commit()


def mark_job_failed(
    db: Session,
    *,
    job_id: UUID,
    error_message: str,
    error_code: str = "job_failed",
    error_detail_json: dict[str, Any] | None = None,
    retry_allowed: bool = True,
) -> None:
    db.execute(
        text(
            """
            update background_job
            set status = case
                  when :retry_allowed and attempt_count < max_attempts then 'retry_waiting'
                  else 'failed'
                end,
                run_after = case
                  when :retry_allowed and attempt_count < max_attempts then now() + interval '60 seconds'
                  else run_after
                end,
                locked_by = null,
                locked_at = null,
                finished_at = case
                  when :retry_allowed and attempt_count < max_attempts then null
                  else now()
                end,
                updated_at = now(),
                error_code = :error_code,
                error_message = :error_message,
                -- cast 不能省：jsonb_build_object 是变参 "any"，Postgres 推不出
                -- 裸参数的类型，会抛 AmbiguousParameter。而这个异常发生在 worker
                -- 记录失败的路上，抛出去就会带走整个进程，任务停在 running 直到
                -- stale 清扫器把它判死 —— 真实的失败原因永远丢失。
                error_detail_json = :error_detail_json || jsonb_build_object(
                  'previous_failures',
                  coalesce(error_detail_json -> 'previous_failures', '[]'::jsonb)
                    || jsonb_build_array(jsonb_build_object(
                         'attempt', attempt_count,
                         'error_code', cast(:error_code as text),
                         'error_message', left(cast(:error_message as text), 2000),
                         'recorded_at', now()::text
                       ))
                )
            where id = :job_id
            """
        ).bindparams(bindparam("error_detail_json", type_=JSONB)),
        {
            "job_id": job_id,
            "error_code": error_code,
            "error_message": error_message,
            "error_detail_json": json_safe_value(error_detail_json or {}),
            "retry_allowed": retry_allowed,
        },
    )
    db.commit()


def touch_running_job(db: Session, *, job_id: UUID) -> bool:
    """Refresh the lease on a job that is still being worked on.

    `claim_next_job` stamps `locked_at` once and never again, so the stale
    sweep has always been measuring "how long ago was this claimed", not "is
    anyone still on it". Handlers that run for minutes call this at their
    checkpoints to answer the second question.

    Deliberately does not commit: the recommendation handler is inline-commit
    by design, and the lease rides along with the progress write it accompanies
    instead of paying for a transaction of its own.
    """
    result = db.execute(
        text(
            """
            update background_job
            set locked_at = now(),
                updated_at = now()
            where id = :job_id
              and status = 'running'
            """
        ),
        {"job_id": job_id},
    )
    return bool(result.rowcount)


# 同一个 job 被部署反复打断的次数上限。超过就判失败而不是无限放回队列：
# 崩溃重启循环里的 worker 会一直收到 SIGTERM，而重排一次 recommendation_agent
# 就是重新付一次模型钱。
MAX_SHUTDOWN_RELEASES = 3


def release_job_for_shutdown(
    db: Session,
    *,
    job_id: UUID,
    worker_id: str,
    max_releases: int = MAX_SHUTDOWN_RELEASES,
) -> str:
    """Hand a running job back to the queue because *we* are stopping.

    Releasing gives the attempt back (`attempt_count - 1`). With
    `max_attempts = 1` on the agent turn, spending the attempt here would turn
    every deploy into a failed recommendation — graceful shutdown would be
    manufacturing exactly the failure it exists to prevent.

    Returns "queued" when the job went back, "failed" when it has been
    interrupted too many times to keep re-running for free.
    """
    row = db.execute(
        text(
            """
            select coalesce((metadata_json -> 'released_by_shutdown' ->> 'count')::int, 0)
                     as release_count
            from background_job
            where id = :job_id
              and status = 'running'
            """
        ),
        {"job_id": job_id},
    ).mappings().one_or_none()
    if row is None:
        # Someone else already moved it — a stale sweep, or a cancel. Leave it.
        return "unchanged"

    release_count = int(row["release_count"]) + 1
    if release_count > max_releases:
        mark_job_failed(
            db,
            job_id=job_id,
            error_message=(
                f"Worker shut down while running this job {release_count - 1} times; "
                "not requeueing again."
            ),
            error_code="worker_shutdown_exhausted",
            retry_allowed=False,
        )
        return "failed"

    db.execute(
        text(
            """
            update background_job
            set status = 'queued',
                run_after = now(),
                locked_by = null,
                locked_at = null,
                started_at = null,
                finished_at = null,
                attempt_count = greatest(attempt_count - 1, 0),
                updated_at = now(),
                metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
                  'released_by_shutdown', jsonb_build_object(
                    'at', now()::text,
                    'worker_id', cast(:worker_id as text),
                    'count', cast(:release_count as int)
                  )
                )
            where id = :job_id
              and status = 'running'
            """
        ),
        {"job_id": job_id, "worker_id": worker_id, "release_count": release_count},
    )
    db.commit()
    return "queued"
