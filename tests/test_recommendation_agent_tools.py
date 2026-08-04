"""Agent tool contract: budgets hold, filters are whitelisted, digests stay small."""

from typing import Any

from backend.app.ai.llm_client import ToolCall
from backend.app.services.recommendation_agent_tools import (
    MAX_DETAIL_TARGETS_TOTAL,
    MAX_SEARCH_CALLS,
    MAX_SEARCH_RESULTS_PER_CALL,
    RECOMMENDATION_AGENT_TOOLS,
    RecommendationAgentTools,
    _candidate_digest,
    anchor_from_filters,
)
from backend.app.services.recommendation_flow import _enum_label, _money_text, _target_facts


def _call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments, raw_arguments="{}")


def _fake_search(count: int = 3, eligible: int = 47):
    def run(_db: Any, anchor: dict[str, Any], limit: int) -> dict[str, Any]:
        candidates = [
            {
                "seller_target_id": f"00000000-0000-0000-0000-00000000000{index}",
                "seller_target_name": f"标的{index}",
                "recommendation_level": "strong",
                "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "pe_ratio": 8.5},
                "evidence_json": {"matches": ["行业匹配", "净利达标"], "gaps": []},
                "missing_dimensions": ["负债率"],
            }
            for index in range(min(count, limit))
        ]
        return {
            "candidates": candidates,
            "funnel": {"eligible_count": eligible, "scan_count": 1200, "conflict_count": 5},
        }

    return run


# -- filter whitelist ----------------------------------------------------


def test_anchor_from_filters_keeps_only_known_condition_fields() -> None:
    anchor = anchor_from_filters(
        {
            "industries_json": ["制造业"],
            "min_net_profit_yuan": 20000000,
            "requires_control": "yes",
            "drop_table": "seller_target",  # 不在白名单
            "max_pe": "not-a-number",  # 类型错，被 coerce 丢掉
        }
    )

    assert anchor["industries_json"] == ["制造业"]
    assert anchor["min_net_profit_yuan"] == 20000000
    assert anchor["requires_control"] == "yes"
    assert "drop_table" not in anchor
    assert "max_pe" not in anchor


def test_anchor_has_no_id_so_it_can_never_become_a_persisted_intent() -> None:
    anchor = anchor_from_filters({"industries_json": ["制造业"]})

    assert anchor["id"] is None
    assert anchor["buyer_party_id"] is None


def test_anchor_survives_garbage_filters() -> None:
    assert anchor_from_filters(None)["id"] is None
    assert anchor_from_filters("industries")["industries_json"] == []


# -- budgets -------------------------------------------------------------


def test_search_budget_returns_an_error_the_model_can_read() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())

    for _ in range(MAX_SEARCH_CALLS):
        result = tools.execute(_call("search_targets", {"filters": {"industries_json": ["制造业"]}}))
        assert "error" not in result

    exhausted = tools.execute(_call("search_targets", {"filters": {"industries_json": ["制造业"]}}))
    assert "error" in exhausted
    assert len(tools.search_calls) == MAX_SEARCH_CALLS


def test_search_limit_is_clamped() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search(count=99))

    result = tools.execute(
        _call("search_targets", {"filters": {}, "limit": 500})
    )

    assert len(result["returned"]) == MAX_SEARCH_RESULTS_PER_CALL


def test_count_only_skips_candidate_payload() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())

    result = tools.execute(_call("search_targets", {"filters": {}, "count_only": True}))

    assert result["matched_count"] == 47
    assert "returned" not in result
    assert tools.search_calls[0]["returned_count"] == 0


def test_ask_user_is_capped_at_one_turn_and_stops_the_loop() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())

    first = tools.execute(
        _call("ask_user", {"questions": [{"question": "哪个方向？", "options": ["精密制造", "都可以"]}]})
    )
    second = tools.execute(
        _call("ask_user", {"questions": [{"question": "再问一个", "options": ["A", "B"]}]})
    )

    assert first["status"] == "asked"
    assert "error" in second
    assert tools.should_stop is True


