"""Agent turn contract: deep eval is visible before the code-held brief join."""

import importlib.util
import json
import pathlib
import sys
from typing import Any
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.api.routes.recommendations import (
    AGENT_INPUT_MAX_CHARS,
    RecommendationAgentTurnRequest,
)
from backend.app.jobs.handlers.recommendation import (
    _agent_finalize_after_auto_deep_eval,
    _build_answer_brief,
    _build_recommendation_agent_context,
)
from backend.app.ai.llm_client import ToolCall
from backend.app.services.screening_sql import ScreeningResult
from backend.app.registry.nodes import (
    recommendation_agent_node_by_mode,
    recommendation_answer_writer_node_by_mode,
)
from backend.app.services.recommendation_agent_tools import RecommendationAgentTools
from backend.app.services.recommendation_writer import WriterOutcome


def _agent_prompt_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_recommendation_agent_v020_prompt.py"
    spec = importlib.util.spec_from_file_location("publish_recommendation_agent_v020_prompt", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def _tools_with(
    candidates: dict[str, dict[str, Any]],
    *,
    ranked_ids: list[str] | None = None,
    dropped_ids: list[str] | None = None,
    deep_status: str = "ok",
) -> RecommendationAgentTools:
    tools = RecommendationAgentTools(db=None, target_facts_fn=dict, screen_targets_fn=lambda *_, **__: None)
    tools.candidates_by_id = candidates
    candidate_ids = list(candidates)
    tools.search_calls = [{
        "call_index": 1,
        "valid": True,
        "group_id": "fallback-0",
        "filters": {},
        "count_only": False,
        "eligible_count": len(candidate_ids),
        "returned_count": len(candidate_ids),
        "full_conditions": True,
        "relaxed_fields": [],
        "candidate_ids": candidate_ids,
    }]
    ranked = ranked_ids if ranked_ids is not None else candidate_ids
    tools.deep_eval_result = {
        "deep_eval_status": deep_status,
        "ranked": [
            {
                "id": candidate_id,
                "rank": index,
                "qualitative_verdicts": {},
                "fit_points": [],
                "risks": None,
                "info_gaps": None,
            }
            for index, candidate_id in enumerate(ranked, start=1)
        ] if deep_status == "ok" else [],
        "dropped": [{"id": candidate_id, "reason": "不满足"} for candidate_id in (dropped_ids or [])],
    }
    return tools


_CANDIDATE = {
    "seller_target_id": "t-1",
    "seller_target_name": "杭州XX精密制造",
    "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "pe_ratio": 8.5},
}


# -- 4C final-output and brief-v2 contract -------------------------------


def test_brief_drops_candidates_the_agent_invented() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})

    brief = _build_answer_brief(
        {
            "understanding": "华东精密制造",
            "recommended_ids": ["t-1", "t-does-not-exist"],
            "selection_notes": {"t-1": "产线互补"},
        },
        tools=tools,
        mode="buyer_to_target",
    )

    assert [item["id"] for item in brief["recommended"]] == ["t-1"]
    assert any("候选池外" in note for note in tools.final_output_normalization_notes)


def test_brief_takes_numbers_from_code_not_from_the_model() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})

    brief = _build_answer_brief(
        {
            "recommended": [
                {"id": "t-1", "facts": {"net_profit_text": "9999万"}, "name": "假名字"}
            ],
            "selection_notes": {"t-1": "假名字净利9999万"},
        },
        tools=tools,
        mode="buyer_to_target",
    )

    item = brief["recommended"][0]
    assert item["facts"]["net_profit_text"] == "2800万"
    assert item["name"] == "杭州XX精密制造"
    assert "selection_note" not in item
    assert tools.final_output_contract["selection_notes"] == {"t-1": "假名字净利9999万"}


def test_brief_survives_a_non_json_agent_answer() -> None:
    brief = _build_answer_brief(None, tools=_tools_with({}), mode="buyer_to_target")

    assert brief["recommended"] == []
    assert brief["intent_summary"] == "本轮按用户当前表达进行候选筛选"
    assert brief["mode"] == "buyer_to_target"
    assert brief["brief_version"] == 2


def test_brief_carries_progress_flags_without_naming_the_other_side() -> None:
    """只给布尔值，不泄露另一段关系的对象或阶段。

    原来还断言过 `already_in_progress`（本买家与这家标的的推进状态）。阶段五 5B
    删掉了它：新链路是无买家主体的自然语言会话，会话里没有 buyer_intent_id，
    这个字段在结构上算不出来，`relation_status` 一直是硬编码的 None。
    `other_buyer_in_deep_progress` 只需要 target_id，来源真实，留着。
    """
    tools = _tools_with(
        {
            "t-1": {
                **_CANDIDATE,
                "seller_target_has_other_deep_progress": True,
            }
        }
    )

    item = _build_answer_brief(
        {"recommended": [{"id": "t-1"}]}, tools=tools, mode="buyer_to_target"
    )["recommended"][0]

    assert "already_in_progress" not in item
    assert item["other_buyer_in_deep_progress"] is True


