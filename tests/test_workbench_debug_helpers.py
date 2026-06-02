from uuid import UUID

from backend.app.api.routes.debug import _debug_summary
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
