"""The job queue's SQL, executed against a real Postgres.

These statements cannot be checked without a database. `mark_job_failed`
shipped broken for four days because `jsonb_build_object` is variadic `"any"`
and Postgres refuses to infer a bare parameter's type inside it — the failure
only appears when a job actually fails, and it appeared as the worker process
dying rather than as a test failure.

Skipped unless DATABASE_URL points at a migrated database; CI runs them in the
`Fresh database from baseline` job, which already has one.
"""

import os
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="needs a migrated Postgres (DATABASE_URL)",
)


@pytest.fixture
def db():
    from backend.app.db import session_scope

    with session_scope() as session:
        yield session


@pytest.fixture
def job_id(db):
    from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

    new_id = uuid4()
    db.execute(
        text(
            """
            insert into background_job (
              id, team_id, workspace_id, job_type, priority, queue_name,
              idempotency_key, payload_json, max_attempts, created_by, metadata_json
            )
            values (
              :id, :team_id, :workspace_id, 'model_node_test', 100, 'llm',
              :idempotency_key, :payload_json, 3, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "id": new_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "idempotency_key": f"test-job-queue-sql:{new_id}",
            "payload_json": {},
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {},
        },
    )
    db.commit()
    yield new_id
    db.execute(text("delete from background_job where id = :id"), {"id": new_id})
    db.commit()


def _job(db, job_id):
    return db.execute(
        text("select status, error_code, error_message, error_detail_json from background_job where id = :id"),
        {"id": job_id},
    ).mappings().one()


def test_mark_job_failed_records_the_reason(db, job_id) -> None:
    from backend.app.jobs.queue import mark_job_failed

    mark_job_failed(
        db,
        job_id=job_id,
        error_message="Default model node is not configured: recommendation_agent_to_target",
        retry_allowed=False,
    )

    row = _job(db, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "job_failed"
    assert "recommendation_agent_to_target" in row["error_message"]


def test_repeated_failures_accumulate_instead_of_overwriting(db, job_id) -> None:
    from backend.app.jobs.queue import mark_job_failed

    mark_job_failed(db, job_id=job_id, error_message="first", retry_allowed=True)
    mark_job_failed(db, job_id=job_id, error_message="second", retry_allowed=False)

    previous = _job(db, job_id)["error_detail_json"]["previous_failures"]
    assert [entry["error_message"] for entry in previous] == ["first", "second"]


def test_a_very_long_error_is_truncated_not_rejected(db, job_id) -> None:
    from backend.app.jobs.queue import mark_job_failed

    mark_job_failed(db, job_id=job_id, error_message="x" * 5000, retry_allowed=False)

    previous = _job(db, job_id)["error_detail_json"]["previous_failures"]
    assert len(previous[0]["error_message"]) == 2000


def test_mark_job_succeeded_and_stale_requeue_execute(db, job_id) -> None:
    from backend.app.jobs.queue import mark_job_succeeded, requeue_stale_running_jobs

    mark_job_succeeded(db, job_id=job_id, result_json={"handled": True})
    assert _job(db, job_id)["status"] == "succeeded"
    # 清扫器和失败标记跑在同一条路径上，一起过一遍。
    requeue_stale_running_jobs(db, queue_name="llm", stale_after_seconds=1800)


def _claim(db, job_id):
    """Put the job into the state a worker actually holds it in."""
    db.execute(
        text(
            """
            update background_job
            set status = 'running',
                locked_by = 'worker-test',
                locked_at = now(),
                started_at = now(),
                attempt_count = attempt_count + 1
            where id = :id
            """
        ),
        {"id": job_id},
    )
    db.commit()


def _row(db, job_id):
    return db.execute(
        text(
            """
            select status, attempt_count, locked_at, locked_by, metadata_json,
                   error_code
            from background_job
            where id = :id
            """
        ),
        {"id": job_id},
    ).mappings().one()


def test_touch_running_job_moves_the_lease_forward(db, job_id) -> None:
    from backend.app.jobs.queue import touch_running_job

    _claim(db, job_id)
    db.execute(
        text("update background_job set locked_at = now() - interval '20 minutes' where id = :id"),
        {"id": job_id},
    )
    db.commit()
    before = _row(db, job_id)["locked_at"]

    assert touch_running_job(db, job_id=job_id) is True
    db.commit()

    assert _row(db, job_id)["locked_at"] > before


def test_touch_ignores_a_job_that_is_no_longer_running(db, job_id) -> None:
    from backend.app.jobs.queue import touch_running_job

    assert touch_running_job(db, job_id=job_id) is False


def test_release_on_shutdown_requeues_without_spending_the_attempt(db, job_id) -> None:
    """agent job 的 max_attempts 是 1：花掉这一次就等于把重启做成了失败。"""
    from backend.app.jobs.queue import release_job_for_shutdown

    _claim(db, job_id)
    assert _row(db, job_id)["attempt_count"] == 1

    assert release_job_for_shutdown(db, job_id=job_id, worker_id="worker-test") == "queued"

    row = _row(db, job_id)
    assert row["status"] == "queued"
    assert row["attempt_count"] == 0
    assert row["locked_at"] is None
    assert row["locked_by"] is None
    assert row["metadata_json"]["released_by_shutdown"]["count"] == 1
    assert row["metadata_json"]["released_by_shutdown"]["worker_id"] == "worker-test"


def test_a_job_interrupted_too_often_stops_being_requeued(db, job_id) -> None:
    """崩溃重启循环里，无限重排一个 agent turn 就是无限重新付费。"""
    from backend.app.jobs.queue import release_job_for_shutdown

    for expected in ("queued", "queued"):
        _claim(db, job_id)
        assert release_job_for_shutdown(
            db, job_id=job_id, worker_id="worker-test", max_releases=2
        ) == expected

    _claim(db, job_id)
    assert release_job_for_shutdown(
        db, job_id=job_id, worker_id="worker-test", max_releases=2
    ) == "failed"

    row = _row(db, job_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "worker_shutdown_exhausted"


def test_releasing_a_job_nobody_holds_changes_nothing(db, job_id) -> None:
    from backend.app.jobs.queue import release_job_for_shutdown

    assert release_job_for_shutdown(db, job_id=job_id, worker_id="worker-test") == "unchanged"
    assert _row(db, job_id)["status"] == "queued"