def test_ask_user_truncates_to_three_questions() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())

    tools.execute(
        _call(
            "ask_user",
            {"questions": [{"question": f"Q{index}", "options": ["A"]} for index in range(6)]},
        )
    )

    assert len(tools.ask_user_payload["questions"]) == 3


def test_detail_budget_counts_across_calls() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())
    ids = [f"id-{index}" for index in range(MAX_DETAIL_TARGETS_TOTAL + 4)]

    # db 为 None，取详情会在 SQL 那步炸；这里只验预算记账，所以先塞满配额。
    tools.detail_target_ids.extend(ids[:MAX_DETAIL_TARGETS_TOTAL])
    result = tools.execute(_call("get_target_detail", {"target_ids": ids[MAX_DETAIL_TARGETS_TOTAL:]}))

    assert "error" in result


def test_unknown_tool_reports_instead_of_raising() -> None:
    tools = RecommendationAgentTools(db=None, search_targets_fn=_fake_search())

    assert "error" in tools.execute(_call("rm_rf", {}))


# -- digest --------------------------------------------------------------


def test_candidate_digest_carries_hard_numbers_and_stays_small() -> None:
    digest = _candidate_digest(
        {
            "seller_target_id": "abc",
            "seller_target_name": "杭州XX精密制造",
            "recommendation_level": "strong",
            "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "pe_ratio": 8.5},
            "evidence_json": {"matches": ["行业匹配"] * 20, "gaps": ["估值偏高"] * 9},
            "missing_dimensions": ["负债率"] * 9,
        }
    )

    assert digest["net_profit_text"] == "2800万"
    assert digest["pe_ratio"] == 8.5
    assert len(digest["matches"]) == 6
    assert len(digest["gaps"]) == 4
    assert len(digest["unknown"]) == 5


def test_digest_flags_progress_state_without_naming_the_other_side() -> None:
    digest = _candidate_digest(
        {
            "seller_target_id": "abc",
            "seller_target_name": "标的",
            "seller_target_has_other_deep_progress": True,
        }
    )

    assert digest["other_buyer_in_deep_progress"] is True
    assert "buyer" not in {key.replace("other_buyer_in_deep_progress", "") for key in digest}


# -- tool schemas --------------------------------------------------------


def test_every_tool_declares_a_json_schema() -> None:
    names = set()
    for tool in RECOMMENDATION_AGENT_TOOLS:
        function = tool["function"]
        names.add(function["name"])
        assert function["description"]
        assert function["parameters"]["type"] == "object"

    assert names == {"search_targets", "get_target_detail", "ask_user"}


# -- facts ---------------------------------------------------------------


def test_money_text_reads_like_a_person_wrote_it() -> None:
    assert _money_text(28000000) == "2800万"
    assert _money_text(240000000) == "2.4亿"
    assert _money_text(100000000) == "1亿"
    assert _money_text(None) is None


def test_enum_labels_come_from_the_indicator_registry() -> None:
    assert _enum_label("can_control", "yes") == "是"
    assert _enum_label("can_control", "unknown") is None
    assert _enum_label("can_control", "") is None


def test_target_facts_drops_unknowns_rather_than_reporting_them() -> None:
    facts = _target_facts(
        {
            "industry_l1": "制造业",
            "industry_l2": "精密制造",
            "location_province": "浙江",
            "location_city": "杭州",
            "current_net_profit_yuan": 28000000,
            "pe_ratio": 8.5,
            "can_control": "yes",
            "can_consolidate": "unknown",
        }
    )

    assert facts["industry"] == "制造业 / 精密制造"
    assert facts["region"] == "浙江杭州"
    assert facts["net_profit_text"] == "2800万"
    assert facts["can_control"] == "是"
    assert "can_consolidate" not in facts
