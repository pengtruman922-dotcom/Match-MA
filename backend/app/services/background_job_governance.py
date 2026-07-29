from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.constants import DEFAULT_ADMIN_USER_ID

def _retry_metadata(job: dict[str, Any]) -> dict[str, Any]:
    metadata = _without_keys(
        job.get("metadata_json"),
        {"failure_ignored", "failure_ignored_at", "failure_ignored_by", "failure_ignore_reason"},
    )
    metadata.update(
        {
            "last_retry_at": _utc_now_text(),
            "last_retry_by": str(DEFAULT_ADMIN_USER_ID),
            "last_retry_previous_status": job.get("status"),
            "last_retry_previous_error_code": job.get("error_code"),
            "last_retry_previous_error_message": _truncate_text(job.get("error_message"), 2000) or "",
            "last_retry_previous_attempt_count": job.get("attempt_count"),
        }
    )
    return metadata


def _ignore_metadata(metadata_json: Any, *, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "failure_ignored": True,
            "failure_ignored_at": _utc_now_text(),
            "failure_ignored_by": str(DEFAULT_ADMIN_USER_ID),
            "failure_ignore_reason": reason,
        }
    )
    return metadata


def _unignore_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(
        metadata_json,
        {"failure_ignored", "failure_ignored_at", "failure_ignored_by", "failure_ignore_reason"},
    )
    metadata.update(
        {
            "failure_unignored_at": _utc_now_text(),
            "failure_unignored_by": str(DEFAULT_ADMIN_USER_ID),
        }
    )
    return metadata


def _archive_metadata(metadata_json: Any, *, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "archived": True,
            "archived_at": _utc_now_text(),
            "archived_by": str(DEFAULT_ADMIN_USER_ID),
            "archive_reason": reason,
        }
    )
    return metadata


def _unarchive_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(metadata_json, {"archived", "archived_at", "archived_by", "archive_reason"})
    metadata.update({"unarchived_at": _utc_now_text(), "unarchived_by": str(DEFAULT_ADMIN_USER_ID)})
    return metadata


def _test_data_metadata(metadata_json: Any, *, label: str | None, reason: str | None) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    metadata.update(
        {
            "is_test_data": True,
            "test_data_marked_at": _utc_now_text(),
            "test_data_marked_by": str(DEFAULT_ADMIN_USER_ID),
            "test_data_label": label,
            "test_data_reason": reason,
        }
    )
    return metadata


def _untest_data_metadata(metadata_json: Any) -> dict[str, Any]:
    metadata = _without_keys(
        metadata_json,
        {
            "is_test_data",
            "test_data_marked_at",
            "test_data_marked_by",
            "test_data_label",
            "test_data_reason",
        },
    )
    metadata.update({"test_data_unmarked_at": _utc_now_text(), "test_data_unmarked_by": str(DEFAULT_ADMIN_USER_ID)})
    return metadata



def _without_keys(metadata_json: Any, keys: set[str]) -> dict[str, Any]:
    metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    for key in keys:
        metadata.pop(key, None)
    return metadata


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _failure_group_item(row: dict[str, Any], *, group_key: str) -> dict[str, Any]:
    group_value = str(row.get(group_key) or "unknown")
    return {
        group_key: group_value,
        "failed_count": int(row.get("failed_count") or 0),
        "latest_failed_at": row.get("latest_failed_at"),
        "list_route": f"/background-jobs?status=failed&{group_key}={group_value}",
    }


def _failure_job_type_item(row: dict[str, Any]) -> dict[str, Any]:
    item = _failure_group_item(row, group_key="job_type")
    item["queue_name"] = row.get("queue_name")
    item["list_route"] = f"/background-jobs?status=failed&job_type={item['job_type']}"
    return item


