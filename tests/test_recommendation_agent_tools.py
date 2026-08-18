"""Agent tool contract: budgets hold, exclusions stick, digests stay small."""

from decimal import Decimal
from typing import Any

from backend.app.ai.llm_client import ToolCall
from backend.app.services.recommendation_agent_tools import (
    MAX_DETAIL_TARGETS_TOTAL,
    MAX_SEARCH_CALLS,
    MAX_SEARCH_RESULTS_PER_CALL,
    RecommendationAgentTools,
    build_agent_tools,
)
from backend.app.services.recommendation_flow import _enum_label, _money_text, _target_facts
from backend.app.services.screening_sql import ScreeningResult


def _call(name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id="call_1", name=name, arguments=arguments, raw_arguments="{}")


class _EmptyResult:
    def mappings(self) -> "_EmptyResult":
        return self

    def all(self) -> list[dict]:
        return []

    def scalars(self) -> "_EmptyResult":
        return self


class _QuietDb:
    """Answers every query with nothing — enough for the relation annotation."""

    def execute(self, *_args, **_kwargs) -> _EmptyResult:
        return _EmptyResult()


def _row(index: int) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-0000-0000-00000000000{index}",
        "target_name": f"标的{index}",
        "target_grade": "B",
        "industry_pairs_json": [{"l1": "制造与工业", "l2": "专用设备"}],
        "location_province": "浙江省",
        "location_city": "杭州市",
        "current_net_profit_yuan": Decimal("28000000"),
    }


def _fake_screen(count: int = 3, matched: int = 47):
    def run(
        _db: Any,
        conditions: Any,
        *,
        limit: int,
        offset: int = 0,
        count_only: bool = False,
    ) -> ScreeningResult:
        rows = [] if count_only else [_row(index) for index in range(min(count, limit))]
        return ScreeningResult(
            conditions=dict(conditions or {}),
            matched=matched,
            excluded_by_condition={},
            rows=rows,
            ignored=[],
            limit=limit,
            offset=offset,
            count_only=count_only,
        )

    return run


def _tools(**kwargs) -> RecommendationAgentTools:
    kwargs.setdefault("screen_targets_fn", _fake_screen())
    return RecommendationAgentTools(db=_QuietDb(), target_facts_fn=dict, **kwargs)


def _search_args(
    conditions: dict[str, Any] | None = None,
    *,
    group_id: str = "fallback-0",
    **extra: Any,
) -> dict[str, Any]:
    return {"group_id": group_id, "conditions": conditions or {}, **extra}


def _snapshot(*groups: dict[str, Any], exclusions: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "condition_groups": list(groups),
        "exclusions": exclusions or {"industries": [], "risk_flags": []},
    }


# -- budgets -------------------------------------------------------------


def test_search_budget_returns_an_error_the_model_can_read() -> None:
    tools = _tools()

    for _ in range(MAX_SEARCH_CALLS):
        result = tools.execute(_call("search_targets", _search_args()))
        assert "error" not in result

    exhausted = tools.execute(_call("search_targets", _search_args()))
    assert "error" in exhausted
    assert len(tools.search_calls) == MAX_SEARCH_CALLS


def test_search_limit_is_clamped() -> None:
    tools = _tools(screen_targets_fn=_fake_screen(count=99))

    result = tools.execute(_call("search_targets", _search_args(limit=500)))

    assert len(result["returned"]) == MAX_SEARCH_RESULTS_PER_CALL


def test_count_only_skips_candidate_payload() -> None:
    tools = _tools()

    result = tools.execute(_call("search_targets", _search_args(count_only=True)))

    assert result["matched"] == 47
    assert "returned" not in result
    assert tools.search_calls[0]["returned_count"] == 0


