"""Writer-in-the-worker: the answer survives whatever the browser does.

The bug these cover: the Writer used to run inside the `/answer-stream`
request and persist only after the stream loop finished, so closing the tab
threw away a generation the customer had already paid for, left the session on
a yellow dot forever, and made reopening it pay a second time.

The rules being pinned down here are the ones that make the move safe:
a half-finished draft is never promoted to an answer, abort beats everything,
and a second producer never appends a duplicate answer.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest

from backend.app.services import recommendation_writer as writer
from backend.app.services.recommendation_flow import AgentAnswerWrite
from backend.app.shutdown import WorkerShutdown

SESSION_ID = UUID("00000000-0000-0000-0000-0000000000a1")
TURN_ID = "turn-1"

_BRIEF: dict[str, Any] = {
    "mode": "buyer_to_target",
    "brief_version": 2,
    "intent_summary": "华东 · 精密制造",
    "selection_source": "deep_eval",
    "deep_eval_status": "ok",
    "candidate_pool_count": 30,
    "follow_up_suggestions": ["细看杭州XX精密制造"],
    "recommended": [
        {
            "id": "t-1",
            "name": "杭州XX精密制造",
            "facts": {"net_profit_text": "2800万", "region": "浙江杭州"},
            "reason_points": ["产线互补"],
        }
    ],
    "runner_ups": [],
}

_NODE_CONFIG = {
    "base_url": "https://example.invalid",
    "api_key_secret_ref": "x",
    "model_name": "writer",
    "temperature": 0.4,
    "top_p": 1,
    "max_tokens": 1000,
    "timeout_seconds": 30,
}


class _FakeDb:
    """Just enough session for a module that only commits and delegates."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _Harness:
    """In-memory stand-ins for the draft row and the terminal answer write."""

    def __init__(self) -> None:
        self.draft: str | None = None
        self.draft_history: list[str] = []
        self.answers: list[dict[str, Any]] = []
        self.touched = 0
        self.write_status = "inserted"

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def upsert(_db, *, session_id, turn_id, markdown):
            assert (session_id, turn_id) == (SESSION_ID, TURN_ID)
            self.draft = markdown
            self.draft_history.append(markdown)

        def delete(_db, *, session_id, turn_id):
            assert (session_id, turn_id) == (SESSION_ID, TURN_ID)
            self.draft = None

        def insert_answer(_db, **kwargs):
            if self.write_status == "aborted":
                return AgentAnswerWrite(status="aborted", message_id=None)
            if self.write_status == "already_exists":
                return AgentAnswerWrite(status="already_exists", message_id=uuid4())
            self.answers.append(kwargs)
            return AgentAnswerWrite(status="inserted", message_id=uuid4())

        monkeypatch.setattr(writer, "upsert_answer_draft", upsert)
        monkeypatch.setattr(writer, "delete_answer_draft", delete)
        monkeypatch.setattr(writer, "insert_agent_answer_message", insert_answer)
        monkeypatch.setattr(
            writer,
            "_touch_recommendation_session",
            lambda *_args, **_kwargs: setattr(self, "touched", self.touched + 1),
        )


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    deltas: list[str] | None = None,
    fail_after: int | None = None,
    node_config: dict[str, Any] | None = _NODE_CONFIG,
    abort_after: int | None = None,
    write_status: str = "inserted",
    checkpoint=None,
    budget_seconds: float | None = None,
    harness: _Harness | None = None,
) -> tuple[writer.WriterOutcome, _Harness]:
    state = harness or _Harness()
    state.write_status = write_status
    state.install(monkeypatch)

    def stream(**_kwargs):
        for index, delta in enumerate(deltas or []):
            if fail_after is not None and index == fail_after:
                raise RuntimeError("writer upstream died")
            yield delta

    abort_calls = {"n": 0}

    def is_aborted() -> bool:
        abort_calls["n"] += 1
        return abort_after is not None and abort_calls["n"] > abort_after

    outcome = writer.run_writer_stage(
        _FakeDb(),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        brief=_BRIEF,
        node_config=node_config,
        render_messages=lambda *_args, **_kwargs: [],
        is_aborted=is_aborted,
        checkpoint=checkpoint,
        stream_fn=stream,
        budget_seconds=budget_seconds,
        # 每个 delta 都 flush，这样「第几个 delta 之后中止」在测试里是确定的。
        flush_delta_count=1,
    )
    return outcome, state


# -- 行为①：断连不落半截，也不重新生成 -----------------------------------


def test_writer_persists_the_answer_with_no_reader_attached(monkeypatch) -> None:
    """没有任何人在读 SSE，正文照样完整落库 —— 这是这一批的核心判据。"""
    outcome, state = _run(monkeypatch, deltas=["推荐杭州XX", "精密制造。"])

    assert outcome.status == "answered"
    assert outcome.generation_mode == "llm"
    assert "杭州XX精密制造" in outcome.markdown
    assert len(state.answers) == 1
    assert state.answers[0]["markdown"] == outcome.markdown


def test_finished_answer_carries_links_and_leaves_no_draft_behind(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=["重点看杭州XX精密制造。"])

    assert "](/targets/t-1)" in outcome.markdown
    assert state.draft is None
    assert state.touched == 1


def test_prose_reaches_the_draft_while_it_is_still_being_written(monkeypatch) -> None:
    """草稿是订阅者唯一的数据来源；不落草稿等于没有流式。"""
    _, state = _run(monkeypatch, deltas=["第一段。", "第二段。", "第三段。"])

    assert state.draft_history[:3] == ["第一段。", "第一段。第二段。", "第一段。第二段。第三段。"]


