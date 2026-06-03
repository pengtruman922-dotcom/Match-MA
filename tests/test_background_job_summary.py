from uuid import UUID

from backend.app.api.routes.background_jobs import (
    _compact_queue_job,
    _compact_failure_job,
    _failure_category,
    _failure_job_type_item,
    _failure_summary_text,
    _failure_summary_totals,
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


def test_failure_summary_totals_and_job_type_item() -> None:
    item = _failure_job_type_item(
        {
            "job_type": "business_update_extract_actions",
            "queue_name": "llm",
            "failed_count": 3,
            "latest_failed_at": "2026-06-03",
        }
    )
    totals = _failure_summary_totals(
        by_queue=[{"queue_name": "llm", "failed_count": 3}],
        by_job_type=[item],
        recent_failures=[{"id": "job-1"}],
    )

    assert item["queue_name"] == "llm"
    assert item["list_route"] == "/background-jobs?status=failed&job_type=business_update_extract_actions"
    assert totals["failed_job_count"] == 3
    assert totals["failed_queue_count"] == 1
    assert totals["recent_failure_count"] == 1


def test_compact_failure_job_truncates_error_and_links_related_entity() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000003")
    entity_id = UUID("00000000-0000-0000-0000-000000000004")
    compact = _compact_failure_job(
        {
            "id": job_id,
            "job_type": "business_update_extract_actions",
            "status": "failed",
            "priority": 100,
            "queue_name": "llm",
            "entity_type": "business_update",
            "entity_id": entity_id,
            "run_after": None,
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "error_code": "llm_failed",
            "error_message": "x" * 600,
            "attempt_count": 1,
            "max_attempts": 3,
        }
    )

    assert compact["error_code"] == "llm_failed"
    assert compact["failure_category"] == "provider_or_llm"
    assert compact["failure_summary"] == "Model provider call failed or returned an unusable response. Check model config and trace."
    assert len(compact["error_message"]) == 500
    assert compact["related_entity_ref"]["route"] == f"/debug/entities/business_update/{entity_id}"
    assert compact["can_retry"] is True
    assert compact["retry_route"] == f"/background-jobs/{job_id}/retry"
    assert [item["key"] for item in compact["recommended_actions"]] == [
        "open_debug",
        "open_related_entity",
        "retry_job",
    ]


def test_failure_category_and_summary_map_common_errors() -> None:
    assert _failure_category("job_failed", "violates check constraint seller_target_listed_status_check") == "db_constraint"
    assert _failure_category("job_failed", "name 'x' is not defined") == "code_error"
    assert _failure_category("job_failed", "Some actions are invalid.") == "schema_validation"
    assert _failure_category("llm_failed", "LLM HTTP 401") == "provider_or_llm"
    assert _failure_summary_text("db_constraint", "raw") == (
        "Database constraint failed while applying extracted data. Check enum/normalized field values."
    )