def test_legacy_filters_key_is_still_accepted() -> None:
    """改造前的参数名叫 filters，线上提示词还在用它，不能因为改名就筛空。"""
    tools = _tools(
        intent_snapshot=_snapshot(
            {"conditions": {"industries_json": ["制造与工业"]}, "strength": {}}
        )
    )

    result = tools.execute(
        _call(
            "search_targets",
            {"group_id": "group-1", "filters": {"industries_json": ["制造与工业"]}},
        )
    )

    assert result["conditions"] == {"industries_json": ["制造与工业"]}


def test_exclusions_stick_to_every_later_call() -> None:
    """用户说不要的东西，agent 放宽多少次都还是不要 —— 工具层强制，不靠自觉。"""
    tools = _tools(
        intent_snapshot=_snapshot(
            {
                "conditions": {"industries_json": ["制造与工业"]},
                "strength": {"industries_json": "preferred"},
            },
            exclusions={"industries": ["房地产与建筑"], "risk_flags": ["equity_frozen"]},
        )
    )

    tools.execute(
        _call(
            "search_targets",
            _search_args({"industries_json": ["制造与工业"]}, group_id="group-1"),
        )
    )
    relaxed = tools.execute(
        _call(
            "search_targets",
            _search_args(
                group_id="group-1",
                relaxation_reason="调用1显示 preferred 行业条件需要放宽",
                based_on_call_index=1,
            ),
        )
    )

    assert relaxed["conditions"]["excluded_industries_json"] == ["房地产与建筑"]
    assert relaxed["conditions"]["unacceptable_risk_flags_json"] == ["equity_frozen"]


def test_ask_user_is_capped_at_one_turn_and_stops_the_loop() -> None:
    tools = _tools()

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
    tools = _tools()

    tools.execute(
        _call(
            "ask_user",
            {"questions": [{"question": f"Q{index}", "options": ["A"]} for index in range(6)]},
        )
    )

    assert len(tools.ask_user_payload["questions"]) == 3


def test_detail_budget_counts_across_calls() -> None:
    tools = _tools()
    ids = [f"id-{index}" for index in range(MAX_DETAIL_TARGETS_TOTAL + 4)]

    tools.detail_target_ids.extend(ids[:MAX_DETAIL_TARGETS_TOTAL])
    result = tools.execute(_call("get_target_detail", {"target_ids": ids[MAX_DETAIL_TARGETS_TOTAL:]}))

    assert "error" in result


def test_unknown_tool_reports_instead_of_raising() -> None:
    tools = _tools()

    assert "error" in tools.execute(_call("rm_rf", {}))


# -- screened candidates are registered for the writer --------------------


def test_screened_rows_become_candidates_with_code_held_facts() -> None:
    """正文里的数字来自这份 facts，不来自模型重打的那一遍。"""
    tools = RecommendationAgentTools(
        db=_QuietDb(),
        target_facts_fn=_target_facts,
        screen_targets_fn=_fake_screen(count=1),
    )

    tools.execute(_call("search_targets", _search_args()))

    candidate = tools.candidates_by_id["00000000-0000-0000-0000-000000000000"]
    assert candidate["seller_target_name"] == "标的0"
    assert candidate["facts"]["net_profit_text"] == "2800万"


# -- 命中组数（用例 10）---------------------------------------------------


def test_a_target_hit_by_two_groups_has_two_group_and_search_hits() -> None:
    tools = _tools(
        intent_snapshot=_snapshot(
            {"conditions": {"industries_json": ["制造与工业"]}},
            {"conditions": {"industries_json": ["信息技术与通信"]}},
        )
    )

    tools.execute(
        _call(
            "search_targets",
            _search_args({"industries_json": ["制造与工业"]}, group_id="group-1"),
        )
    )
    tools.execute(
        _call(
            "search_targets",
            _search_args({"industries_json": ["信息技术与通信"]}, group_id="group-2"),
        )
    )

    source = tools.candidate_pool().source_for("00000000-0000-0000-0000-000000000000")
    assert len(tools.candidates_by_id) == 3
    assert source["group_hit_count"] == 2
    assert source["search_hit_count"] == 2


