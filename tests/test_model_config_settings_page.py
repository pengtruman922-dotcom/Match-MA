from uuid import UUID

from backend.app.api.routes.model_config import (
    _group_prompts_by_node_name,
    _safe_queue_name_for_node_type,
    _settings_node_summary,
    _settings_page_overview,
    _required_business_node_statuses,
)

NODE_ID = UUID("00000000-0000-0000-0000-000000000001")
PROMPT_ID = UUID("00000000-0000-0000-0000-000000000002")
JOB_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_group_prompts_by_node_name() -> None:
    prompts = [
        {"id": PROMPT_ID, "node_name": "writer", "version": "v1"},
        {"id": PROMPT_ID, "node_name": "writer", "version": "v2"},
        {"id": PROMPT_ID, "node_name": "parser", "version": "v1"},
    ]

    grouped = _group_prompts_by_node_name(prompts)

    assert set(grouped) == {"writer", "parser"}
    assert len(grouped["writer"]) == 2


def test_settings_node_summary_exposes_ui_flags_and_latest_test() -> None:
    node = {
        "id": NODE_ID,
        "node_name": "recommendation_report_writer",
        "node_type": "llm",
        "is_active": True,
        "prompt_editable": True,
    }
    prompt = {
        "id": PROMPT_ID,
        "version": "v1",
        "name": "Default prompt",
        "is_active": True,
        "is_default": True,
        "updated_at": "2026-06-02",
    }
    test_record = {
        "job_id": JOB_ID,
        "job_status": "succeeded",
        "latency_ms": 123,
        "error_code": None,
        "error_message": None,
    }

    summary = _settings_node_summary(node, prompts=[prompt], test_records=[test_record])

    assert summary["test_supported"] is True
    assert summary["queue_name"] == "llm"
    assert summary["default_prompt"]["version"] == "v1"
    assert summary["test_summary"]["latest_status"] == "succeeded"
    assert summary["test_summary"]["latest_latency_ms"] == 123
    assert summary["ui"]["show_prompt_editor"] is True
    assert summary["ui"]["show_sampling_options"] is True


def test_required_business_nodes_make_fallback_visible() -> None:
    nodes = [
        {
            "id": NODE_ID,
            "node_name": "buyer_intent_parser",
            "is_active": True,
            "is_default": True,
            "model_name": "legacy-model",
        },
        {
            "id": UUID("00000000-0000-0000-0000-000000000004"),
            "node_name": "buyer_intent_semantic_parser",
            "is_active": True,
            "is_default": True,
            "model_name": "semantic-model",
        },
    ]
    prompts = {
        "buyer_intent_parser": [{"is_active": True, "is_default": True}],
        "buyer_intent_semantic_parser": [{"is_active": True, "is_default": True}],
    }

    statuses = _required_business_node_statuses(
        nodes=nodes,
        prompts_by_node_name=prompts,
        latest_production_calls={
            "buyer_intent_semantic_parser": {
                "status": "failed",
                "error_message": "invalid output",
            }
        },
    )
    semantic = next(item for item in statuses if item["node_name"] == "buyer_intent_semantic_parser")
    normalizer = next(item for item in statuses if item["node_name"] == "buyer_intent_normalizer")

    assert semantic["ready"] is False  # 两阶段必须成对就绪
    assert semantic["using_fallback"] is True
    assert semantic["effective_node_name"] == "buyer_intent_parser"
    assert semantic["latest_production_call"]["error_message"] == "invalid output"
    assert normalizer["configured"] is False
    assert normalizer["using_fallback"] is True


def test_settings_node_summary_hides_prompt_editor_for_rerank() -> None:
    summary = _settings_node_summary(
        {
            "id": NODE_ID,
            "node_name": "recommendation_reranker",
            "node_type": "rerank",
            "is_active": True,
            "prompt_editable": False,
        },
        prompts=[],
        test_records=[],
    )

    assert summary["test_supported"] is True
    assert summary["queue_name"] == "rerank"
    assert summary["ui"]["show_prompt_editor"] is False
    assert summary["ui"]["show_sampling_options"] is False


def test_settings_page_overview_counts_nodes_and_tests() -> None:
    overview = _settings_page_overview(
        providers=[{"is_active": True}, {"is_active": False}],
        nodes=[
            {"node_type": "llm", "is_active": True, "prompt_editable": True, "test_supported": True},
            {"node_type": "embedding", "is_active": True, "prompt_editable": False, "test_supported": True},
        ],
        prompts=[{"id": PROMPT_ID}],
        node_test_records={
            str(NODE_ID): [
                {"job_status": "failed"},
                {"job_status": "running"},
                {"job_status": "succeeded"},
            ]
        },
    )

    assert overview["provider_count"] == 2
    assert overview["active_provider_count"] == 1
    assert overview["prompt_editable_node_count"] == 1
    assert overview["failed_test_count"] == 1
    assert overview["running_test_count"] == 1
    assert overview["node_type_counts"] == {"llm": 1, "embedding": 1}


def test_safe_queue_name_for_node_type() -> None:
    assert _safe_queue_name_for_node_type("embedding") == "embedding"
    assert _safe_queue_name_for_node_type("unknown") is None
