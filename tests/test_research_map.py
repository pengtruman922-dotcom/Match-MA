"""The normalization node: what it is handed, and what happens without it."""

import json
from uuid import UUID

from backend.app.jobs.handlers.research import (
    RESEARCH_MAPPER_NODE_NAME,
    _research_mapper_available,
)
from backend.app.jobs.handlers.research_map import (
    REPORT_TEXT_LIMIT,
    _mapping_context,
    _research_job_for_proposals,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.research_apply import RESEARCH_STRUCTURED_FIELDS


class _NoNodeDb:
    """一个还没配规范化节点的库。"""

    def execute(self, *args, **kwargs):
        class _Result:
            def mappings(self_inner):
                return self_inner

            def one_or_none(self_inner):
                return None

            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return []

        return _Result()


class _TaxonomyDb(_NoNodeDb):
    def __init__(self, terms):
        self._terms = terms

    def execute(self, *args, **kwargs):
        terms = self._terms

        class _Result:
            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return terms

        return _Result()


def test_missing_mapper_node_falls_back_instead_of_failing() -> None:
    """修复批次要能先于规范化节点单独发版验证。

    节点没配好时调研照旧自己采纳建议，而不是整条链路失效。
    """
    assert _research_mapper_available(_NoNodeDb()) is False


def test_mapping_context_hands_over_dictionaries_as_data_not_prose() -> None:
    """字段白名单、枚举取值、行业字典都是活的库状态。

    写进提示词就会随着字典更新而过期 —— prompt 要 industry_l1、白名单只收
    industry_pairs_json，是这轮全额丢弃事故的根因。
    """
    context = _mapping_context(
        _TaxonomyDb(["信息技术与通信", "医药与生命科学"]),
        report={"report_text": "报告正文", "agent_output_json": {}},
    )

    field_paths = {item["field_path"] for item in context["writable_fields"]}
    assert field_paths == RESEARCH_STRUCTURED_FIELDS
    assert context["industry_l1_terms"] == ["信息技术与通信", "医药与生命科学"]

    # 枚举取值随字段一起交付，模型不必去猜合法 code。
    listed = next(
        item for item in context["writable_fields"] if item["field_path"] == "listed_status"
    )
    assert {option["value"] for option in listed["allowed_values"]} >= {"listed", "unlisted"}

    # 金额字段明确要求原样带单位，换算留给代码。
    revenue = next(
        item for item in context["writable_fields"] if item["field_path"] == "current_revenue_yuan"
    )
    assert "unit" in revenue["note"]
    assert "万元" in context["money_units"]

    # 整份上下文要进 ai_trace 的 JSONB 绑定。
    json.dumps(context, ensure_ascii=False)


def test_report_text_is_capped_before_entering_the_prompt() -> None:
    """一份九模块报告正常几千字；明显超出的多半是模型跑飞了。"""
    from backend.app.jobs.handlers import research_map

    class _JobDb(_NoNodeDb):
        def execute(self, *args, **kwargs):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return {"report_text": "字" * (REPORT_TEXT_LIMIT + 5000)}

            return _Result()

    report = research_map._load_research_report(_JobDb(), "job-1")

    assert len(report["report_text"]) == REPORT_TEXT_LIMIT


def test_mapper_node_name_is_its_own_node() -> None:
    """规范化走独立节点，才能在设置页单独换模型和提示词版本。"""
    assert RESEARCH_MAPPER_NODE_NAME == "seller_target_research_mapper"


def test_mapper_attributes_proposals_to_the_original_research_job() -> None:
    mapping_job = JobClaim(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        job_type="seller_target_research_map",
        queue_name="research",
        entity_type="seller_target",
        entity_id=UUID("33333333-3333-3333-3333-333333333333"),
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=3,
    )

    original_id = UUID("11111111-1111-1111-1111-111111111111")
    proposal_job = _research_job_for_proposals(mapping_job, original_id)

    assert proposal_job.id == original_id
    assert proposal_job.job_type == "seller_target_research"
    assert proposal_job.entity_id == mapping_job.entity_id