def test_search_hits_do_not_change_the_first_seen_candidate_payload() -> None:
    """首见为准是对的 —— 候选内容在多次查询之间没有差异，后见覆盖只会让结果不可复现。"""
    tools = _tools()
    tools.execute(_call("search_targets", _search_args()))
    first = tools.candidates_by_id["00000000-0000-0000-0000-000000000000"]

    tools.execute(_call("search_targets", _search_args()))

    assert tools.candidates_by_id["00000000-0000-0000-0000-000000000000"] is first
    source = tools.candidate_pool().source_for("00000000-0000-0000-0000-000000000000")
    assert source["group_hit_count"] == 1
    assert source["search_hit_count"] == 2


def test_count_only_searches_do_not_form_candidate_sources() -> None:
    """count_only 不返回候选明细，也就没有「命中了谁」这回事。"""
    tools = _tools()

    tools.execute(_call("search_targets", _search_args(count_only=True)))

    assert tools.candidate_pool().candidate_ids == ()


def test_trace_payload_carries_pool_counts_and_sources() -> None:
    tools = _tools()
    tools.execute(_call("search_targets", _search_args()))

    trace = tools.as_trace_payload()
    assert trace["candidate_pool"]["unique_after_cap"] == 3
    assert trace["candidate_sources"]["00000000-0000-0000-0000-000000000000"]["group_hit_count"] == 1


# -- controlled deep-eval tool ------------------------------------------


def test_deep_eval_requires_a_real_candidate_batch() -> None:
    tools = _tools(deep_eval_fn=lambda **_: {"deep_eval_status": "ok"})

    result = tools.execute(_call("deep_evaluate_candidates", {}))

    assert result["error"]["code"] == "deep_eval_requires_real_candidates"
    assert tools.deep_eval_called is False
    assert tools.screening_frozen is False


def test_deep_eval_runs_once_and_freezes_search_and_detail() -> None:
    calls: list[dict[str, Any]] = []

    def evaluate(**kwargs):
        calls.append(kwargs)
        ids = list(kwargs["candidates_by_id"])
        return {
            "deep_eval_status": "ok",
            "ranked": [{"id": value, "rank": index + 1} for index, value in enumerate(ids)],
            "dropped": [],
            "uncovered": [],
        }

    tools = _tools(deep_eval_fn=evaluate)
    tools.execute(_call("search_targets", _search_args()))

    first = tools.execute(_call("deep_evaluate_candidates", {}))
    second = tools.execute(_call("deep_evaluate_candidates", {}))
    later_search = tools.execute(_call("search_targets", _search_args()))
    later_detail = tools.execute(_call("get_target_detail", {"target_ids": ["t-1"]}))

    assert first["deep_eval_status"] == "ok"
    assert first["candidate_pool"]["unique_after_cap"] == 3
    assert len(calls) == 1
    assert second["error"]["code"] == "deep_eval_already_called"
    assert later_search["error"]["code"] == "screening_frozen"
    assert later_detail["error"]["code"] == "screening_frozen"


def test_deep_eval_schema_mismatch_is_returned_without_being_disguised() -> None:
    tools = _tools(
        deep_eval_fn=lambda **_: {
            "deep_eval_status": "schema_mismatch",
            "ranked": [],
            "dropped": [],
            "uncovered": [],
            "notes": ["schema mismatch"],
        }
    )
    tools.execute(_call("search_targets", _search_args()))

    result = tools.execute(_call("deep_evaluate_candidates", {}))

    assert result["deep_eval_status"] == "schema_mismatch"
    assert tools.screening_frozen is True


