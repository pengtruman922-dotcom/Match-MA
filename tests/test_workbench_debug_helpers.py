from uuid import UUID

from backend.app.api.routes.debug import (
    _compact_job_for_debug_center,
    _debug_center_health_level,
    _debug_ref,
    _debug_summary,
    _truncate_debug_text,
)
from backend.app.api.routes.workbench import _categorize_action, _task_priority, _task_title, _truncate_text


def test_workbench_task_priority_uses_confidence_thresholds() -> None:
    assert _task_priority({"action_type": "seller_fact_update", "confidence": 0.9}) == "normal"
    assert _task_priority({"action_type": "seller_fact_update", "confidence": 0.7}) == "medium"
    assert _task_priority({"action_type": "seller_fact_update", "confidence": 0.5}) == "high"
    assert _task_priority({"action_type": "unresolved_item", "confidence": 0.95}) == "high"
    assert _task_priority({"action_type": "seller_fact_update", "confidence": None}) == "high"


def test_workbench_action_grouping_matches_frontend_task_board() -> None:
    assert _categorize_action({"action_type": "seller_fact_update"}) == "seller_update_review"
    assert _categorize_action({"action_type": "buyer_intent_update"}) == "buyer_intent_review"
    assert _categorize_action({"action_type": "buyer_seller_relation_update"}) == "relation_progress_review"
    assert _categorize_action({"action_type": "internal_note"}) == "parse_exception"


def test_workbench_task_title_and_truncation_are_frontend_ready() -> None:
    title = _task_title({"action_type": "buyer_intent_update"}, "Buyer Intent")

    assert title.endswith("Buyer Intent")
    assert _truncate_text(" abc ", 10) == "abc"
    truncated = _truncate_text("abcde", 4)
    assert truncated is not None
    assert truncated.startswith("abc")
    assert len(truncated) == 4
    assert _truncate_text(None, 4) is None


def test_debug_summary_supports_unified_entity_types() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000001")
    job_summary = _debug_summary(
        "background_job",
        {"job": {"id": job_id, "job_type": "model_node_test", "status": "succeeded", "queue_name": "llm"}, "traces": [{}]},
    )
    node_summary = _debug_summary(
        "model_node_config",
        {"node": {"node_name": "recommendation_reranker", "node_type": "rerank", "is_active": True}, "jobs": [{}, {}], "traces": [{}]},
    )

    assert job_summary["title"] == "Background job: model_node_test"
    assert job_summary["trace_count"] == 1
    assert node_summary["status"] == "active"
    assert node_summary["node_type"] == "rerank"
    assert node_summary["job_count"] == 2


def test_debug_center_health_level_prioritizes_failures() -> None:
    assert _debug_center_health_level({"failed_job_count": 1, "failed_trace_count": 0}) == "error"
    assert _debug_center_health_level({"failed_job_count": 0, "failed_trace_count": 1}) == "error"
    assert _debug_center_health_level({"failed_job_count": 0, "failed_trace_count": 0, "active_job_count": 1}) == "warning"
    assert _debug_center_health_level({"failed_job_count": 0, "failed_trace_count": 0, "active_job_count": 0}) == "ok"


def test_debug_center_compact_job_exposes_frontend_debug_refs() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000010")
    update_id = UUID("00000000-0000-0000-0000-000000000011")
    item = _compact_job_for_debug_center(
        {
            "id": job_id,
            "job_type": "business_update_extract",
            "status": "failed",
            "queue_name": "llm",
            "priority": 100,
            "entity_type": "business_update",
            "entity_id": update_id,
            "error_code": "LLM_ERROR",
            "error_message": "x" * 300,
            "attempt_count": 2,
            "max_attempts": 3,
            "run_after": None,
            "started_at": None,
            "finished_at": None,
            "created_at": "2026-06-02T00:00:00+08:00",
            "updated_at": "2026-06-02T00:01:00+08:00",
        }
    )

    assert item["title"] == "business_update_extract / llm"
    assert item["debug_ref"]["route"].endswith(f"/debug/entities/background_job/{job_id}")
    assert item["related_entity_ref"]["route"].endswith(f"/debug/entities/business_update/{update_id}")
    assert len(item["error_message"]) == 240


def test_debug_ref_and_truncation_are_null_safe() -> None:
    assert _debug_ref(None, None) is None
    assert _debug_ref("model_node_config", "node-1") == {
        "entity_type": "model_node_config",
        "entity_id": "node-1",
        "route": "/debug/entities/model_node_config/node-1",
    }
    assert _truncate_debug_text(None, 4) is None
    assert _truncate_debug_text("abc", 4) == "abc"
    assert _truncate_debug_text("abcde", 4) == "abc…"
