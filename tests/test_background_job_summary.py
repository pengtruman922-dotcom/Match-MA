from uuid import UUID

from backend.app.api.routes import background_jobs as background_job_routes
from backend.app.api.routes.background_jobs import (
    BackgroundJobIgnoreRequest,
    _compact_queue_job,
    _compact_failure_job,
    _archive_metadata,
    _failure_category,
    _failure_job_type_item,
    _ignore_metadata,
    _job_archived,
    _job_failure_ignored,
    _job_test_data,
    _retry_metadata,
    _test_data_metadata,
    _task_center_item,
    _task_display_name,
    _retry_preview_warnings,
    _unarchive_metadata,
    _unignore_metadata,
    _untest_data_metadata,
    _failure_summary_text,
    _failure_summary_totals,
    _queue_health_status,
    _queue_summary_names,
    _queue_summary_totals,
)


class _FakeExecuteResult:
    def __init__(self, row: dict):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _FakeDb:
    def __init__(self, row: dict):
        self.row = row
        self.execute_calls = []
        self.commit_count = 0

    def execute(self, *args, **kwargs):
        self.execute_calls.append((args, kwargs))
        return _FakeExecuteResult(self.row)

    def commit(self):
        self.commit_count += 1


def test_queue_summary_names_include_default_worker_queues() -> None:
    names = _queue_summary_names(["custom", "llm"], include_empty=True)

    # research 是独立队列：调研单次 5~15 分钟，不与解析/抽取/深评抢 llm 的槽位。
    assert names[:4] == ["llm", "research", "ocr", "default"]
    assert "custom" in names
    assert names.count("llm") == 1
    # 已下线的 worker 队列不再无条件占位。
    assert "embedding" not in names
    assert "rerank" not in names


def test_queue_summary_names_still_surface_retired_queues_with_history() -> None:
    # 历史作业仍在 embedding 队列里，必须照常出现，否则旧记录会从任务中心消失。
    names = _queue_summary_names(["embedding"], include_empty=True)

    assert "embedding" in names


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
                "counts": {"failed": 1, "ignored_failed": 2, "queued": 2, "running": 1, "retry_waiting": 0},
            },
            {
                "active_count": 0,
                "counts": {"failed": 0, "ignored_failed": 0, "queued": 0, "running": 0, "retry_waiting": 0},
            },
        ]
    )

    assert totals["queue_count"] == 2
    assert totals["active_queue_count"] == 1
    assert totals["failed_queue_count"] == 1
    assert totals["active_job_count"] == 3
    assert totals["ignored_failed_job_count"] == 2
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
            "metadata_json": {},
        }
    )

    assert compact["error_code"] == "llm_failed"
    assert compact["failure_category"] == "provider_or_llm"
    assert compact["failure_summary"] == "Model provider call failed or returned an unusable response. Check model config and trace."
    assert len(compact["error_message"]) == 500
    assert compact["related_entity_ref"]["route"] == f"/debug/entities/business_update/{entity_id}"
    assert compact["can_retry"] is True
    assert compact["retry_route"] == f"/background-jobs/{job_id}/retry"
    assert compact["retry_preview_route"] == f"/background-jobs/{job_id}/retry-preview"
    assert compact["ignore_route"] == f"/background-jobs/{job_id}/ignore"
    assert [item["key"] for item in compact["recommended_actions"]] == [
        "open_debug",
        "open_related_entity",
        "preview_retry",
        "retry_job",
        "ignore_job",
        "archive_job",
        "mark_test_data",
    ]


def test_compact_failure_job_exposes_ignore_metadata() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000005")
    compact = _compact_failure_job(
        {
            "id": job_id,
            "job_type": "buyer_intent_parse",
            "status": "failed",
            "priority": 100,
            "queue_name": "llm",
            "entity_type": None,
            "entity_id": None,
            "run_after": None,
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "error_code": "job_failed",
            "error_message": "test data",
            "attempt_count": 3,
            "max_attempts": 3,
            "metadata_json": {
                "failure_ignored": True,
                "failure_ignored_at": "2026-06-03",
                "failure_ignore_reason": "test garbage",
            },
        }
    )

    assert _job_failure_ignored({"metadata_json": {"failure_ignored": True}}) is True
    assert compact["ignored"] is True
    assert compact["ignore_reason"] == "test garbage"
    assert compact["ignore_route"] is None
    assert compact["unignore_route"] == f"/background-jobs/{job_id}/unignore"
    assert "unignore_job" in [item["key"] for item in compact["recommended_actions"]]