def test_invalid_search_is_structured_traced_and_spends_budget() -> None:
    tools = _tools()

    result = tools.execute(
        _call(
            "search_targets",
            {"group_id": "missing", "conditions": {"min_net_profit_yuan": 1}},
        )
    )

    assert result["error"]["code"] == "unknown_group"
    assert len(tools.search_calls) == 1
    assert tools.search_calls[0]["valid"] is False
    assert tools.as_trace_payload()["policy_errors"]


# -- tool schemas --------------------------------------------------------


def test_every_tool_declares_a_json_schema() -> None:
    names = set()
    for tool in build_agent_tools(_QuietDb()):
        function = tool["function"]
        names.add(function["name"])
        assert function["description"]
        assert function["parameters"]["type"] == "object"

    assert names == {
        "search_targets",
        "get_target_detail",
        "deep_evaluate_candidates",
        "ask_user",
    }


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


# -- 按 id 取详情的标的也要登记成候选 --------------------------------------


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


class _FakeDb:
    """Answers the two queries `_get_target_detail` makes, in order."""

    def __init__(self, target_rows: list[dict], deep_rows: list[dict]) -> None:
        self._results = [_FakeResult(target_rows), _FakeResult(deep_rows)]

    def execute(self, *_args, **_kwargs) -> _FakeResult:
        return self._results.pop(0)


def _detail_tools(monkeypatch, target_rows, deep_rows=()):
    monkeypatch.setattr(
        "backend.app.services.recommendation_agent_tools.load_profile_sections",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        "backend.app.services.recommendation_agent_tools.render_profile_text",
        lambda *args, **kwargs: "",
    )
    return RecommendationAgentTools(
        db=_FakeDb(list(target_rows), list(deep_rows)),
        target_facts_fn=lambda row: {"net_profit_text": "2800万", "region": row["location_city"]},
        screen_targets_fn=_fake_screen(),
    )


_DETAIL_ROW = {
    "id": "t-9",
    "target_name": "杭州XX精密制造",
    "business_summary": "精密件",
    "transaction_summary": None,
    "risk_summary": None,
    "gap_summary": None,
    "location_city": "杭州",
}


def test_detail_registers_the_target_so_a_follow_up_can_recommend_it(monkeypatch) -> None:
    """跟进问题拿的是上一轮正文里的 id，不登记就会被最终那道 join 丢掉。"""
    tools = _detail_tools(monkeypatch, [_DETAIL_ROW])

    tools.execute(_call("get_target_detail", {"target_ids": ["t-9"]}))

    candidate = tools.candidates_by_id["t-9"]
    assert candidate["seller_target_name"] == "杭州XX精密制造"
    assert candidate["facts"]["net_profit_text"] == "2800万"


def test_detail_still_carries_the_other_buyer_warning(monkeypatch) -> None:
    tools = _detail_tools(monkeypatch, [_DETAIL_ROW], [{"seller_target_id": "t-9"}])

    tools.execute(_call("get_target_detail", {"target_ids": ["t-9"]}))

    assert tools.candidates_by_id["t-9"]["seller_target_has_other_deep_progress"] is True


def test_a_target_pulled_by_id_alone_has_no_screening_hits(monkeypatch) -> None:
    """按 id 取详情带进来的标的不是筛出来的，命中组数是 0 而不是 1。"""
    tools = _detail_tools(monkeypatch, [_DETAIL_ROW])

    tools.execute(_call("get_target_detail", {"target_ids": ["t-9"]}))

    assert "t-9" in tools.candidates_by_id
    assert tools.candidate_pool().source_for("t-9") == {}


def test_detail_does_not_overwrite_a_screened_candidate(monkeypatch) -> None:
    tools = _detail_tools(monkeypatch, [_DETAIL_ROW])
    screened = {"seller_target_id": "t-9", "seller_target_name": "初筛来的", "facts": {"pe_ratio": 7}}
    tools.candidates_by_id["t-9"] = screened

    tools.execute(_call("get_target_detail", {"target_ids": ["t-9"]}))

    assert tools.candidates_by_id["t-9"] is screened
