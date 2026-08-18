"""对话链路深评（阶段三）的契约 —— 纯单测，**不打 LLM**。

每个用例都用 fixture 模拟深评节点的返回，验证**代码这一侧**的收敛：id 校验、
逐条判定的闭集、漏判与剔光的兜底、两种失败各自的名字。模型排得好不好是提示词的事，
这里钉住的是「无论模型给什么，代码都不会伪造一个排序，也不会把候选静默弄丢」。

用例编号对应《推荐升级阶段三施工单_深评节点0818.md》第六节。

旧 `/candidates` 链路的深评在 `tests/test_recommendation_deep_eval.py`，那一份一个字
都没动 —— 它绿着才说明新链路确实是并排新建的，不是把旧函数改了。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
from typing import Any

import pytest

from backend.app.ai.llm_client import LlmCallError
from backend.app.services import recommendation_deep_eval as module
from backend.app.services.recommendation_deep_eval import (
    FALLBACK_KEEP_COUNT,
    NO_PROFILE_TEXT,
    VERDICT_UNKNOWN,
    build_anchor_context,
    build_deep_eval_candidates,
    describe_deep_eval_result,
    normalize_deep_eval_result,
    run_recommendation_deep_eval,
)

T1 = "11111111-1111-1111-1111-111111111111"
T2 = "22222222-2222-2222-2222-222222222222"
T3 = "33333333-3333-3333-3333-333333333333"
T4 = "44444444-4444-4444-4444-444444444444"
T5 = "55555555-5555-5555-5555-555555555555"

REQ_A = "具备地区产业优势"
REQ_B = "有成熟的海外仓网络"

ALL_FIVE = [T1, T2, T3, T4, T5]


def normalize(raw: Any, *, ids: list[str] | None = None, requirements: list[str] | None = None) -> dict:
    return normalize_deep_eval_result(
        raw,
        candidate_ids=ids if ids is not None else [T1, T2, T3],
        qualitative_requirements=requirements if requirements is not None else [REQ_A, REQ_B],
    )


def ranked_ids(result: dict) -> list[str]:
    return [item["id"] for item in result["ranked"]]


# =========================================================================
# 用例 1-6：归一化
# =========================================================================


def test_case1_ranked_comes_back_in_rank_order() -> None:
    """模型给的数组顺序与它自己给的 rank 冲突时，以 rank 为准，再重新连续编号。"""
    result = normalize(
        {
            "ranked": [
                {"id": T3, "rank": 3, "qualitative_verdicts": {REQ_A: "不符合"}},
                {"id": T1, "rank": 1, "qualitative_verdicts": {REQ_A: "符合", REQ_B: "无法判断"},
                 "fit_points": ["链主地位", "配套半径 30 公里"], "risks": "客户集中度高", "info_gaps": "海外仓未提及"},
                {"id": T2, "rank": 2, "qualitative_verdicts": {REQ_A: "无法判断"}},
            ]
        }
    )

    assert result["deep_eval_status"] == "ok"
    assert ranked_ids(result) == [T1, T2, T3]
    assert [item["rank"] for item in result["ranked"]] == [1, 2, 3]
    assert result["ranked"][0]["qualitative_verdicts"] == {REQ_A: "符合", REQ_B: "无法判断"}
    assert result["ranked"][0]["fit_points"] == ["链主地位", "配套半径 30 公里"]
    assert result["ranked"][0]["risks"] == "客户集中度高"
    assert result["dropped"] == []
    assert result["uncovered"] == []
    assert result["fallback_reason"] is None
    assert result["notes"] == []


def test_case2_invented_ids_are_dropped_and_noted() -> None:
    result = normalize(
        {
            "ranked": [
                {"id": T1, "rank": 1},
                {"id": "这家我编的", "rank": 2},
                {"id": T2, "rank": 3},
            ]
        }
    )

    assert ranked_ids(result)[:2] == [T1, T2]
    assert any("不在本轮候选集内" in note for note in result["notes"])


def test_case3_candidates_the_model_never_mentioned_land_at_the_tail() -> None:
    """漏判不等于淘汰：没被提到的按初筛序缀在末尾，并单独列出来。"""
    result = normalize(
        {"ranked": [{"id": T3, "rank": 1}, {"id": T1, "rank": 2}, {"id": T5, "rank": 3}]},
        ids=ALL_FIVE,
    )

    assert ranked_ids(result) == [T3, T1, T5, T2, T4]
    assert [item["rank"] for item in result["ranked"]] == [1, 2, 3, 4, 5]
    assert result["uncovered"] == [T2, T4]
    assert result["ranked"][3]["uncovered"] is True
    assert result["ranked"][3]["qualitative_verdicts"] == {}
    assert any("未提及" in note for note in result["notes"])


def test_case4_dropping_everything_falls_back_to_the_first_three() -> None:
    """「一家都没有」比「有几家但都不理想」糟糕得多。"""
    result = normalize(
        {"dropped": [{"id": candidate_id, "reason": "都不合适"} for candidate_id in reversed(ALL_FIVE)]},
        ids=ALL_FIVE,
    )

    assert result["fallback_reason"] == "all_dropped"
    assert ranked_ids(result) == ALL_FIVE[:FALLBACK_KEEP_COUNT]
    assert [item["rank"] for item in result["ranked"]] == [1, 2, 3]
    # 模型的剔除理由不能丢：客户经理要的就是这句判断材料。
    assert result["ranked"][0]["risks"] == "都不合适"
    assert all(item["fallback"] is True for item in result["ranked"])
    assert [item["id"] for item in result["dropped"]] == [T5, T4]
    assert any("保底" in note for note in result["notes"])


def test_case4b_partial_drop_does_not_trigger_the_fallback() -> None:
    result = normalize({"ranked": [{"id": T1, "rank": 1}], "dropped": [{"id": T2}, {"id": T3}]})

    assert result["fallback_reason"] is None
    assert ranked_ids(result) == [T1]
    assert [item["id"] for item in result["dropped"]] == [T2, T3]


def test_case4c_uncovered_candidates_make_the_fallback_unnecessary() -> None:
    """还有没判过的候选可以填进来时，不要把模型明确剔掉的家硬拉回来。"""
    result = normalize({"dropped": [{"id": T1}, {"id": T2}]})

    assert result["fallback_reason"] is None
    assert ranked_ids(result) == [T3]
    assert result["uncovered"] == [T3]


def test_case5_invented_verdict_keys_are_dropped_but_never_silently() -> None:
    result = normalize(
        {"ranked": [{"id": T1, "rank": 1, "qualitative_verdicts": {REQ_A: "符合", "我自己想的一条要求": "符合"}}]}
    )

    assert result["ranked"][0]["qualitative_verdicts"] == {REQ_A: "符合"}
    assert any("不在定性诉求里的键" in note for note in result["notes"])


def test_case6_verdicts_outside_the_closed_set_become_unknown() -> None:
    result = normalize({"ranked": [{"id": T1, "rank": 1, "qualitative_verdicts": {REQ_A: "很符合", REQ_B: ""}}]})

    assert result["ranked"][0]["qualitative_verdicts"] == {REQ_A: VERDICT_UNKNOWN, REQ_B: VERDICT_UNKNOWN}
    assert sum("不在闭集内" in note for note in result["notes"]) == 2


# =========================================================================
# 用例 7：结构失配要有名字
# =========================================================================


def test_case7_unrecognisable_payload_is_schema_mismatch_not_an_exception() -> None:
    """v0.1.0 那次翻车的直接复刻：模型返回了东西，但一个认识的键都没有。

    不抛异常（那会中断本轮），也不伪造排序（那会让错误看起来像结论）。
    """
    result = normalize({"foo": 1})

    assert result["deep_eval_status"] == "schema_mismatch"
    assert result["ranked"] == []
    assert result["dropped"] == []
    assert result["uncovered"] == []
    assert result["fallback_reason"] is None
    assert any("提示词版本" in note for note in result["notes"])
    assert "提示词版本" in describe_deep_eval_result(result)


@pytest.mark.parametrize("raw", [None, "一段散文", [], {"results": [{"candidate_id": T1, "grade": "A"}]}])
def test_case7b_old_shape_output_is_schema_mismatch_too(raw: Any) -> None:
    """旧形态提示词（分档 + results）落到新代码上必须响，这正是不走 understudy 回落的理由。"""
    assert normalize(raw)["deep_eval_status"] == "schema_mismatch"


def test_schema_mismatch_never_triggers_the_all_dropped_fallback() -> None:
    """失配时保底不许开火 —— 那会把一次识别失败包装成「模型挑了前三家」。"""
    result = normalize({"foo": 1}, ids=ALL_FIVE)

    assert result["ranked"] == []
    assert result["fallback_reason"] is None


# =========================================================================
# 用例 8-11：跑一次深评
# =========================================================================


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def one_or_none(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _RecordingDb:
    """记下每一次查询。节点取配置与画像加载都要能被断言。"""

    def __init__(
        self,
        *,
        node_row: dict[str, Any] | None = None,
        profile_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.node_row = node_row
        self.profile_rows = profile_rows or []
        self.queries: list[dict[str, Any]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Rows:
        sql = str(statement)
        self.queries.append({"sql": sql, "params": dict(params or {})})
        if "model_node_config" in sql:
            return _Rows([self.node_row] if self.node_row else [])
        if "entity_profile_section" in sql:
            return _Rows(self.profile_rows)
        return _Rows([])

    def node_names_queried(self) -> list[str]:
        return [query["params"]["node_name"] for query in self.queries if "node_name" in query["params"]]


_NODE_ROW: dict[str, Any] = {
    "node_name": "recommendation_deep_eval_to_target",
    "model_name": "test-model",
    "temperature": 0.2,
    "top_p": 0.9,
    "max_tokens": 4000,
    "timeout_seconds": 300,
    "response_format": "json_object",
    "base_url": "https://example.invalid/v1",
    "api_key_secret_ref": "ref",
    "api_key_encrypted": None,
    "prompt_version": "v0.2.0",
    "system_prompt": "你是分析师。方向：{{ mode }}",
    "user_prompt_template": "{{ anchor_context }}\n诉求：{{ qualitative_requirements_json }}\n候选：{{ candidates_json }}",
}

_SNAPSHOT: dict[str, Any] = {
    "condition_groups": [{"label": "方案1", "conditions": {"industries_json": ["制造与工业"]}, "strength": {}}],
    "qualitative_requirements": [REQ_A, REQ_B],
    "exclusions": {"industries": ["房地产与建筑"], "risk_flags": []},
    "unstructured_notes": ["预算大概三个亿"],
    "raw_text": "找华东的制造业标的，最好在当地有产业优势，有成熟的海外仓",
    "parser_status": "ok",
    "parser_notes": [],
}

_CANDIDATES: dict[str, dict[str, Any]] = {
    T1: {"seller_target_name": "杭州XX精密制造", "facts": {"net_profit_text": "2800万", "region": "浙江杭州"}},
    T2: {"seller_target_name": "苏州YY装备", "facts": {"net_profit_text": "1900万"}},
}


class _LlmResult:
    def __init__(self, parsed: Any, total_tokens: int | None = 1234) -> None:
        self.parsed_output_json = parsed
        self.total_tokens = total_tokens


def _fake_chat(captured: dict[str, Any], parsed: Any):
    def chat(**kwargs: Any) -> _LlmResult:
        captured.update(kwargs)
        return _LlmResult(parsed)

    return chat


def _run(monkeypatch, *, parsed: Any, snapshot: dict[str, Any] | None = None,
         candidates: dict[str, dict[str, Any]] | None = None, hit_counts: dict[str, int] | None = None,
         captured: dict[str, Any] | None = None, db: _RecordingDb | None = None) -> dict[str, Any]:
    monkeypatch.setattr(module, "call_openai_compatible_chat", _fake_chat(captured if captured is not None else {}, parsed))
    return run_recommendation_deep_eval(
        db or _RecordingDb(node_row=_NODE_ROW),
        mode="buyer_to_target",
        intent_snapshot=snapshot if snapshot is not None else _SNAPSHOT,
        candidates_by_id=candidates if candidates is not None else _CANDIDATES,
        hit_counts=hit_counts,
    )


def test_run_passes_all_four_variables_and_reports_the_prompt_version(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    result = _run(monkeypatch, parsed={"ranked": [{"id": T1, "rank": 1}, {"id": T2, "rank": 2}]}, captured=captured)

    assert result["deep_eval_status"] == "ok"
    assert result["prompt_version"] == "v0.2.0"
    assert result["model_name"] == "test-model"
    assert result["candidate_count"] == 2
    assert result["total_tokens"] == 1234

    rendered = "\n".join(message["content"] for message in captured["messages"])
    # 变量渲染成了值，不是字面量 —— 这是上一轮翻车的那一步。
    assert "{{" not in rendered
    assert REQ_A in rendered and REQ_B in rendered
    assert "杭州XX精密制造" in rendered
    assert "buyer_to_target" in rendered


def test_case8_a_failing_llm_call_degrades_instead_of_raising(monkeypatch) -> None:
    """深评调不通不中断本轮 —— 这一轮退化成「没有深评的一轮」，agent 名单照出。"""

    def boom(**_kwargs: Any):
        raise LlmCallError("上游 502")

    monkeypatch.setattr(module, "call_openai_compatible_chat", boom)

    result = run_recommendation_deep_eval(
        _RecordingDb(node_row=_NODE_ROW),
        mode="buyer_to_target",
        intent_snapshot=_SNAPSHOT,
        candidates_by_id=_CANDIDATES,
    )

    assert result["deep_eval_status"] == "unavailable"
    assert result["ranked"] == []
    assert any("502" in note for note in result["notes"])
    assert "未能返回结果" in describe_deep_eval_result(result)


def test_case9_no_qualitative_requirements_still_produces_a_ranking(monkeypatch) -> None:
    """用户只提了硬条件：深评照跑，判定为空对象，排序仍然产出。"""
    snapshot = {**_SNAPSHOT, "qualitative_requirements": []}
    captured: dict[str, Any] = {}
    result = _run(
        monkeypatch,
        parsed={"ranked": [{"id": T2, "rank": 1}, {"id": T1, "rank": 2}]},
        snapshot=snapshot,
        captured=captured,
    )

    assert result["deep_eval_status"] == "ok"
    assert ranked_ids(result) == [T2, T1]
    assert all(item["qualitative_verdicts"] == {} for item in result["ranked"])
    assert result["qualitative_requirements"] == []
    # 诉求变量渲染成空数组，而不是留个字面量或者 "null" 塞给模型。
    injected = next(
        message["content"].split("诉求：", 1)[1].split("\n", 1)[0]
        for message in captured["messages"]
        if "诉求：" in message["content"]
    )
    assert injected == "[]"


def test_case10_hit_counts_reach_the_deep_eval_input(monkeypatch) -> None:
    """本阶段唯一的新数据流。漏了不会报错，只会让深评永远看不到「强候选」信号。"""
    captured: dict[str, Any] = {}
    result = _run(
        monkeypatch,
        parsed={"ranked": [{"id": T1, "rank": 1}, {"id": T2, "rank": 2}]},
        hit_counts={T1: 2, T2: 1},
        captured=captured,
    )

    payload = json.loads(next(
        message["content"].split("候选：", 1)[1]
        for message in captured["messages"]
        if "候选：" in message["content"]
    ))
    assert {item["id"]: item["hit_count"] for item in payload} == {T1: 2, T2: 1}
    assert result["candidate_hit_counts"] == {T1: 2, T2: 1}


def test_case11_an_unconfigured_node_never_falls_back_to_the_understudy(monkeypatch) -> None:
    """`_get_deep_eval_node_config` 的 understudy 回落就在旁边，顺手复用是最自然的写法，也是错的。

    共用节点上装的是旧形态提示词（分档、分片、旧 schema），回落过去模型返回的东西
    对不上新代码 —— 而且不会报错。所以取不到配置就降级，不要悄悄换一个节点跑。
    """
    db = _RecordingDb(node_row=None)
    monkeypatch.setattr(module, "call_openai_compatible_chat", _fake_chat({}, {"ranked": []}))

    result = run_recommendation_deep_eval(
        db,
        mode="buyer_to_target",
        intent_snapshot=_SNAPSHOT,
        candidates_by_id=_CANDIDATES,
    )

    assert result["deep_eval_status"] == "unavailable"
    assert db.node_names_queried() == ["recommendation_deep_eval_to_target"]
    assert "recommendation_deep_eval" not in db.node_names_queried()


def test_a_node_row_without_a_prompt_is_treated_as_unconfigured(monkeypatch) -> None:
    db = _RecordingDb(node_row={**_NODE_ROW, "user_prompt_template": None})
    monkeypatch.setattr(module, "call_openai_compatible_chat", _fake_chat({}, {"ranked": []}))

    result = run_recommendation_deep_eval(
        db, mode="buyer_to_target", intent_snapshot=_SNAPSHOT, candidates_by_id=_CANDIDATES
    )

    assert result["deep_eval_status"] == "unavailable"


def test_an_unknown_mode_degrades_instead_of_guessing_an_entity_type(monkeypatch) -> None:
    monkeypatch.setattr(module, "call_openai_compatible_chat", _fake_chat({}, {"ranked": []}))

    result = run_recommendation_deep_eval(
        _RecordingDb(node_row=_NODE_ROW),
        mode="sideways",
        intent_snapshot=_SNAPSHOT,
        candidates_by_id=_CANDIDATES,
    )

    assert result["deep_eval_status"] == "unavailable"


def test_no_candidates_degrades_rather_than_calling_the_model(monkeypatch) -> None:
    called: list[int] = []

    def chat(**_kwargs: Any):
        called.append(1)
        raise AssertionError("没有候选时不该调用模型")

    monkeypatch.setattr(module, "call_openai_compatible_chat", chat)

    result = run_recommendation_deep_eval(
        _RecordingDb(node_row=_NODE_ROW),
        mode="buyer_to_target",
        intent_snapshot=_SNAPSHOT,
        candidates_by_id={},
    )

    assert result["deep_eval_status"] == "unavailable"
    assert called == []


# =========================================================================
# 候选画像
# =========================================================================


def test_profiles_are_loaded_for_seller_targets_in_the_forward_direction() -> None:
    """传错实体类型不会报错，只会返回空画像 —— 然后深评在没有画像的情况下照常排序。"""
    db = _RecordingDb(profile_rows=[
        {"entity_id": T1, "section_code": "business_product", "info_status": "filled",
         "content_text": "细分领域前三，链主地位", "source_type": None, "source_url": None,
         "as_of_date": None, "updated_at": "2026-08-01"},
    ])

    items = build_deep_eval_candidates(db, mode="buyer_to_target", candidates_by_id=_CANDIDATES)

    profile_query = next(query for query in db.queries if "entity_profile_section" in query["sql"])
    assert profile_query["params"]["entity_type"] == "seller_target"
    assert "链主地位" in items[0]["profile"]


def test_candidates_without_a_profile_say_so_out_loud() -> None:
    """空字符串会让模型以为这家真的没内容，然后把「没查到」读成「不符合」。"""
    items = build_deep_eval_candidates(_RecordingDb(), mode="buyer_to_target", candidates_by_id=_CANDIDATES)

    assert [item["profile"] for item in items] == [NO_PROFILE_TEXT, NO_PROFILE_TEXT]
    assert [item["id"] for item in items] == [T1, T2]
    assert [item["hit_count"] for item in items] == [0, 0]


def test_placeholder_fact_fields_do_not_reach_the_model() -> None:
    """PE 口径、财务期间标签、估值/报价时间对「合不合适」没有贡献，纯占位。"""
    candidates = {
        T1: {
            "seller_target_name": "标的甲",
            "facts": {
                "net_profit_text": "2800万", "pe_ratio": 8.5,
                "pe_source_type": "trailing", "financial_period_label": "2025年报",
                "valuation_date": "2026-01-01", "asking_price_date": "2026-02-01",
            },
        }
    }

    facts = build_deep_eval_candidates(_RecordingDb(), mode="buyer_to_target", candidates_by_id=candidates)[0]["facts"]

    assert facts == {"net_profit_text": "2800万", "pe_ratio": 8.5}


# =========================================================================
# anchor_context
# =========================================================================


def test_anchor_context_tells_the_model_the_hard_conditions_already_passed() -> None:
    context = build_anchor_context(_SNAPSHOT)

    assert "找华东的制造业标的" in context
    assert "不要重复判断" in context
    assert "房地产与建筑" in context
    assert "预算大概三个亿" in context
    # 定性诉求有自己的变量，不在这里重复一遍。
    assert REQ_A not in context


def test_anchor_context_flags_a_degraded_snapshot() -> None:
    """快照本身就是降级来的：照跑，但模型该知道自己拿到的不是完整基线。"""
    context = build_anchor_context(
        {"raw_text": "杭州的标的", "qualitative_requirements": ["杭州的标的"], "parser_status": "fallback"}
    )

    assert "降级结果" in context
    assert "parser_status=fallback" in context


def test_anchor_context_appends_the_buyer_party_block_when_there_is_one() -> None:
    context = build_anchor_context(_SNAPSHOT, party_facts="【买方自身情况（供协同性判断）】\n所属行业：机器人")

    assert context.endswith("所属行业：机器人")


# =========================================================================
# 本阶段的边界：只产出，不改最终答案
# =========================================================================


def test_the_answer_brief_cannot_see_the_deep_eval() -> None:
    """接进素材包与最终名单是阶段四。在它稳定之前，改名单就等于没有对照组。"""
    import inspect

    from backend.app.jobs.handlers.recommendation import _build_answer_brief

    assert "deep_eval" not in inspect.signature(_build_answer_brief).parameters


# =========================================================================
# Prompt v0.2.0：变量必须真的被替换成值
# =========================================================================


def _prompt_module():
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "publish_deep_eval_v020_prompt.py"
    spec = importlib.util.spec_from_file_location("publish_deep_eval_v020_prompt", path)
    loaded = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def test_prompt_v020_declares_exactly_the_variables_the_node_injects() -> None:
    from backend.app.ai.prompting import extract_template_variables
    from backend.app.registry.nodes import node_by_name

    prompt = _prompt_module()
    spec = node_by_name(prompt.NODE_NAME)
    assert spec is not None

    used = set(extract_template_variables(prompt.SYSTEM_PROMPT, prompt.USER_PROMPT_TEMPLATE))
    assert used == set(spec.prompt_variables)
    assert "qualitative_requirements_json" in used


def test_prompt_v020_renders_every_variable_into_a_value(monkeypatch) -> None:
    """单花括号不会报错，只会让模型收到字面量 —— 上一轮就是这么错了一整轮。"""
    from backend.app.ai.prompting import render_template
    from backend.app.api.routes.model_config import _validate_prompt_variables

    prompt = _prompt_module()
    # 存提示词那一关先过：单花括号包住已声明变量会被拒。
    _validate_prompt_variables(prompt.NODE_NAME, prompt.SYSTEM_PROMPT, prompt.USER_PROMPT_TEMPLATE)

    values = {
        "mode": "buyer_to_target",
        "anchor_context": "【用户原话】找华东的制造业标的",
        "candidates_json": json.dumps([{"id": T1, "hit_count": 2}], ensure_ascii=False),
        "qualitative_requirements_json": json.dumps([REQ_A], ensure_ascii=False),
    }
    rendered = render_template(prompt.SYSTEM_PROMPT, values) + "\n" + render_template(
        prompt.USER_PROMPT_TEMPLATE, values
    )

    for name, value in values.items():
        assert "{{ " + name + " }}" not in rendered, f"{name} 没被替换"
        assert value in rendered


def test_prompt_v020_writes_the_closed_set_and_the_no_grading_rule_into_the_body() -> None:
    prompt = _prompt_module()
    body = prompt.SYSTEM_PROMPT + prompt.USER_PROMPT_TEMPLATE

    assert "不评级" in body and "不打分" in body
    for verdict in ("符合", "不符合", VERDICT_UNKNOWN):
        assert verdict in body
    assert "原文" in body                      # 判定的键用原文
    assert "已经在数据库层筛过" in body          # 硬条件不要重判
    assert "明显不符合" in body                 # dropped 的门槛
    # few_shot_examples_json 是死存储，示例必须写进正文
    assert body.count('"ranked"') >= 2
