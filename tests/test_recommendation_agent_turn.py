"""Agent turn contract: the brief joins model picks to code-held facts."""

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
    _build_answer_brief,
    _build_recommendation_agent_context,
)
from backend.app.registry.nodes import (
    recommendation_agent_node_by_mode,
    recommendation_answer_writer_node_by_mode,
)
from backend.app.services.recommendation_agent_tools import RecommendationAgentTools


def _tools_with(candidates: dict[str, dict[str, Any]]) -> RecommendationAgentTools:
    tools = RecommendationAgentTools(db=None, target_facts_fn=dict, screen_targets_fn=lambda *_, **__: None)
    tools.candidates_by_id = candidates
    return tools


_CANDIDATE = {
    "seller_target_id": "t-1",
    "seller_target_name": "杭州XX精密制造",
    "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "pe_ratio": 8.5},
}


# -- the hallucinated-id guard -------------------------------------------


def test_brief_drops_candidates_the_agent_invented() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})

    brief = _build_answer_brief(
        {
            "understanding": "华东精密制造",
            "recommended": [
                {"id": "t-1", "reason_points": ["产线互补"]},
                {"id": "t-does-not-exist", "reason_points": ["凭空捏造"]},
            ],
        },
        tools=tools,
        mode="buyer_to_target",
    )

    assert [item["id"] for item in brief["recommended"]] == ["t-1"]


def test_brief_takes_numbers_from_code_not_from_the_model() -> None:
    tools = _tools_with({"t-1": _CANDIDATE})

    brief = _build_answer_brief(
        {"recommended": [{"id": "t-1", "facts": {"net_profit_text": "9999万"}, "name": "假名字"}]},
        tools=tools,
        mode="buyer_to_target",
    )

    item = brief["recommended"][0]
    assert item["facts"]["net_profit_text"] == "2800万"
    assert item["name"] == "杭州XX精密制造"


def test_brief_survives_a_non_json_agent_answer() -> None:
    brief = _build_answer_brief(None, tools=_tools_with({}), mode="buyer_to_target")

    assert brief["recommended"] == []
    assert brief["understanding"] is None
    assert brief["mode"] == "buyer_to_target"


def test_brief_carries_progress_flags_without_naming_the_other_side() -> None:
    tools = _tools_with(
        {
            "t-1": {
                **_CANDIDATE,
                "relation_status": "contacted",
                "seller_target_has_other_deep_progress": True,
            }
        }
    )

    item = _build_answer_brief(
        {"recommended": [{"id": "t-1"}]}, tools=tools, mode="buyer_to_target"
    )["recommended"][0]

    assert item["already_in_progress"] == "contacted"
    assert item["other_buyer_in_deep_progress"] is True


def test_brief_caps_list_sizes() -> None:
    tools = _tools_with({f"t-{index}": {**_CANDIDATE, "seller_target_id": f"t-{index}"} for index in range(20)})

    brief = _build_answer_brief(
        {
            "recommended": [
                {"id": f"t-{index}", "reason_points": ["点"] * 9} for index in range(20)
            ],
            "runner_ups": [{"name": f"备选{index}"} for index in range(9)],
            "follow_up_suggestions": [f"建议{index}" for index in range(9)],
        },
        tools=tools,
        mode="buyer_to_target",
    )

    assert len(brief["recommended"]) == 10
    assert len(brief["recommended"][0]["reason_points"]) == 5
    assert len(brief["runner_ups"]) == 5
    assert len(brief["follow_up_suggestions"]) == 4


def test_brief_reports_the_last_eligible_count_the_agent_actually_saw() -> None:
    tools = _tools_with({})
    tools.search_calls = [
        {"eligible_count": 1200},
        {"eligible_count": 47},
        {"count_only": True, "eligible_count": 56},
    ]

    brief = _build_answer_brief({}, tools=tools, mode="buyer_to_target")

    assert brief["total_eligible"] == 56
    assert len(brief["search_story"]) == 3


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

    from backend.app.jobs.handlers.recommendation import (
        AGENT_WALL_CLOCK_BUDGET_SECONDS,
        _agent_early_stop,
    )

    tools = _tools_with({})
    now = time.perf_counter()

    assert _agent_early_stop(tools, now) is None
    assert "时间已用尽" in _agent_early_stop(tools, now - AGENT_WALL_CLOCK_BUDGET_SECONDS - 1)

    tools.ask_user_payload = {"questions": []}
    assert "已向用户提问" in _agent_early_stop(tools, now)


def test_agent_and_writer_are_distinct_nodes() -> None:
    agent = recommendation_agent_node_by_mode()["buyer_to_target"]
    writer = recommendation_answer_writer_node_by_mode()["buyer_to_target"]

    assert agent != writer
