"""推荐一轮的四个 AI 节点都必须留下调用记录。

这一轮真正调了四次模型：需求解析、深评、编排 Agent、正文撰写。但只有编排 Agent
写 `ai_trace` —— 于是设置页那一列「最近生产调用」对另外三个节点**永远**是「无记录」。
0820 用户实测就是这么发现的：模型配了、提示词发了、对话也确实跑出了结果，可设置页
上那三行看起来跟从没接线一模一样。

这里锁两件事：**写**（三个调用点都真的把 trace 交出去了）和**不写**（没调用过模型
的分支不许伪造记录，写 trace 失败也不许带走这一轮的产出）。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

import backend.app.services.recommendation_conditions as conditions
import backend.app.services.recommendation_deep_eval as deep_eval
import backend.app.services.recommendation_writer as writer
from backend.app.services.recommendation_flow import AgentAnswerWrite
from backend.app.services.recommendation_trace import (
    RecommendationTraceContext,
    insert_recommendation_node_trace,
)


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_Rows":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Db:
    def __init__(self, node_row: dict[str, Any] | None = None) -> None:
        self.node_row = node_row
        self.inserts: list[dict[str, Any]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Rows:
        sql = str(statement)
        if "insert into ai_trace" in sql:
            self.inserts.append(dict(params or {}))
            return _Rows([])
        if "model_node_config" in sql:
            return _Rows([self.node_row] if self.node_row else [])
        return _Rows([])

    def commit(self) -> None:
        return None


class _LlmResult:
    def __init__(self, parsed: Any) -> None:
        self.parsed_output_json = parsed
        self.raw_output_text = "{}"
        self.prompt_tokens = 100
        self.completion_tokens = 20
        self.total_tokens = 120
        self.latency_ms = 1500


_CONTEXT = RecommendationTraceContext(
    session_id=uuid4(), job_id=uuid4(), correlation_id=uuid4(), turn_id="turn-1"
)

_PARSER_NODE = {
    "node_config_id": uuid4(),
    "provider_config_id": uuid4(),
    "prompt_template_id": uuid4(),
    "provider_name": "test-provider",
    "model_name": "test-model",
    "temperature": 0.1,
    "top_p": 0.9,
    "max_tokens": 2000,
    "timeout_seconds": 120,
    "response_format": "json_object",
    "base_url": "https://example.invalid/v1",
    "api_key_secret_ref": "ref",
    "api_key_encrypted": None,
    "prompt_version": "v0.3.1",
    "system_prompt": "sys",
    "user_prompt_template": "user",
}


def _captured(monkeypatch, module) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        module, "insert_recommendation_node_trace", lambda *_, **kwargs: calls.append(kwargs)
    )
    return calls


# -- 需求解析 -------------------------------------------------------------


def test_the_parser_records_a_production_call(monkeypatch) -> None:
    calls = _captured(monkeypatch, conditions)
    monkeypatch.setattr(conditions, "list_l1_terms", lambda _db: ["制造与工业"])
    monkeypatch.setattr(conditions, "list_l2_terms", lambda _db: [])
    monkeypatch.setattr(conditions, "industry_l1_prompt_list", lambda _db: "")
    monkeypatch.setattr(conditions, "industry_l2_prompt_list", lambda _db: "")
    monkeypatch.setattr(
        conditions,
        "call_openai_compatible_chat",
        lambda **_: _LlmResult({"condition_groups": [], "qualitative_requirements": ["浙江"]}),
    )

    conditions.parse_recommendation_intent(
        _Db(node_row=_PARSER_NODE),
        mode="buyer_to_target",
        user_message="浙江制造业",
        trace_context=_CONTEXT,
    )

    assert len(calls) == 1
    assert calls[0]["node_name"] == conditions.QUERY_PARSER_NODE_NAME
    assert calls[0]["status"] == "succeeded"
    assert calls[0]["node_config"]["prompt_version"] == "v0.3.1"
    # 耗时取模型自己报的那个数：设置页那一列显示的就是这次调用有多慢。
    assert calls[0]["latency_ms"] == 1500


def test_a_degraded_parser_still_records_the_attempt(monkeypatch) -> None:
    """「节点没被调用」和「调了但降级了」在设置页上都是一片空白 —— 排查方向却相反。"""
    calls = _captured(monkeypatch, conditions)
    monkeypatch.setattr(conditions, "list_l1_terms", lambda _db: [])
    monkeypatch.setattr(conditions, "list_l2_terms", lambda _db: [])
    monkeypatch.setattr(conditions, "industry_l1_prompt_list", lambda _db: "")
    monkeypatch.setattr(conditions, "industry_l2_prompt_list", lambda _db: "")

    def boom(**_: Any):
        raise conditions.LlmCallError("LLM request timed out or dropped after 120s")

    monkeypatch.setattr(conditions, "call_openai_compatible_chat", boom)

    result = conditions.parse_recommendation_intent(
        _Db(node_row=_PARSER_NODE),
        mode="buyer_to_target",
        user_message="浙江制造业",
        trace_context=_CONTEXT,
    )

    assert result["parser_status"] == "fallback"
    assert len(calls) == 1
    assert calls[0]["status"] == "failed"
    assert "timed out" in calls[0]["error_message"]


# -- 深评 -----------------------------------------------------------------


def test_deep_eval_records_a_production_call(monkeypatch) -> None:
    calls = _captured(monkeypatch, deep_eval)
    node_row = {**_PARSER_NODE, "node_name": "recommendation_deep_eval_to_target"}
    monkeypatch.setattr(
        deep_eval,
        "build_deep_eval_candidates",
        lambda *_, **__: [{"id": "t-1", "group_hit_count": 1, "search_hit_count": 1}],
    )
    monkeypatch.setattr(deep_eval, "buyer_party_fact_block", lambda *_, **__: "")
    monkeypatch.setattr(
        deep_eval,
        "call_openai_compatible_chat",
        lambda **_: _LlmResult({"ranked": [{"id": "t-1", "rank": 1}], "dropped": []}),
    )

    deep_eval.run_recommendation_deep_eval(
        _Db(node_row=node_row),
        mode="buyer_to_target",
        intent_snapshot={"qualitative_requirements": ["净利率 5% 以上"]},
        candidates_by_id={"t-1": {}},
        trace_context=_CONTEXT,
    )

    assert len(calls) == 1
    assert calls[0]["node_name"] == "recommendation_deep_eval_to_target"
    assert calls[0]["status"] == "succeeded"
    assert calls[0]["metadata"]["ranked_count"] == 1


def test_deep_eval_records_the_call_that_degraded(monkeypatch) -> None:
    calls = _captured(monkeypatch, deep_eval)
    node_row = {**_PARSER_NODE, "node_name": "recommendation_deep_eval_to_target"}
    monkeypatch.setattr(
        deep_eval,
        "build_deep_eval_candidates",
        lambda *_, **__: [{"id": "t-1", "group_hit_count": 1, "search_hit_count": 1}],
    )
    monkeypatch.setattr(deep_eval, "buyer_party_fact_block", lambda *_, **__: "")

    def boom(**_: Any):
        raise deep_eval.LlmCallError("模型没应答")

    monkeypatch.setattr(deep_eval, "call_openai_compatible_chat", boom)

    result = deep_eval.run_recommendation_deep_eval(
        _Db(node_row=node_row),
        mode="buyer_to_target",
        intent_snapshot={},
        candidates_by_id={"t-1": {}},
        trace_context=_CONTEXT,
    )

    assert result["deep_eval_status"] == "unavailable"
    assert [call["status"] for call in calls] == ["failed"]


# -- 正文撰写 -------------------------------------------------------------


_BRIEF = {
    "brief_version": 2,
    "mode": "buyer_to_target",
    "intent_summary": "浙江制造业",
    "deep_eval_status": "ok",
    "recommended": [],
    "runner_ups": [],
    "follow_up_suggestions": [],
    "screening_runs": [],
}


def _run_writer(monkeypatch, *, node_config: dict[str, Any] | None, stream_fn) -> list[dict[str, Any]]:
    calls = _captured(monkeypatch, writer)
    monkeypatch.setattr(writer, "delete_answer_draft", lambda *_, **__: None)
    monkeypatch.setattr(writer, "upsert_answer_draft", lambda *_, **__: None)
    monkeypatch.setattr(writer, "_touch_recommendation_session", lambda *_, **__: None)
    monkeypatch.setattr(
        writer,
        "insert_agent_answer_message",
        lambda *_, **__: AgentAnswerWrite(status="inserted", message_id=uuid4()),
    )
    writer.run_writer_stage(
        _Db(),
        session_id=_CONTEXT.session_id,
        turn_id="turn-1",
        brief=_BRIEF,
        node_config=node_config,
        render_messages=lambda *_: [{"role": "user", "content": "写"}],
        is_aborted=lambda: False,
        stream_fn=stream_fn,
        trace_context=_CONTEXT,
    )
    return calls


def test_the_writer_records_a_production_call(monkeypatch) -> None:
    node_config = {**_PARSER_NODE, "node_name": "recommendation_answer_writer_to_target"}
    calls = _run_writer(
        monkeypatch,
        node_config=node_config,
        stream_fn=lambda **_: iter(["这一轮", "找到 2 家。"]),
    )

    assert len(calls) == 1
    assert calls[0]["node_name"] == "recommendation_answer_writer_to_target"
    assert calls[0]["status"] == "succeeded"
    # 原始输出而不是落库正文：落库那份已经消毒并回填过链接，出问题时看不出模型写了什么。
    assert calls[0]["raw_output_text"] == "这一轮找到 2 家。"
    assert calls[0]["metadata"]["generation_mode"] == "llm"


def test_a_writer_that_fell_back_is_recorded_as_a_failed_call(monkeypatch) -> None:
    node_config = {**_PARSER_NODE, "node_name": "recommendation_answer_writer_to_target"}

    def boom(**_: Any):
        raise RuntimeError("上游断流")
        yield  # pragma: no cover - 只是让它成为生成器

    calls = _run_writer(monkeypatch, node_config=node_config, stream_fn=boom)

    assert [call["status"] for call in calls] == ["failed"]
    assert calls[0]["metadata"]["generation_mode"] == "fallback"


def test_an_unconfigured_writer_records_nothing(monkeypatch) -> None:
    """规则兜底那条路一次模型都没调过，凭空记一行会让设置页显示成节点在跑。"""
    calls = _run_writer(monkeypatch, node_config=None, stream_fn=lambda **_: iter([]))

    assert calls == []


# -- 写 trace 本身的边界 ---------------------------------------------------


def test_a_failed_trace_write_never_takes_the_turn_down() -> None:
    """观测不是产出。一次写 trace 失败换掉一整轮已经付过钱的推荐，是错误的交换。"""

    class _Exploding(_Db):
        def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Rows:
            raise RuntimeError("ai_trace 写不进去")

    insert_recommendation_node_trace(
        _Exploding(),
        context=_CONTEXT,
        node_name="recommendation_query_parser",
        node_config=_PARSER_NODE,
        status="succeeded",
        input_json={},
        prompt_messages=[],
        latency_ms=10,
    )


@pytest.mark.parametrize(
    "context, node_name",
    [
        (None, "recommendation_query_parser"),
        (_CONTEXT, ""),
    ],
)
def test_nothing_is_written_without_an_owner_or_a_node(context, node_name) -> None:
    """没上下文、或连节点名都解析不出来时，宁可不记 —— 空 node_name 会在设置页上
    凭空长出一个不存在的节点。"""
    db = _Db()
    insert_recommendation_node_trace(
        db,
        context=context,
        node_name=node_name,
        node_config=_PARSER_NODE,
        status="succeeded",
        input_json={},
        prompt_messages=[],
        latency_ms=10,
    )
    assert db.inserts == []


def test_the_trace_row_carries_the_turn_and_the_node_identity() -> None:
    """设置页那一列靠 node_name 关联；drill-down 靠 turn_id 找回这一轮。"""
    db = _Db()
    insert_recommendation_node_trace(
        db,
        context=_CONTEXT,
        node_name="recommendation_query_parser",
        node_config=_PARSER_NODE,
        status="succeeded",
        input_json={"mode": "buyer_to_target"},
        prompt_messages=[{"role": "user", "content": "浙江"}],
        latency_ms=1500,
        metadata={"parser_status": "ok"},
    )

    assert len(db.inserts) == 1
    row = db.inserts[0]
    assert row["node_name"] == "recommendation_query_parser"
    assert row["entity_id"] == _CONTEXT.session_id
    assert row["job_id"] == _CONTEXT.job_id
    assert row["node_config_id"] == _PARSER_NODE["node_config_id"]
    assert row["prompt_version"] == "v0.3.1"
    assert row["metadata_json"]["turn_id"] == "turn-1"
    assert row["metadata_json"]["parser_status"] == "ok"
    # 「最近生产调用」那一列会剔掉节点业务测试的 trace，靠的就是 source 这个键。
    # 真实业务调用不能带它，否则整列又变回空的。
    assert "source" not in row["metadata_json"]
