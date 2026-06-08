import argparse
import socket
import time

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import session_scope
from backend.app.jobs.handlers import execute_job
from backend.app.jobs.queue import (
    claim_next_job,
    mark_job_failed,
    mark_job_succeeded,
    requeue_stale_running_jobs,
)


def run_once(*, queue_name: str, worker_id: str) -> bool:
    job = None
    with session_scope() as db:
        requeue_stale_running_jobs(db, queue_name=queue_name)
        job = claim_next_job(db, worker_id=worker_id, queue_name=queue_name)
    if job is None:
        return False

    try:
        with session_scope() as db:
            result = execute_job(db, job)
            mark_job_succeeded(db, job_id=job.id, result_json=result)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        with session_scope() as db:
            mark_job_failed(db, job_id=job.id, error_message=str(exc))
            _mark_related_business_update_failed_if_final(db, job, str(exc))
        raise

    return True


def _mark_related_business_update_failed_if_final(db, job, error_message: str) -> None:
    if (
        job.job_type != "business_update_extract_actions"
        or job.entity_type != "business_update"
        or job.entity_id is None
    ):
        return
    failed_job = db.execute(
        text(
            """
            select status
            from background_job
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "job_id": job.id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if not failed_job or failed_job["status"] != "failed":
        return
    db.execute(
        text(
            """
            update business_update
            set processing_status = 'failed',
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": job.entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_processed_job_id": str(job.id),
                "last_processing_result": "failed",
                "last_error_message": error_message,
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Match-MA background worker")
    parser.add_argument("--queue", default="default", help="Queue name to consume")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration then exit")
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Sleep seconds when no job is found",
    )
    parser.add_argument("--worker-id", default=f"worker-{socket.gethostname()}")
    args = parser.parse_args()

    print(
        f"Starting Match-MA worker queue={args.queue} worker_id={args.worker_id}",
        flush=True,
    )

    while True:
        found = run_once(queue_name=args.queue, worker_id=args.worker_id)
        if args.once:
            return
        if not found:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
