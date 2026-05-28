import argparse
import socket
import time

from backend.app.db import session_scope
from backend.app.jobs.handlers import execute_job
from backend.app.jobs.queue import claim_next_job, mark_job_failed, mark_job_succeeded


def run_once(*, queue_name: str, worker_id: str) -> bool:
    job = None
    with session_scope() as db:
        job = claim_next_job(db, worker_id=worker_id, queue_name=queue_name)
    if job is None:
        return False

    try:
        result = execute_job(job)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        with session_scope() as db:
            mark_job_failed(db, job_id=job.id, error_message=str(exc))
        raise

    with session_scope() as db:
        mark_job_succeeded(db, job_id=job.id, result_json=result)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Match-MA background worker")
    parser.add_argument("--queue", default="default", help="Queue name to consume")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration then exit")
    parser.add_argument("--sleep", type=float, default=2.0, help="Sleep seconds when no job is found")
    parser.add_argument("--worker-id", default=f"worker-{socket.gethostname()}")
    args = parser.parse_args()

    while True:
        found = run_once(queue_name=args.queue, worker_id=args.worker_id)
        if args.once:
            return
        if not found:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