def test_task_center_item_uses_business_display_fields() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000006")
    entity_id = UUID("00000000-0000-0000-0000-000000000007")
    user_id = UUID("00000000-0000-0000-0000-000000000008")

    item = _task_center_item(
        {
            "id": job_id,
            "job_type": "buyer_intent_parse",
            "status": "failed",
            "priority": 100,
            "queue_name": "llm",
            "entity_type": "buyer_intent",
            "entity_id": entity_id,
            "related_object_name": "小鹏汽车 / 并购需求（2026-07）",
            "initiated_by_user_id": user_id,
            "initiated_by_name": "管理员",
            "initiated_by_username": "admin",
            "run_after": None,
            "created_at": "2026-07-10 10:00:00+00",
            "updated_at": "2026-07-10 10:01:00+00",
            "started_at": "2026-07-10 10:00:10+00",
            "finished_at": "2026-07-10 10:01:00+00",
            "error_code": "job_failed",
            "error_message": "LLM HTTP 429: insufficient_quota",
            "attempt_count": 3,
            "max_attempts": 3,
            "metadata_json": {},
        }
    )

    assert item["task_display_name"] == "买家意向解析"
    assert item["related_object_name"] == "小鹏汽车 / 并购需求（2026-07）"
    assert item["related_object_route"] == f"/buyer-intents/{entity_id}"
    assert item["initiated_by_name"] == "管理员"
    assert item["failure_category"] == "provider_or_llm"
    assert item["can_retry"] is True
    assert item["ignore_route"] == f"/background-jobs/{job_id}/ignore"


def test_task_center_item_supports_ignored_historical_jobs() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000009")
    item = _task_center_item(
        {
            "id": job_id,
            "job_type": "attachment_ocr_parse",
            "status": "failed",
            "priority": 100,
            "queue_name": "ocr",
            "entity_type": "attachment",
            "entity_id": UUID("00000000-0000-0000-0000-000000000012"),
            "related_object_name": None,
            "initiated_by_user_id": None,
            "initiated_by_name": None,
            "initiated_by_username": None,
            "run_after": None,
            "created_at": None,
            "updated_at": None,
            "started_at": None,
            "finished_at": None,
            "error_code": "job_failed",
            "error_message": "OCR failed",
            "attempt_count": 1,
            "max_attempts": 3,
            "metadata_json": {"failure_ignored": True, "failure_ignore_reason": "历史测试"},
        }
    )

    assert item["task_display_name"] == "附件 OCR 解析"
    assert item["related_object_name"].startswith("attachment / ")
    assert item["initiated_by_name"] == "未知"
    assert item["ignored"] is True
    assert item["ignore_route"] is None
    assert item["unignore_route"] == f"/background-jobs/{job_id}/unignore"


def test_task_center_task_display_name_falls_back_to_job_type() -> None:
    assert _task_display_name("recommendation_rerank") == "推荐重排"
    assert _task_display_name("custom_job") == "custom_job"



def test_retry_ignore_metadata_helpers_preserve_audit_snapshot() -> None:
    retry_metadata = _retry_metadata(
        {
            "status": "failed",
            "error_code": "job_failed",
            "error_message": "x" * 2100,
            "attempt_count": 3,
            "metadata_json": {
                "source": "test",
                "failure_ignored": True,
                "failure_ignore_reason": "old",
            },
        }
    )

    assert retry_metadata["source"] == "test"
    assert "failure_ignored" not in retry_metadata
    assert retry_metadata["last_retry_previous_status"] == "failed"
    assert retry_metadata["last_retry_previous_error_code"] == "job_failed"
    assert len(retry_metadata["last_retry_previous_error_message"]) == 2000
    assert retry_metadata["last_retry_previous_attempt_count"] == 3

    ignored_metadata = _ignore_metadata({"source": "test"}, reason="historical garbage")
    assert ignored_metadata["source"] == "test"
    assert ignored_metadata["failure_ignored"] is True
    assert ignored_metadata["failure_ignore_reason"] == "historical garbage"

    unignored_metadata = _unignore_metadata(ignored_metadata)
    assert unignored_metadata["source"] == "test"
    assert "failure_ignored" not in unignored_metadata
    assert unignored_metadata["failure_unignored_by"]

    archived_metadata = _archive_metadata({"source": "test"}, reason="old failure")
    assert archived_metadata["source"] == "test"
    assert archived_metadata["archived"] is True
    assert archived_metadata["archive_reason"] == "old failure"
    assert _job_archived({"metadata_json": archived_metadata}) is True

    unarchived_metadata = _unarchive_metadata(archived_metadata)
    assert "archived" not in unarchived_metadata
    assert unarchived_metadata["unarchived_by"]

    test_data_metadata = _test_data_metadata({"source": "test"}, label="demo", reason="sample")
    assert test_data_metadata["is_test_data"] is True
    assert test_data_metadata["test_data_label"] == "demo"
    assert _job_test_data({"metadata_json": test_data_metadata}) is True

    untest_data_metadata = _untest_data_metadata(test_data_metadata)
    assert "is_test_data" not in untest_data_metadata
    assert untest_data_metadata["test_data_unmarked_by"]

