from uuid import UUID

from backend.app.api.routes.background_jobs import (
    _compact_queue_job,
    _queue_health_status,
    _queue_summary_names,
    _queue_summary_totals,
)


def test_queue_summary_names_include_default_worker_queues() -> None:
    names = _queue_summary_names(["custom", "llm"], include_empty=True)

    assert names[:5] == ["llm", "ocr", "embedding", "rerank", "default"]
    assert "custom" in names
    assert names.count("llm") == 1


def test_queue_summary_names_can_exclude_empty_defaults() -> None:
    assert _queue_summary_names(["custom"], include_empty=False) == ["custom"]


def test_queue_health_status_prioritizes_failures_then_active() -> None:
    assert _queue_health_status(active_count=0, failed_count=1) == "has_failures"
    assert _queue_health_status(active_count=2, failed_count=0) == "active"
    assert _queue_health_status(active_count=0, failed_count=0) == "idle"


def test_queue_summary_totals_aggregate_active_and_failed_counts() -> None:
    totals = _queue_summary_totals(
        [
            {
                "active_count": 3,
                "counts": {"failed": 1, "queued": 2, "running": 1, "retry_waiting": 0},
            },
            {
                "active_count": 0,
                "counts": {"failed": 0, "queued": 0, "running": 0, "retry_waiting": 0},
            },
        ]
    )

    assert totals["queue_count"] == 2
    assert totals["active_queue_count"] == 1
    assert totals["failed_queue_count"] == 1
    assert totals["active_job_count"] == 3
    assert totals["queued_job_count"] == 2
    assert totals["running_job_count"] == 1


def test_compact_queue_job_exposes_debug_ref() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000001")
    compact = _compact_queue_job(
        {
            "id": job_id,
            "job_type": "attachment_ocr_parse",
            "status": "queued",
            "priority": 100,
            "queue_name": "ocr",
            "entity_type": "attachment",
            "entity_id": UUID("00000000-0000-0000-0000-000000000002"),
            "run_after": "2026-06-03",
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "error_message": None,
        }
    )

    assert compact["debug_ref"]["route"] == f"/debug/entities/background_job/{job_id}"
    assert compact["queue_name"] == "ocr"