def test_a_previous_runs_draft_is_cleared_before_writing_again(monkeypatch) -> None:
    """job 被部署打断后会重排；接着上一次的残稿写会让读者读到断裂的文本。"""
    state = _Harness()
    state.draft = "上一次跑到一半的残稿"

    _run(monkeypatch, deltas=["全新的一段。"], harness=state)

    assert state.draft_history[0] == "全新的一段。"


# -- 上游异常：兜底可以，半截不行 ------------------------------------------


def test_stream_failure_falls_back_to_the_rule_built_answer(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=["半截", "正文"], fail_after=1)

    assert outcome.status == "answered"
    assert outcome.generation_mode == "fallback"
    assert "30 家去重候选" in outcome.markdown
    assert outcome.error_message == "writer upstream died"
    # 关键不变式：落库的是完整兜底文案，不是那半截 "半截"。
    assert state.answers[0]["markdown"] == outcome.markdown
    assert "半截正文" not in state.answers[0]["markdown"]


def test_unconfigured_writer_still_produces_something_sendable(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=[], node_config=None)

    assert outcome.generation_mode == "fallback"
    assert "30 家去重候选" in outcome.markdown
    assert state.answers[0]["model_name"] is None


def test_the_node_budget_is_handed_to_the_stream_not_re_timed_here(monkeypatch) -> None:
    """只能有一处算 deadline。

    第一批交付时 Writer 自己也掐一遍表，因为那会儿 `timeout_seconds` 只是 socket
    超时、流式每来一个 token 就重置。第三批把 deadline 做进
    `stream_openai_compatible_chat` 之后，Writer 再算一次就是第二个算法 ——
    两处各判一次「超时没有」，迟早对不上。所以这里只验预算被原样交下去。
    """
    seen: list[int] = []
    state = _Harness()
    state.install(monkeypatch)

    def stream(**kwargs):
        seen.append(kwargs["timeout_seconds"])
        yield "正文。"

    writer.run_writer_stage(
        _FakeDb(),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        brief=_BRIEF,
        node_config={**_NODE_CONFIG, "timeout_seconds": 45},
        render_messages=lambda *_args, **_kwargs: [],
        is_aborted=lambda: False,
        stream_fn=stream,
    )

    assert seen == [45]


def test_a_stream_that_hits_its_budget_still_ends_in_a_sendable_answer(monkeypatch) -> None:
    """超时由流抛 LlmCallError，Writer 照常走规则兜底 —— 用户仍拿得到可发的文本。"""
    from backend.app.ai.llm_client import LlmCallError

    def blow_up(**_kwargs):
        raise LlmCallError("LLM stream exceeded the node budget of 45s")
        yield  # pragma: no cover - 让它是个生成器

    state = _Harness()
    state.install(monkeypatch)

    outcome = writer.run_writer_stage(
        _FakeDb(),
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        brief=_BRIEF,
        node_config=_NODE_CONFIG,
        render_messages=lambda *_args, **_kwargs: [],
        is_aborted=lambda: False,
        stream_fn=blow_up,
    )

    assert outcome.generation_mode == "fallback"
    assert "budget" in (outcome.error_message or "")
    assert "30 家去重候选" in outcome.markdown


def test_empty_model_output_falls_back_instead_of_writing_nothing(monkeypatch) -> None:
    outcome, _ = _run(monkeypatch, deltas=["   "])

    assert outcome.generation_mode == "fallback"
    assert outcome.markdown.strip()


# -- 行为③：中止优先 -------------------------------------------------------


def test_abort_mid_stream_writes_no_answer_and_leaves_no_draft(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=["第一段。", "第二段。", "第三段。"], abort_after=2)

    assert outcome.status == "aborted"
    assert state.answers == []
    assert state.draft is None


def test_abort_landing_inside_the_terminal_lock_still_wins(monkeypatch) -> None:
    """另一个页签在最后一刻按了停止：锁内复查为准，正文不落库。"""
    outcome, state = _run(monkeypatch, deltas=["完整正文。"], write_status="aborted")

    assert outcome.status == "aborted"
    assert state.answers == []
    assert state.draft is None


def test_abort_during_a_failing_stream_beats_the_fallback(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=["半截"], fail_after=0, abort_after=1)

    assert outcome.status == "aborted"
    assert state.answers == []


# -- 双页签 / 重排：绝不写第二份正文 ---------------------------------------


def test_an_answer_another_producer_already_wrote_is_not_duplicated(monkeypatch) -> None:
    outcome, state = _run(monkeypatch, deltas=["正文。"], write_status="already_exists")

    assert outcome.status == "answered"
    assert outcome.already_existed is True
    assert state.answers == []
    # 已经有正文的一轮不该再被 touch 成「刚刚更新」。
    assert state.touched == 0


# -- 优雅退出：释放不是失败 -------------------------------------------------


def test_shutdown_during_the_stream_writes_nothing_at_all(monkeypatch) -> None:
    """worker 要停时兜底正文一旦落库就再也换不回真正的正文了。"""

    def checkpoint() -> None:
        raise WorkerShutdown("SIGTERM")

    state = _Harness()
    with pytest.raises(WorkerShutdown):
        _run(monkeypatch, deltas=["一", "二"], checkpoint=checkpoint, harness=state)

    assert state.answers == []