def test_brief_caps_list_sizes() -> None:
    tools = _tools_with({f"t-{index}": {**_CANDIDATE, "seller_target_id": f"t-{index}"} for index in range(20)})

    brief = _build_answer_brief(
        {
            "recommended": [
                {"id": f"t-{index}", "reason_points": ["点"] * 9} for index in range(20)
            ],
            "runner_ups": [{"id": f"t-{index}"} for index in range(6, 15)],
            "follow_up_suggestions": [f"再看第{index}批" for index in range(9)],
        },
        tools=tools,
        mode="buyer_to_target",
    )

    assert len(brief["recommended"]) == 6
    assert len(brief["runner_ups"]) == 5
    assert len(brief["follow_up_suggestions"]) == 4
    assert any("超过 6 家" in note for note in tools.final_output_normalization_notes)
    assert any("超过 5 家" in note for note in tools.final_output_normalization_notes)


def test_brief_uses_candidate_pool_count_not_the_last_matched_count() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})
    tools.search_calls = [
        {"call_index": 1, "valid": True, "group_id": "fallback-0", "eligible_count": 1200,
         "returned_count": 1, "candidate_ids": ["t-1"], "filters": {}, "full_conditions": True},
        {"call_index": 2, "valid": True, "group_id": "fallback-0", "eligible_count": 47,
         "returned_count": 1, "candidate_ids": ["t-1"], "filters": {}, "full_conditions": True},
        {"call_index": 3, "valid": True, "group_id": "fallback-0", "count_only": True,
         "eligible_count": 56, "candidate_ids": []},
    ]

    brief = _build_answer_brief({"recommended_ids": ["t-1"]}, tools=tools, mode="buyer_to_target")

    assert "total_eligible" not in brief
    assert brief["candidate_pool_count"] == 1
    assert [run["matched_count"] for run in brief["screening_runs"]] == [1200, 47, 56]


def test_deep_eval_30_candidates_agent_selects_exactly_four() -> None:
    candidates = {
        f"t-{index}": {**_CANDIDATE, "seller_target_id": f"t-{index}", "seller_target_name": f"标的{index}"}
        for index in range(30)
    }
    tools = _tools_with(candidates)

    brief = _build_answer_brief(
        {"recommended_ids": ["t-8", "t-3", "t-20", "t-1"]},
        tools=tools,
        mode="buyer_to_target",
    )

    assert brief["candidate_pool_count"] == 30
    assert [item["id"] for item in brief["recommended"]] == ["t-8", "t-3", "t-20", "t-1"]


def test_dropped_duplicate_and_pool_outside_ids_are_rejected_with_trace_notes() -> None:
    candidates = {f"t-{index}": {**_CANDIDATE, "seller_target_id": f"t-{index}"} for index in range(4)}
    tools = _tools_with(candidates, ranked_ids=["t-0", "t-1", "t-2"], dropped_ids=["t-3"])

    brief = _build_answer_brief(
        {"recommended_ids": ["t-0", "t-0", "t-3", "invented"]},
        tools=tools,
        mode="buyer_to_target",
    )

    assert [item["id"] for item in brief["recommended"]] == ["t-0", "t-1", "t-2"]
    joined = " | ".join(tools.final_output_normalization_notes)
    assert "重复 id" in joined
    assert "dropped id" in joined
    assert "候选池外" in joined


def test_required_relaxation_is_enriched_from_snapshot_and_source() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})
    tools.intent_snapshot = {
        "condition_groups": [{
            "label": "主方案",
            "conditions": {"min_net_profit_yuan": 10_000_000},
            "strength": {"min_net_profit_yuan": "required"},
        }],
        "qualitative_requirements": ["有海外仓"],
        "exclusions": {},
        "parser_status": "ok",
    }
    tools.search_calls[0].update({
        "group_id": "group-1",
        "filters": {},
        "full_conditions": False,
        "relaxed_fields": ["min_net_profit_yuan"],
        "relaxation_reason": "完整条件只命中 1 家",
        "based_on_call_index": 1,
    })
    tools.deep_eval_result["ranked"][0].update({
        "qualitative_verdicts": {"有海外仓": "无法判断"},
        "fit_points": ["业务方向相近"],
        "risks": "客户集中度待核实",
        "info_gaps": "缺少海外仓材料",
    })

    item = _build_answer_brief(
        {"recommended_ids": ["t-1"]}, tools=tools, mode="buyer_to_target"
    )["recommended"][0]

    assert item["required_relaxation"] is True
    assert item["relaxed_fields"] == [{
        "field": "min_net_profit_yuan",
        "label": "最低净利润",
        "strength": "required",
    }]
    assert item["risks"] == "客户集中度待核实"
    assert item["info_gaps"] == "缺少海外仓材料"


