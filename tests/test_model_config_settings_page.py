from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.routes.model_config import (
    CatalogNodeConfigIn,
    _catalog_placeholder_row,
    _prompt_seed,
    _validate_prompt_payload,
    _group_prompts_by_node_name,
    _safe_queue_name_for_node_type,
    _settings_node_summary,
    _settings_page_overview,
    _required_business_node_statuses,
    upsert_catalog_node,
)
from backend.app.registry.nodes import node_by_name

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

    # rerank worker 已下线：节点既不可编 Prompt，也不再支持异步测试。
    assert summary["test_supported"] is False
    assert summary["queue_name"] is None
    assert summary["ui"]["show_prompt_editor"] is False
    assert summary["ui"]["show_sampling_options"] is False
    assert summary["ui"]["show_test_button"] is False


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
    assert _safe_queue_name_for_node_type("llm") == "llm"
    assert _safe_queue_name_for_node_type("ocr") == "ocr"
    # 已下线的 worker 队列必须返回 None，否则测试任务会被投进无人消费的队列。
    assert _safe_queue_name_for_node_type("embedding") is None
    assert _safe_queue_name_for_node_type("rerank") is None
    assert _safe_queue_name_for_node_type("unknown") is None


def test_catalog_placeholder_looks_like_an_unconfigured_node() -> None:
    """未建配置的目录节点也要能进 nodes 数组，且结构化参数取自代码目录。"""
    spec = node_by_name("buyer_intent_semantic_parser")
    assert spec is not None

    summary = _settings_node_summary(
        _catalog_placeholder_row(spec),
        prompts=[],
        test_records=[],
        latest_production_call=None,
    )

    assert summary["configured"] is False
    assert summary["id"] is None
    assert summary["model_name"] is None
    assert summary["label"] == "买家需求语义解析"
    assert summary["domain"] == "buyer"
    # 结构化字段来自注册表，管理员只需要挑模型。
    assert summary["node_type"] == spec.node_type
    assert summary["output_mode"] == spec.output_mode
    assert summary["response_format"] == spec.response_format
    assert summary["timeout_seconds"] == spec.default_timeout_seconds
    # 「与」组关系必须下发，否则设置页写不出「需与 XX 同时就绪」。
    assert summary["understudy"] == "buyer_intent_parser"
    assert summary["understudy_kind"] == "and"
    assert summary["understudy_group"] == ["buyer_intent_normalizer"]


def test_configured_node_is_marked_configured() -> None:
    summary = _settings_node_summary(
        {"id": NODE_ID, "node_name": "seller_target_parser", "node_type": "llm",
         "is_active": True, "is_default": True, "prompt_editable": True},
        prompts=[],
        test_records=[],
    )

    assert summary["configured"] is True
    assert summary["registered"] is True


@pytest.mark.parametrize(
    "node_name",
    [
        "not_a_real_node",              # 目录里没有
        "recommendation_reranker",      # 已退役，不允许再建配置
    ],
)
def test_catalog_upsert_rejects_nodes_outside_the_catalog(node_name: str) -> None:
    """节点是代码资产：设置页不能凭任意 node_name 创建节点。"""
    payload = CatalogNodeConfigIn(provider_config_id=uuid4())

    with pytest.raises(HTTPException) as excinfo:
        upsert_catalog_node(node_name, payload, db=None)

    assert excinfo.value.status_code == 404


def test_catalog_upsert_payload_cannot_carry_structural_fields() -> None:
    """node_type / output_mode / response_format 不在请求体里，调用方无从干预。"""
    fields = set(CatalogNodeConfigIn.model_fields)

    assert fields == {"provider_config_id", "temperature", "top_p", "max_tokens", "timeout_seconds"}


def _understudy_prompt(system: str | None, user: str | None, version: str = "v0.7.0") -> dict:
    return {"version": version, "system_prompt": system, "user_prompt_template": user,
            "output_schema_json": {"type": "object"}}


def test_prompt_seed_offers_copy_when_variables_are_covered() -> None:
    """方向深评与共用深评的变量完全相同，复制过来就能改，是个真起点。"""
    spec = node_by_name("recommendation_deep_eval_to_target")
    assert spec is not None

    seed = _prompt_seed(
        spec,
        has_own_prompt=False,
        understudy_prompt=_understudy_prompt(
            "你是评估助手。方向：{{ mode }}",
            "{{ anchor_context }}\n候选：{{ candidates_json }}",
            version="v0.2.0",
        ),
    )

    assert seed is not None
    assert seed["compatible"] is True
    assert seed["source_node_name"] == "recommendation_deep_eval"
    assert seed["source_version"] == "v0.2.0"
    assert seed["extra_variables"] == []
    assert seed["user_prompt_template"] is not None


def test_prompt_seed_refuses_copy_when_understudy_uses_unavailable_variables() -> None:
    """买家新建解析会拿到行业字典，语义解析节点不会。

    照抄会把 {{ industry_l1_list }} 带进一个收不到该变量的节点，渲染时变成
    "null" 字面量塞给模型 —— 比空白更糟，所以只给理由不给内容。
    """
    spec = node_by_name("buyer_intent_semantic_parser")
    assert spec is not None

    seed = _prompt_seed(
        spec,
        has_own_prompt=False,
        understudy_prompt=_understudy_prompt(
            None,
            "行业：{{ industry_l1_list }}\n材料：{{ raw_requirement_text }}",
        ),
    )

    assert seed is not None
    assert seed["compatible"] is False
    assert seed["extra_variables"] == ["industry_l1_list"]
    # 不兼容时绝不下发内容，避免页面「不小心」把它填进编辑器。
    assert seed["system_prompt"] is None
    assert seed["user_prompt_template"] is None


def test_prompt_seed_is_absent_when_not_applicable() -> None:
    semantic = node_by_name("buyer_intent_semantic_parser")
    standalone = node_by_name("seller_target_parser")
    assert semantic is not None and standalone is not None

    # 已经有自己的提示词
    assert _prompt_seed(semantic, has_own_prompt=True, understudy_prompt=_understudy_prompt(None, "{{ raw_requirement_text }}")) is None
    # 代跑节点也没发布提示词
    assert _prompt_seed(semantic, has_own_prompt=False, understudy_prompt=None) is None
    # 本来就没有代跑节点
    assert _prompt_seed(standalone, has_own_prompt=False, understudy_prompt=_understudy_prompt(None, "x")) is None
    # 未登记节点
    assert _prompt_seed(None, has_own_prompt=False, understudy_prompt=_understudy_prompt(None, "x")) is None


def test_prompt_can_be_written_before_a_model_is_picked() -> None:
    """目录里已声明、还没选模型的节点必须能先准备提示词。

    旧实现要求先有默认模型节点，于是「写提示词」和「启用节点」被绑死：
    建号那一刻节点就生效了，没法先把提示词准备好再决定何时启用。
    """
    # db 传 None 即可证明它没走库查询这条路。
    _validate_prompt_payload(None, "buyer_intent_semantic_parser", "jinja")
    _validate_prompt_payload(None, "recommendation_deep_eval_to_target", "jinja")


def test_prompt_is_rejected_for_nodes_that_have_none() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _validate_prompt_payload(None, "ocr_attachment_parser", "jinja")
    assert excinfo.value.status_code == 400

    with pytest.raises(HTTPException) as excinfo:
        _validate_prompt_payload(None, "embedding_seller_doc", "jinja")
    assert excinfo.value.status_code == 400