def test_retry_preview_warnings_flag_missing_trace_and_existing_logs() -> None:
    warnings = _retry_preview_warnings(
        {"status": "failed"},
        {
            "trace_count": 0,
            "active_same_entity_job_count": 1,
            "business_update": {"application_log_count": 2},
        },
    )

    assert [item["key"] for item in warnings] == [
        "active_related_jobs",
        "no_trace",
        "existing_application_logs",
    ]


def test_failure_category_and_summary_map_common_errors() -> None:
    assert _failure_category("job_failed", "violates check constraint seller_target_listed_status_check") == "db_constraint"
    assert _failure_category("job_failed", "name 'x' is not defined") == "code_error"
    assert _failure_category("job_failed", "Some actions are invalid.") == "schema_validation"
    assert _failure_category("llm_failed", "LLM HTTP 401") == "provider_auth"
    assert _failure_category("job_failed", 'Doc2X HTTP 401: {"code":"unauthorized","msg":"认证失败"}') == "provider_auth"
    assert _failure_summary_text("db_constraint", "raw") == (
        "Database constraint failed while applying extracted data. Check enum/normalized field values."
    )


def test_ignore_background_job_marks_related_business_update(monkeypatch) -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000010")
    business_update_id = UUID("00000000-0000-0000-0000-000000000011")
    db = _FakeDb(
        {
            "id": job_id,
            "job_type": "business_update_extract_actions",
            "status": "failed",
            "entity_type": "business_update",
            "entity_id": business_update_id,
        }
    )
    marked_jobs = []

    monkeypatch.setattr(
        background_job_routes,
        "_get_job_or_404",
        lambda _db, _job_id: {"id": _job_id, "status": "failed"},
    )
    monkeypatch.setattr(
        background_job_routes,
        "_mark_related_business_update_ignored",
        lambda _db, job: marked_jobs.append(job),
    )

    result = background_job_routes.ignore_background_job(
        job_id,
        BackgroundJobIgnoreRequest(reason="historical test data"),
        db,
    )

    assert result["id"] == job_id
    assert marked_jobs == [db.row]
    assert db.commit_count == 1


def test_cancel_background_job_does_not_mark_business_update_ignored(monkeypatch) -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000012")
    db = _FakeDb(
        {
            "id": job_id,
            "job_type": "business_update_extract_actions",
            "status": "cancelled",
            "entity_type": "business_update",
            "entity_id": UUID("00000000-0000-0000-0000-000000000013"),
        }
    )
    marked_jobs = []

    monkeypatch.setattr(
        background_job_routes,
        "_get_job_or_404",
        lambda _db, _job_id: {"id": _job_id, "status": "queued"},
    )
    monkeypatch.setattr(
        background_job_routes,
        "_mark_related_business_update_ignored",
        lambda _db, job: marked_jobs.append(job),
    )

    result = background_job_routes.cancel_background_job(job_id, db)

    assert result["status"] == "cancelled"
    assert marked_jobs == []
    assert db.commit_count == 1


def test_retry_background_job_marks_related_business_update_processing(monkeypatch) -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000014")
    db = _FakeDb(
        {
            "id": job_id,
            "job_type": "business_update_extract_actions",
            "status": "queued",
            "entity_type": "business_update",
            "entity_id": UUID("00000000-0000-0000-0000-000000000015"),
        }
    )
    marked_jobs = []

    monkeypatch.setattr(
        background_job_routes,
        "_get_job_or_404",
        lambda _db, _job_id: {"id": _job_id, "status": "failed"},
    )
    monkeypatch.setattr(
        background_job_routes,
        "_mark_related_business_update_retrying",
        lambda _db, job: marked_jobs.append(job),
    )

    result = background_job_routes.retry_background_job(job_id, db)

    assert result["status"] == "queued"
    assert marked_jobs == [db.row]
    assert db.commit_count == 1