@pytest.mark.parametrize("deep_status", ["unavailable", "schema_mismatch"])
def test_deep_eval_degradation_is_explicit_agent_fallback(deep_status: str) -> None:
    tools = _tools_with({"t-1": _CANDIDATE}, deep_status=deep_status)

    brief = _build_answer_brief(
        {"recommended_ids": ["t-1"]}, tools=tools, mode="buyer_to_target"
    )

    assert brief["deep_eval_status"] == deep_status
    assert brief["selection_source"] == "agent_fallback"


def test_follow_up_suggestions_are_short_deduplicated_and_budget_safe() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})
    long = "请继续收窄行业和地区" * 20
    brief = _build_answer_brief(
        {
            "recommended_ids": ["t-1"],
            "follow_up_suggestions": [
                "细看杭州XX精密制造",
                "细看杭州XX精密制造",
                "列出全部56家候选",
                "打开 /targets/t-1",
                long,
                "再看下一批候选",
            ],
        },
        tools=tools,
        mode="buyer_to_target",
    )

    suggestions = brief["follow_up_suggestions"]
    assert suggestions[0] == "细看杭州XX精密制造"
    assert "再看下一批候选" in suggestions
    assert all(len(value) <= 80 for value in suggestions)
    assert not any("全部56家" in value or "/targets/" in value for value in suggestions)


def test_adviser_style_follow_up_suggestions_are_dropped_with_trace_notes() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})
    brief = _build_answer_brief(
        {
            "recommended_ids": ["t-1"],
            "follow_up_suggestions": [
                "明确是否要求控股",
                "建议补充地区限制",
                "可补充估值区间",
                "是否可以只看上市的",
                "净利放宽到500万",
            ],
        },
        tools=tools,
        mode="buyer_to_target",
    )

    assert brief["follow_up_suggestions"] == ["是否可以只看上市的", "净利放宽到500万"]
    assert any("顾问建议口吻" in note for note in tools.final_output_normalization_notes)


# -- 4A intent snapshot wiring -----------------------------------------


def test_agent_context_receives_the_real_intent_snapshot() -> None:
    snapshot = {
        "condition_groups": [{"label": "当前需求", "conditions": {"min_net_profit_yuan": 5000000}}],
        "qualitative_requirements": ["有成熟海外仓"],
        "exclusions": {"industries": ["房地产与建筑"], "risk_flags": []},
        "unstructured_notes": ["其他不变"],
        "raw_text": "净利放宽到500万，其他不变",
        "parser_status": "ok",
        "parser_notes": [],
        "prompt_version": "v0.3.0",
    }

    context = _build_recommendation_agent_context(
        user_message="净利放宽到500万，其他不变",
        intent_snapshot=snapshot,
    )

    assert context["intent_snapshot"] == {
        "condition_groups": snapshot["condition_groups"],
        "qualitative_requirements": snapshot["qualitative_requirements"],
        "exclusions": snapshot["exclusions"],
        "unstructured_notes": snapshot["unstructured_notes"],
        "parser_status": "ok",
    }
    assert context["intent_snapshot_policy"]["allow_agent_invent_structured_conditions"] is False
    assert context["search_group_catalog"][0]["group_id"] == "group-1"
    assert "history_context" not in context


@pytest.mark.parametrize("status", ["fallback", "schema_mismatch"])
def test_parser_degradation_clears_structured_conditions_before_the_agent(status: str) -> None:
    """就算降级结果意外夹带条件，主 Agent 边界也必须把它们清空。"""
    context = _build_recommendation_agent_context(
        user_message="杭州的制造业",
        intent_snapshot={
            "condition_groups": [{"conditions": {"min_net_profit_yuan": 99999999}}],
            "qualitative_requirements": ["模型编出来的"],
            "exclusions": {"industries": ["医药与健康"], "risk_flags": ["equity_frozen"]},
            "unstructured_notes": ["旧残留"],
            "parser_status": status,
        },
    )

    assert context["intent_snapshot"] == {
        "condition_groups": [],
        "qualitative_requirements": ["杭州的制造业"],
        "exclusions": {"industries": [], "risk_flags": []},
        "unstructured_notes": [],
        "parser_status": status,
    }
    assert context["intent_snapshot_policy"]["on_parser_failure"] == "只允许无条件初筛或向用户提问"
    assert context["search_group_catalog"] == [
        {
            "group_id": "fallback-0",
            "label": "无结构化条件",
            "conditions": {},
            "strength": {},
            "enforced_exclusions": {},
            "fallback": True,
        }
    ]


