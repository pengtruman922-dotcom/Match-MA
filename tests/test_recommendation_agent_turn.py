"""Agent turn contract: the brief joins model picks to code-held facts."""

from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.api.routes.recommendations import (
    AGENT_INPUT_MAX_CHARS,
    RecommendationAgentTurnRequest,
)
from backend.app.jobs.handlers.recommendation import _build_answer_brief
from backend.app.registry.nodes import (
    recommendation_agent_node_by_mode,
    recommendation_answer_writer_node_by_mode,
)
from backend.app.services.recommendation_agent_tools import RecommendationAgentTools


def _tools_with(candidates: dict[str, dict[str, Any]]) -> RecommendationAgentTools:
    tools = RecommendationAgentTools(db=None, search_targets_fn=lambda *_: {})
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