def _compact_failure_job(row: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_queue_job(row)
    ignored = _job_failure_ignored(row)
    archived = _job_archived(row)
    test_data = _job_test_data(row)
    metadata_json = row.get("metadata_json") or {}
    can_retry = row.get("status") in {"failed", "cancelled"}
    failure_category = _failure_category(row.get("error_code"), row.get("error_message"))
    compact["error_code"] = row.get("error_code")
    compact["failure_category"] = failure_category
    compact["failure_summary"] = _failure_summary_text(failure_category, row.get("error_message"))
    compact["attempt_count"] = row.get("attempt_count")
    compact["max_attempts"] = row.get("max_attempts")
    compact["error_message"] = _truncate_text(row.get("error_message"), 500)
    compact["related_entity_ref"] = _debug_ref(row.get("entity_type"), row.get("entity_id")) if row.get("entity_type") and row.get("entity_id") else None
    compact["ignored"] = ignored
    compact["ignore_reason"] = metadata_json.get("failure_ignore_reason")
    compact["ignored_at"] = metadata_json.get("failure_ignored_at")
    compact["archived"] = archived
    compact["archive_reason"] = metadata_json.get("archive_reason")
    compact["archived_at"] = metadata_json.get("archived_at")
    compact["is_test_data"] = test_data
    compact["test_data_label"] = metadata_json.get("test_data_label")
    compact["test_data_reason"] = metadata_json.get("test_data_reason")
    compact["can_retry"] = can_retry
    compact["retry_route"] = f"/background-jobs/{row['id']}/retry" if can_retry else None
    compact["retry_preview_route"] = f"/background-jobs/{row['id']}/retry-preview" if can_retry else None
    compact["ignore_route"] = None if ignored else f"/background-jobs/{row['id']}/ignore"
    compact["unignore_route"] = f"/background-jobs/{row['id']}/unignore" if ignored else None
    compact["archive_route"] = None if archived else f"/background-jobs/{row['id']}/archive"
    compact["unarchive_route"] = f"/background-jobs/{row['id']}/unarchive" if archived else None
    compact["mark_test_data_route"] = None if test_data else f"/background-jobs/{row['id']}/mark-test-data"
    compact["unmark_test_data_route"] = f"/background-jobs/{row['id']}/unmark-test-data" if test_data else None
    compact["recommended_actions"] = _failure_recommended_actions(compact)
    return compact


def _failure_category(error_code: Any, error_message: Any) -> str:
    code = str(error_code or "").lower()
    message = str(error_message or "").lower()
    if "checkviolation" in message or "violates check constraint" in message:
        return "db_constraint"
    if "not defined" in message or "nameerror" in message or code in {"name_error", "code_error"}:
        return "code_error"
    if "schema" in message or "invalid" in message or code in {"schema_validation_failed", "invalid_output"}:
        return "schema_validation"
    if (
        "unauthorized" in message
        or "authentication" in message
        or "认证失败" in message
        or "http 401" in message
        or code in {"auth_failed", "unauthorized"}
    ):
        return "provider_auth"
    if "llm" in message or "provider" in message or "http " in message or code in {"llm_failed", "provider_failed"}:
        return "provider_or_llm"
    if code:
        return code
    return "unknown"


def _failure_summary_text(category: str, error_message: Any) -> str:
    message = _truncate_text(error_message, 240)
    if category == "db_constraint":
        return "Database constraint failed while applying extracted data. Check enum/normalized field values."
    if category == "code_error":
        return "Backend code error occurred while running the job. Check deploy version and stack trace."
    if category == "schema_validation":
        return "AI output or extracted action payload failed validation. Check trace output and prompt/schema."
    if category == "provider_auth":
        return "Provider authentication failed. Check API key formatting, secret binding, and provider account status."
    if category == "provider_or_llm":
        return "Model provider call failed or returned an unusable response. Check model config and trace."
    return message or "Job failed without a detailed error message."


def _failure_recommended_actions(job: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [
        {
            "key": "open_debug",
            "label": "Open Debug",
            "route": job["debug_ref"]["route"],
        }
    ]
    if job.get("related_entity_ref"):
        actions.append(
            {
                "key": "open_related_entity",
                "label": "Open Related Entity",
                "route": job["related_entity_ref"]["route"],
            }
        )
    if job.get("can_retry"):
        actions.append(
            {
                "key": "preview_retry",
                "label": "Preview Retry",
                "route": job.get("retry_preview_route"),
                "method": "GET",
            }
        )
    if job.get("can_retry"):
        actions.append(
            {
                "key": "retry_job",
                "label": "Retry Job",
                "route": job.get("retry_route"),
                "method": "POST",
            }
        )
    if job.get("ignored"):
        actions.append(
            {
                "key": "unignore_job",
                "label": "Unignore Job",
                "route": job.get("unignore_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "ignore_job",
                "label": "Ignore Job",
                "route": job.get("ignore_route"),
                "method": "POST",
            }
        )
    if job.get("archived"):
        actions.append(
            {
                "key": "unarchive_job",
                "label": "Unarchive Job",
                "route": job.get("unarchive_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "archive_job",
                "label": "Archive Job",
                "route": job.get("archive_route"),
                "method": "POST",
            }
        )
    if job.get("is_test_data"):
        actions.append(
            {
                "key": "unmark_test_data",
                "label": "Unmark Test Data",
                "route": job.get("unmark_test_data_route"),
                "method": "POST",
            }
        )
    else:
        actions.append(
            {
                "key": "mark_test_data",
                "label": "Mark Test Data",
                "route": job.get("mark_test_data_route"),
                "method": "POST",
            }
        )
    return actions


def _failure_summary_totals(
    *,
    by_queue: list[dict[str, Any]],
    by_job_type: list[dict[str, Any]],
    recent_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "failed_job_count": sum(int(item.get("failed_count") or 0) for item in by_queue),
        "failed_queue_count": len(by_queue),
        "failed_job_type_count": len(by_job_type),
        "recent_failure_count": len(recent_failures),
    }


def _queue_summary_names(queue_names: Any, *, include_empty: bool) -> list[str]:
    defaults = ["llm", "research", "ocr", "embedding", "rerank", "default"]
    names = list(dict.fromkeys([*defaults, *[str(item) for item in queue_names]]))
    return names if include_empty else [name for name in names if name not in defaults or name in queue_names]


def _queue_health_status(*, active_count: int, failed_count: int) -> str:
    if failed_count:
        return "has_failures"
    if active_count:
        return "active"
    return "idle"



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


def _job_failure_ignored(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("failure_ignored") is True


def _job_archived(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("archived") is True


def _job_test_data(row: dict[str, Any]) -> bool:
    return (row.get("metadata_json") or {}).get("is_test_data") is True


def _not_failure_ignored_sql() -> str:
    return "coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true'"


def _not_archived_sql() -> str:
    return "coalesce(metadata_json ->> 'archived', 'false') <> 'true'"


def _not_test_data_sql() -> str:
    return "coalesce(metadata_json ->> 'is_test_data', 'false') <> 'true'"


def _queue_summary_totals(queues: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "queue_count": len(queues),
        "active_queue_count": 0,
        "failed_queue_count": 0,
        "active_job_count": 0,
        "failed_job_count": 0,
        "ignored_failed_job_count": 0,
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
        totals["ignored_failed_job_count"] += int(counts.get("ignored_failed") or 0)
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


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."