def test_abort_after_parsing_persists_understanding_but_never_enters_the_tool_loop(monkeypatch) -> None:
    from backend.app.jobs.handlers import recommendation as handler

    class Db:
        commits = 0

        def commit(self) -> None:
            self.commits += 1

    db = Db()
    session_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        # 真的 JobClaim 有这个字段。替身缺字段 = 把「调用方读了个不存在的属性」
        # 这种错误推迟到生产才发现。
        correlation_id=uuid4(),
        job_type="recommendation_agent",
        payload_json={
            "mode": "buyer_to_target",
            "turn_id": "turn-1",
            "user_message": "杭州制造业",
            "history_context": "<history_context>\n<user>：旧问题\n<AI>：旧回答\n</history_context>",
        },
    )
    snapshot = {
        "condition_groups": [{"conditions": {"industries_json": ["制造与工业"]}}],
        "qualitative_requirements": [],
        "exclusions": {"industries": [], "risk_flags": []},
        "unstructured_notes": [],
        "parser_status": "ok",
    }
    abort_checks = iter([False, True])
    persisted: list[dict[str, Any]] = []

    monkeypatch.setattr(handler, "_resolve_entity_id", lambda *_args, **_kwargs: session_id)
    monkeypatch.setattr(handler, "_get_default_node_config", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(handler, "agent_turn_aborted", lambda *_args, **_kwargs: next(abort_checks))
    monkeypatch.setattr(handler, "parse_recommendation_intent", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(
        handler,
        "_insert_agent_understanding_message",
        lambda *_args, **kwargs: persisted.append(kwargs["snapshot"]),
    )
    monkeypatch.setattr(
        handler,
        "run_tool_loop",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("中止后不得进入工具循环")),
    )

    result = handler._handle_recommendation_agent(db, job)

    assert result["outcome"] == "aborted"
    assert persisted == [snapshot]
    assert db.commits == 1


class _Usage:
    def __init__(self) -> None:
        self.llm_calls = 1
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.latency_ms = 10
        self.tool_calls_by_name: dict[str, int] = {}

    def record_llm(self, _result) -> None:
        self.llm_calls += 1


def _llm_result(payload: dict[str, Any]):
    return SimpleNamespace(
        parsed_output_json=payload,
        raw_output_text=json.dumps(payload, ensure_ascii=False),
    )


def test_auto_deep_eval_result_is_given_back_to_the_same_agent_without_tools(monkeypatch) -> None:
    from backend.app.jobs.handlers import recommendation as handler

    first = _llm_result({"recommended": [{"id": "t-1"}]})
    final = _llm_result({"deep_eval_status": "ok", "recommended": [{"id": "t-2"}]})
    loop = SimpleNamespace(
        result=first,
        messages=[{"role": "user", "content": "找制造业"}],
        usage=_Usage(),
        json_finalization_attempted=False,
    )
    captured: dict[str, Any] = {}

    def chat(*, messages, tools):
        captured["messages"] = messages
        captured["tools"] = tools
        return final

    monkeypatch.setattr(handler, "_agent_chat_caller", lambda _config, **_kwargs: chat)

    result = _agent_finalize_after_auto_deep_eval(
        loop,
        node_config={},
        deep_eval={"deep_eval_status": "ok", "ranked": [{"id": "t-2"}], "dropped": []},
    )

    assert result.result is final
    assert captured["tools"] is None
    assert "忘了调用必经的深评工具" in captured["messages"][-1]["content"]
    assert '"id": "t-2"' in captured["messages"][-1]["content"]
    assert result.usage.llm_calls == 2


def _exercise_handler_4b(
    monkeypatch,
    *,
    deep_status: str = "ok",
    abort_checks: list[bool] | None = None,
    writer_aborted: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from backend.app.jobs.handlers import recommendation as handler

    class EmptyRows:
        def mappings(self):
            return self

        def all(self):
            return []

        def one_or_none(self):
            # 会话锚点查询走这条路。返回 None 就是「这条会话没锚定买家」，
            # 也就是纯对话页的常态。
            return None

    class Db:
        commits = 0

        def commit(self):
            self.commits += 1

        def execute(self, *_args, **_kwargs):
            return EmptyRows()

    def screen(_db, conditions, *, limit, offset=0, count_only=False):
        rows = [] if count_only else [{
            "id": "t-1",
            "target_name": "标的一",
            "current_net_profit_yuan": 10_000_000,
        }]
        return ScreeningResult(
            conditions=dict(conditions),
            matched=1,
            excluded_by_condition={},
            rows=rows,
            ignored=[],
            limit=limit,
            offset=offset,
            count_only=count_only,
        )

    real_tools = RecommendationAgentTools

    def tools_factory(db, **kwargs):
        return real_tools(db, screen_targets_fn=screen, **kwargs)

    state: dict[str, Any] = {
        "deep_calls": 0,
        "finalize_calls": 0,
        "briefs": [],
        "deep_messages": [],
        "writer_briefs": [],
    }
    checks = iter(abort_checks or [])
    monkeypatch.setattr(handler, "RecommendationAgentTools", tools_factory)
    monkeypatch.setattr(handler, "_resolve_entity_id", lambda *_args, **_kwargs: uuid4())
    monkeypatch.setattr(
        handler,
        "_get_default_node_config",
        lambda *_args, **_kwargs: {
            "node_name": "recommendation_agent_to_target",
            "base_url": "https://example.invalid",
            "api_key_secret_ref": "x",
            "model_name": "test",
            "temperature": 0.2,
            "top_p": 1,
            "max_tokens": 1000,
            "timeout_seconds": 30,
            "response_format": "json_object",
        },
    )
    monkeypatch.setattr(handler, "agent_turn_aborted", lambda *_args, **_kwargs: next(checks, False))
    monkeypatch.setattr(
        handler,
        "parse_recommendation_intent",
        lambda *_args, **_kwargs: {
            "condition_groups": [],
            "qualitative_requirements": ["制造业"],
            "exclusions": {"industries": [], "risk_flags": []},
            "unstructured_notes": [],
            "parser_status": "fallback",
        },
    )
    monkeypatch.setattr(handler, "_render_prompt_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(handler, "_agent_image_inputs", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(handler, "build_agent_tools", lambda *_args, **_kwargs: [])
    for name in ("_insert_agent_understanding_message", "_insert_agent_step_message", "_insert_agent_question_message"):
        monkeypatch.setattr(handler, name, lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        handler,
        "_insert_agent_brief_message",
        lambda *_args, **kwargs: state["briefs"].append(kwargs["brief"]),
    )
    monkeypatch.setattr(
        handler,
        "_insert_agent_deep_eval_message",
        lambda *_args, **kwargs: state["deep_messages"].append(kwargs["result"]),
    )
    monkeypatch.setattr(handler, "_insert_recommendation_agent_trace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(handler, "_writer_node_config", lambda *_args, **_kwargs: None)

    def fake_writer(_db, **kwargs):
        state["writer_briefs"].append(kwargs["brief"])
        if writer_aborted:
            return WriterOutcome("aborted", "", "", None, 0)
        return WriterOutcome("answered", "fallback", "兜底正文", uuid4(), 47)

    monkeypatch.setattr(handler, "run_writer_stage", fake_writer)

    def run_loop(**kwargs):
        executor = kwargs["execute_tool"].__self__
        screened = executor.execute(
            ToolCall(
                id="s1",
                name="search_targets",
                arguments={"group_id": "fallback-0", "conditions": {}},
                raw_arguments="{}",
            )
        )
        assert screened["returned_count"] == 1
        return SimpleNamespace(
            result=_llm_result({"recommended": [{"id": "t-1"}]}),
            messages=[],
            usage=_Usage(),
            hit_iteration_limit=False,
            json_finalization_attempted=False,
        )

    monkeypatch.setattr(handler, "run_tool_loop", run_loop)

    def deep_eval(*_args, **kwargs):
        state["deep_calls"] += 1
        assert list(kwargs["candidates_by_id"]) == ["t-1"]
        return {
            "deep_eval_status": deep_status,
            "ranked": [{"id": "t-1", "rank": 1}] if deep_status == "ok" else [],
            "dropped": [],
            "uncovered": [],
            "notes": [],
        }

    monkeypatch.setattr(handler, "run_recommendation_deep_eval", deep_eval)

    def finalize(loop, **kwargs):
        state["finalize_calls"] += 1
        assert kwargs["deep_eval"]["deep_eval_status"] == deep_status
        loop.result = _llm_result(
            {"deep_eval_status": deep_status, "recommended": [{"id": "t-1"}]}
        )
        return loop

    monkeypatch.setattr(handler, "_agent_finalize_after_auto_deep_eval", finalize)
    db = Db()
    job = SimpleNamespace(
        id=uuid4(),
        # 真的 JobClaim 有这个字段。替身缺字段 = 把「调用方读了个不存在的属性」
        # 这种错误推迟到生产才发现。
        correlation_id=uuid4(),
        job_type="recommendation_agent",
        payload_json={
            "mode": "buyer_to_target",
            "turn_id": "turn-1",
            "user_message": "制造业",
            "history_context": "",
        },
    )
    return handler._handle_recommendation_agent(db, job), state


@pytest.mark.parametrize("deep_status", ["ok", "unavailable", "schema_mismatch"])
def test_agent_forgets_deep_eval_code_runs_it_and_turn_still_finishes(monkeypatch, deep_status) -> None:
    result, state = _exercise_handler_4b(monkeypatch, deep_status=deep_status)

    assert result["outcome"] == "answer_ready"
    assert result["deep_eval_status"] == deep_status
    assert state["deep_calls"] == 1
    assert state["finalize_calls"] == 1
    assert len(state["briefs"]) == 1
    assert state["deep_messages"][0]["auto_invoked"] is True
    # 这一轮不再停在 brief：同一个 job 接着把正文写完，前端不需要发起第二次调用。
    assert state["writer_briefs"] == state["briefs"]


@pytest.mark.parametrize(
    ("abort_checks", "expected_deep_calls"),
    [
        ([False, False, False, True], 0),
        ([False, False, False, False, True], 1),
    ],
)
def test_abort_before_or_after_deep_eval_never_writes_a_brief(
    monkeypatch,
    abort_checks,
    expected_deep_calls,
) -> None:
    result, state = _exercise_handler_4b(monkeypatch, abort_checks=abort_checks)

    assert result["outcome"] == "aborted"
    assert state["deep_calls"] == expected_deep_calls
    assert state["finalize_calls"] == 0
    assert state["briefs"] == []
    assert state["writer_briefs"] == []


def test_a_turn_stopped_while_the_writer_runs_reports_aborted(monkeypatch) -> None:
    """中止发生在正文段：brief 已经落库，但这一轮的终态是 aborted。"""
    result, state = _exercise_handler_4b(monkeypatch, writer_aborted=True)

    assert result["outcome"] == "aborted"
    assert len(state["briefs"]) == 1
    assert len(state["writer_briefs"]) == 1
    assert result["answer_generation_mode"] is None


# -- request contract ----------------------------------------------------


def test_agent_turn_accepts_a_long_pasted_requirement() -> None:
    request = RecommendationAgentTurnRequest(
        mode="buyer_to_target",
        user_message="需" * AGENT_INPUT_MAX_CHARS,
    )

    assert len(request.user_message) == AGENT_INPUT_MAX_CHARS


def test_agent_turn_rejects_input_beyond_the_limit() -> None:
    with pytest.raises(ValidationError):
        RecommendationAgentTurnRequest(
            mode="buyer_to_target",
            user_message="需" * (AGENT_INPUT_MAX_CHARS + 1),
        )


def test_agent_turn_rejects_the_reverse_direction_this_round() -> None:
    with pytest.raises(ValidationError):
        RecommendationAgentTurnRequest(mode="target_to_buyer", user_message="某企业拟出售")


# -- node wiring ---------------------------------------------------------


def test_only_the_forward_direction_is_registered_this_round() -> None:
    assert set(recommendation_agent_node_by_mode()) == {"buyer_to_target"}
    assert set(recommendation_answer_writer_node_by_mode()) == {"buyer_to_target"}


def test_early_stop_fires_on_ask_user_and_on_the_wall_clock() -> None:
    import time

    from backend.app.jobs.handlers.recommendation import _agent_early_stop

    tools = _tools_with({})
    now = time.perf_counter()
    budget = 240.0

    assert _agent_early_stop(tools, now, budget) is None
    assert "时间已用尽" in _agent_early_stop(tools, now - budget - 1, budget)

    tools.ask_user_payload = {"questions": []}
    assert "已向用户提问" in _agent_early_stop(tools, now, budget)


def test_the_turn_budget_comes_from_the_node_config_not_a_hardcoded_number() -> None:
    """0819 起 timeout_seconds 就是「这个节点这一次执行的整体超时」。

    改之前编排段写死 240 秒而生产节点配的是 600 —— 管理员在设置页调那个数字
    没有任何效果，两个数谁说了算也说不清。
    """
    import time

    from backend.app.jobs.handlers.recommendation import _agent_early_stop

    tools = _tools_with({})
    elapsed_90s_ago = time.perf_counter() - 90

    # 节点配 60 秒：90 秒前开始的这一轮早该收口了。
    assert "时间已用尽" in _agent_early_stop(tools, elapsed_90s_ago, 60.0)
    # 同一时刻、节点配 300 秒：还能接着跑。
    assert _agent_early_stop(tools, elapsed_90s_ago, 300.0) is None


def test_each_request_gets_the_smaller_of_node_timeout_and_time_left() -> None:
    """单次调用不能比它所属的那一轮还长。"""
    import time

    from backend.app.jobs.handlers.recommendation import _agent_chat_caller

    seen: list[int] = []

    def fake_call(**kwargs):
        seen.append(kwargs["timeout_seconds"])
        return None

    import backend.app.jobs.handlers.recommendation as handler

    original = handler.call_openai_compatible_chat
    handler.call_openai_compatible_chat = fake_call
    try:
        config = {
            "base_url": "", "api_key_secret_ref": "", "model_name": "m",
            "temperature": 0, "top_p": 1, "max_tokens": 10,
            "timeout_seconds": 300, "response_format": None,
        }
        # 一轮总预算 300，已经跑了 250 秒。剩余 50 秒低于收尾额度，取额度本身 ——
        # 剩余时间见底的那次调用恰恰就是收尾调用，按剩余时间给等于保证它超时。
        chat = _agent_chat_caller(
            config, started=time.perf_counter() - 250, budget_seconds=300.0
        )
        chat(messages=[], tools=None)
        assert seen[-1] == 60

        # 预算还很宽裕：取节点配置值本身，收尾额度不参与。
        chat = _agent_chat_caller(
            config, started=time.perf_counter() - 100, budget_seconds=300.0
        )
        chat(messages=[], tools=None)
        assert 190 <= seen[-1] <= 200

        # 预算充裕时，取节点配置值本身。
        chat = _agent_chat_caller(
            config, started=time.perf_counter(), budget_seconds=3000.0
        )
        chat(messages=[], tools=None)
        assert seen[-1] == 300

        # 节点本身配得比收尾额度还小时，下限跟着节点走 ——
        # 单次调用永远不许超过管理员配的那个数。
        chat = _agent_chat_caller(
            {**config, "timeout_seconds": 30},
            started=time.perf_counter() - 9999,
            budget_seconds=300.0,
        )
        chat(messages=[], tools=None)
        assert seen[-1] == 30
    finally:
        handler.call_openai_compatible_chat = original


def test_the_wrapup_call_is_never_starved_by_the_budget_that_triggered_it() -> None:
    """0820 生产事故：预算耗尽后的收尾调用只拿到 5 秒，必然超时，整轮硬失败。

    收尾调用是 early stop 的产物 —— 它出现的**前提**就是预算已经见底。用同一份
    见底的预算去算它的超时，得到的必然是下限；下限当时是 5 秒，于是这条路径在
    生产上 100% 失败，报的还是 `timed out after 5s`，把真正的原因盖住。矿业那个
    多组需求连挂两轮，两轮都是这条路。

    所以带工具的阶段必须提前收手，把收尾额度留出来。
    """
    import time

    from backend.app.jobs.handlers.recommendation import (
        _agent_chat_caller,
        _agent_early_stop,
        _agent_tool_phase_deadline,
    )
    import backend.app.jobs.handlers.recommendation as handler

    budget = 300.0
    tools = _tools_with({})
    # 工具阶段的截止线严格早于整轮预算，差值就是留给收尾的时间。
    deadline = _agent_tool_phase_deadline(budget)
    assert deadline == 240.0

    # 刚过截止线：early stop 发出收尾指令。
    started = time.perf_counter() - (deadline + 1)
    assert "时间已用尽" in _agent_early_stop(tools, started, budget)

    seen: list[int] = []

    def fake_call(**kwargs):
        seen.append(kwargs["timeout_seconds"])
        return None

    original = handler.call_openai_compatible_chat
    handler.call_openai_compatible_chat = fake_call
    try:
        config = {
            "base_url": "", "api_key_secret_ref": "", "model_name": "m",
            "temperature": 0, "top_p": 1, "max_tokens": 10,
            "timeout_seconds": 300, "response_format": None,
        }
        # 就是这一刻发出的收尾调用：必须拿到一个真能跑完的秒数。
        _agent_chat_caller(config, started=started, budget_seconds=budget)(
            messages=[], tools=None
        )
        assert seen[-1] == 60

        # 最后一次工具（生产上是深评，实测 200~250 秒）把预算冲爆之后同理。
        _agent_chat_caller(
            config, started=time.perf_counter() - 9999, budget_seconds=budget
        )(messages=[], tools=None)
        assert seen[-1] == 60
    finally:
        handler.call_openai_compatible_chat = original


def test_agent_and_writer_are_distinct_nodes() -> None:
    agent = recommendation_agent_node_by_mode()["buyer_to_target"]
    writer = recommendation_answer_writer_node_by_mode()["buyer_to_target"]

    assert agent != writer


# -- main Agent Prompt v0.2.0 ------------------------------------------


def test_agent_prompt_v020_uses_exactly_the_node_variables() -> None:
    from backend.app.ai.prompting import extract_template_variables
    from backend.app.registry.nodes import node_by_name

    prompt = _agent_prompt_module()
    spec = node_by_name(prompt.NODE_NAME)
    assert spec is not None
    assert prompt.VERSION == "v0.2.0"
    assert set(extract_template_variables(prompt.SYSTEM_PROMPT, prompt.USER_PROMPT_TEMPLATE)) == set(
        spec.prompt_variables
    )


def test_agent_prompt_v020_spells_out_the_4b_orchestration_contract() -> None:
    prompt = _agent_prompt_module()
    body = prompt.SYSTEM_PROMPT + prompt.USER_PROMPT_TEMPLATE

    for phrase in (
        "只读当前快照",
        "每组先完整真实筛",
        "based_on_call_index",
        "排除行业与重大风险",
        "deep_evaluate_candidates",
        "不能来自 `dropped`",
        "不能冒充多方案命中",
        "不要把深评机械截成前 5",
    ):
        assert phrase in body


def test_agent_prompt_v020_renders_both_variables() -> None:
    from backend.app.ai.prompting import render_template

    prompt = _agent_prompt_module()
    values = {
        "recommendation_context_json": json.dumps(
            {"intent_snapshot": {"parser_status": "ok"}, "search_group_catalog": []},
            ensure_ascii=False,
        ),
        "history_context": "<history_context>历史</history_context>",
    }
    rendered = render_template(prompt.SYSTEM_PROMPT, values) + render_template(
        prompt.USER_PROMPT_TEMPLATE, values
    )

    for name, value in values.items():
        assert "{{ " + name + " }}" not in rendered
        assert value in rendered


def test_agent_prompt_v020_same_version_conflict_exits_nonzero(monkeypatch) -> None:
    prompt = _agent_prompt_module()

    class FakeApi:
        @staticmethod
        def _resolve_token(_base):
            return "token"

        @staticmethod
        def _request_json(*_args, **_kwargs):
            return [{
                "version": prompt.VERSION,
                "system_prompt": "冲突正文",
                "user_prompt_template": prompt.USER_PROMPT_TEMPLATE,
                "output_schema_json": prompt.OUTPUT_SCHEMA,
                "variables_json": list(prompt.EXPECTED_VARIABLES),
            }]

    monkeypatch.setattr(prompt, "_api_client", lambda: FakeApi)
    monkeypatch.setattr(sys, "argv", ["publish_recommendation_agent_v020_prompt.py", "--dry-run"])

    assert prompt.main() != 0


def test_a_turn_with_candidates_is_forced_closed_instead_of_failing() -> None:
    """「完全无结果才失败」这条降级口径以前只写在文档里，代码从来没实现。

    `LlmCallError` 一路抛到 worker，把已经跑完的初筛、深评连同用户等的几分钟
    一起扔掉，页面只剩一句「这一轮没能跑完」。而最终名单本来就不依赖模型的收尾
    JSON —— 深评正常时来自 ranked，否则来自初筛顺序，都是代码持有的数据。
    """
    from backend.app.jobs.handlers.recommendation import _degraded_loop_from_candidates

    tools = _tools_with({"t-1": _CANDIDATE})
    loop = _degraded_loop_from_candidates(tools, [{"role": "user", "content": "找标的"}])

    assert loop is not None
    # 模型的收尾 JSON 就是没有 —— 这正是要证明的：没有它也能成篇。
    assert loop.result.parsed_output_json is None
    brief = _build_answer_brief(loop.result.parsed_output_json, tools=tools, mode="buyer_to_target")
    assert [item["id"] for item in brief["recommended"]] == ["t-1"]
    assert brief["deep_eval_status"] == "ok"


def test_forced_close_needs_something_to_close_with() -> None:
    """没有候选就是真的失败，不许拿一份空名单冒充答案。"""
    from backend.app.jobs.handlers.recommendation import _degraded_loop_from_candidates

    empty = RecommendationAgentTools(db=None, target_facts_fn=dict, screen_targets_fn=lambda *_, **__: None)
    assert _degraded_loop_from_candidates(empty, []) is None

    # 已经决定向用户提问：本轮的产出是问题，不是名单，也不该被收口成名单。
    asking = _tools_with({"t-1": _CANDIDATE})
    asking.ask_user_payload = {"questions": []}
    assert _degraded_loop_from_candidates(asking, []) is None


def test_timeout_trace_measures_wall_clock_not_the_sum_of_model_latencies() -> None:
    """预算是墙钟，比对它的那个数也必须是墙钟。

    成功路径传进来的 latency_ms 是**各次模型调用耗时之和**，不含工具执行。拿它
    去比预算，一轮真跑了 7 分钟、模型只占 30 秒的编排会报「没超预算」——
    而那一轮恰恰是被强制收口的。
    """
    from backend.app.jobs.handlers.recommendation import _timeout_trace_summary

    summary = _timeout_trace_summary(
        budget_seconds=300.0,
        elapsed_seconds=427.2,
        latency_ms=30_000,
        llm_calls=5,
    )
    assert summary["elapsed_seconds"] == 427.2
    assert summary["llm_seconds"] == 30.0
    assert summary["exhausted"] is True
    assert summary["llm_calls_when_exhausted"] == 5
    assert summary["wrapup_reserve_seconds"] == 60.0

    # 工具阶段截止线之前收工的一轮，不算用尽。
    healthy = _timeout_trace_summary(
        budget_seconds=300.0, elapsed_seconds=120.0, latency_ms=90_000, llm_calls=3
    )
    assert healthy["exhausted"] is False
    assert healthy["llm_calls_when_exhausted"] is None
