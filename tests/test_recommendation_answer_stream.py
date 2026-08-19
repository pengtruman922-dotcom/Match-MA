"""The streamed answer: SSE parsing, deterministic links, usable fallback.

Generation itself moved into the worker on 2026-08-19 (see
`tests/test_recommendation_writer.py`); what is left here is the reading
contract and the pure text helpers both sides share.
"""

import asyncio
import pathlib
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.ai.llm_client import LlmCallError, stream_openai_compatible_chat
from backend.app.services.recommendation_answer import (
    backfill_target_links,
    fallback_answer_markdown,
    plain_text_for_copy,
    sanitize_writer_output,
    target_link_map,
)

_BRIEF: dict[str, Any] = {
    "mode": "buyer_to_target",
    "brief_version": 2,
    "intent_summary": "华东 · 精密制造 · 净利≥2000万",
    "parser_status": "ok",
    "selection_source": "deep_eval",
    "deep_eval_status": "ok",
    "candidate_pool_count": 30,
    "candidate_pool_capped": False,
    "follow_up_suggestions": ["细看杭州XX精密制造"],
    "recommended": [
        {
            "id": "t-1",
            "name": "杭州XX精密制造",
            "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "can_control": "是", "pe_ratio": 8.5},
            "reason_points": ["产线与买方互补"],
            "risks": "应收账款偏高",
            "info_gaps": "客户集中度待补充",
            "qualitative_verdicts": {"有海外仓": "基本满足"},
            "matched_full_conditions": True,
        },
        {
            "id": "t-2",
            "name": "苏州XX电子",
            "facts": {"net_profit_text": "3100万", "region": "江苏苏州"},
            "reason_points": [],
            "other_buyer_in_deep_progress": True,
            "matched_full_conditions": False,
            "required_relaxation": True,
            "relaxed_fields": [{
                "field": "min_net_profit_yuan",
                "label": "最低净利润",
                "strength": "required",
            }],
        },
    ],
    "runner_ups": [{"id": "t-3", "name": "常州XX自动化", "facts": {}, "reason_points": []}],
}


# -- link backfill -------------------------------------------------------


def test_longer_name_wins_so_a_prefix_cannot_eat_it() -> None:
    link_map = {"杭州XX精密制造": "t-1", "杭州XX": "t-2"}

    result = backfill_target_links("推荐杭州XX精密制造。", link_map)

    assert result == "推荐[杭州XX精密制造](/targets/t-1)。"


def test_each_target_is_linked_at_most_once() -> None:
    result = backfill_target_links("苏州XX电子很好，苏州XX电子估值也合适。", {"苏州XX电子": "t-3"})

    assert result.count("](/targets/t-3)") == 1
    assert result.endswith("苏州XX电子估值也合适。")


def test_an_already_linked_name_is_not_wrapped_twice() -> None:
    text = "见[苏州XX电子](/targets/t-3)。"

    assert backfill_target_links(text, {"苏州XX电子": "t-3"}) == text


def test_backfill_is_a_no_op_without_a_map() -> None:
    assert backfill_target_links("随便一段话", {}) == "随便一段话"
    assert backfill_target_links("", {"名字": "id"}) == ""


def test_link_map_covers_final_recommended_and_runner_ups() -> None:
    assert target_link_map(_BRIEF) == {
        "杭州XX精密制造": "t-1",
        "苏州XX电子": "t-2",
        "常州XX自动化": "t-3",
    }
    assert target_link_map({"recommended": [{"name": "无 id 的"}]}) == {}


def test_copy_text_strips_links_back_to_bare_names() -> None:
    linked = backfill_target_links("推荐杭州XX精密制造。", {"杭州XX精密制造": "t-1"})

    assert plain_text_for_copy(linked) == "推荐杭州XX精密制造。"


def test_writer_output_drops_model_links_ids_and_chip_text_before_safe_backfill() -> None:
    dirty = "推荐[杭州XX精密制造](https://evil.test/t-1)，id=t-1。细看杭州XX精密制造"

    cleaned = sanitize_writer_output(
        dirty,
        forbidden_ids=["t-1"],
        forbidden_phrases=["细看杭州XX精密制造"],
    )
    linked = backfill_target_links(cleaned, {"杭州XX精密制造": "t-1"})

    assert "evil.test" not in linked
    assert "id=t-1" not in linked
    assert "细看" not in linked
    assert linked.count("](/targets/t-1)") == 1


def test_writer_url_sanitizer_does_not_eat_following_chinese_prose() -> None:
    cleaned = sanitize_writer_output("旧链接 /targets/t-1，杭州XX精密制造仍值得看。")

    assert "杭州XX精密制造仍值得看" in cleaned
    assert "/targets/" not in cleaned


def test_unique_legal_name_abbreviation_is_backfilled_but_collision_is_not() -> None:
    unique = backfill_target_links(
        "重点看杭州星辰科技。",
        {"杭州星辰科技有限公司": "t-1"},
    )
    collided = backfill_target_links(
        "重点看星辰科技。",
        {
            "星辰科技有限公司": "t-1",
            "星辰科技股份有限公司": "t-2",
        },
    )

    assert unique == "重点看[杭州星辰科技](/targets/t-1)。"
    assert "](/targets/" not in collided


def test_full_name_and_alias_share_the_same_one_link_budget() -> None:
    linked = backfill_target_links(
        "杭州星辰科技有限公司值得看，杭州星辰科技的团队也不错。",
        {"杭州星辰科技有限公司": "t-1"},
    )

    assert linked.count("](/targets/t-1)") == 1


def test_two_targets_sharing_one_name_each_get_their_own_link() -> None:
    """生产真实数据里同名不同标的确实存在（UAT5 的浙江水晶光电两条记录）。"""
    brief = {
        "recommended": [
            {"id": "t-1", "name": "浙江水晶光电科技股份有限公司"},
            {"id": "t-2", "name": "浙江水晶光电科技股份有限公司"},
        ],
        "runner_ups": [],
    }
    link_map = target_link_map(brief)

    linked = backfill_target_links(
        "浙江水晶光电科技股份有限公司市值351.7亿。浙江水晶光电科技股份有限公司市值349亿。",
        link_map,
    )

    assert link_map == {"浙江水晶光电科技股份有限公司": ["t-1", "t-2"]}
    assert linked.count("](/targets/t-1)") == 1
    assert linked.count("](/targets/t-2)") == 1


def test_a_repeated_name_still_stops_at_one_link_per_target() -> None:
    link_map = {"同名公司": ["t-1", "t-2"]}

    linked = backfill_target_links("同名公司、同名公司、同名公司。", link_map)

    assert linked.count("](/targets/") == 2
    assert linked.endswith("同名公司。")


def test_mock_test_prefix_can_be_omitted_when_the_remaining_name_is_unique() -> None:
    linked = backfill_target_links(
        "重点看宁波精密注塑模具厂。",
        {"Mock测试-20260624-宁波精密注塑模具厂": "t-1"},
    )

    assert linked == "重点看[宁波精密注塑模具厂](/targets/t-1)。"


# -- fallback ------------------------------------------------------------


def test_fallback_answer_quotes_the_hard_numbers() -> None:
    markdown = fallback_answer_markdown(_BRIEF)

    assert "30 家去重候选" in markdown
    assert "总共符合" not in markdown
    assert "净利 2800万" in markdown
    assert "浙江杭州" in markdown
    assert "控股 是" in markdown
    assert "PE 8.5" in markdown
    assert "应收账款偏高" in markdown
    assert "客户集中度待补充" in markdown
    assert "有海外仓：基本满足" in markdown
    assert "仅供参考" in markdown
    assert "细看杭州XX精密制造" not in markdown


def test_fallback_answer_flags_deep_progress_without_naming_the_buyer() -> None:
    markdown = fallback_answer_markdown(_BRIEF)

    assert "正与其他买家深入推进" in markdown


def test_fallback_answer_survives_an_empty_brief() -> None:
    markdown = fallback_answer_markdown({})

    assert markdown.strip()
    assert "未形成可推荐名单" in markdown


def test_fallback_answer_uses_explicit_degraded_wording() -> None:
    brief = {**_BRIEF, "selection_source": "agent_fallback", "deep_eval_status": "unavailable"}

    markdown = fallback_answer_markdown(brief)

    assert "深评未能完整返回" in markdown
    assert "需进一步核实" in markdown


# -- the endpoint as a subscriber ----------------------------------------
#
# `/answer-stream` no longer generates anything. It replays a finished answer
# or follows the draft row the worker is filling in, so these cases are about
# the reading contract — the four event types the page understands, unchanged
# from when this endpoint did the writing.


class _TurnState:
    """What the three tables say about one turn, from the reader's side."""

    def __init__(self) -> None:
        self.answer: dict[str, Any] | None = None
        self.aborted = False
        self.drafts: list[str] = []
        self.job_status = "running"
        self.polls = 0

    def draft_now(self) -> str:
        if not self.drafts:
            return ""
        return self.drafts[min(self.polls - 1, len(self.drafts) - 1)]


def _subscribe_body(monkeypatch: pytest.MonkeyPatch, state: _TurnState) -> str:
    from backend.app.api.routes import recommendations as route

    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_get_recommendation_session_or_404", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(route, "find_agent_turn_brief", lambda *_args, **_kwargs: _BRIEF)
    monkeypatch.setattr(route, "SUBSCRIBE_POLL_SECONDS", 0)

    connect_check = {"done": False}

    def aborted(*_args, **_kwargs) -> bool:
        # 第一次是连接前的 409 判断，之后才是订阅循环里的复查。
        if not connect_check["done"]:
            connect_check["done"] = True
            return False
        state.polls += 1
        return state.aborted

    monkeypatch.setattr(route, "agent_turn_aborted", aborted)
    monkeypatch.setattr(route, "find_agent_turn_answer", lambda *_args, **_kwargs: state.answer)
    monkeypatch.setattr(
        route,
        "read_answer_draft",
        lambda *_args, **_kwargs: {"markdown": state.draft_now()},
    )
    monkeypatch.setattr(
        route,
        "find_agent_turn_job",
        lambda *_args, **_kwargs: {"status": state.job_status},
    )

    @contextmanager
    def fake_scope():
        yield object()

    monkeypatch.setattr(route, "session_scope", fake_scope)

    response = route.stream_recommendation_answer(
        uuid4(),
        "turn-1",
        current_user=object(),
        db=object(),
    )

    async def collect() -> str:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
        return "".join(chunks)

    return asyncio.run(collect())


def test_subscriber_streams_the_draft_then_finishes_on_the_persisted_answer(monkeypatch) -> None:
    state = _TurnState()
    state.drafts = ["推荐杭州XX", "推荐杭州XX精密制造。"]

    class _Answering(_TurnState):
        pass

    # 第三次轮询时 worker 已经把正文落库。
    original = state.draft_now

    def draft_now() -> str:
        if state.polls >= 3:
            state.answer = {
                "id": uuid4(),
                "markdown": "推荐[杭州XX精密制造](/targets/t-1)。",
                "duration_ms": 46700,
            }
        return original()

    state.draft_now = draft_now  # type: ignore[method-assign]

    body = _subscribe_body(monkeypatch, state)

    assert body.count("event: delta") == 2
    assert '"text": "推荐杭州XX"' in body
    # 第二个 delta 只带增量，不重发已经发过的前缀。
    assert '"text": "精密制造。"' in body
    assert "event: done" in body
    assert '"duration_ms": 46700' in body


def test_subscriber_emits_the_writer_duration_measured_in_the_worker(monkeypatch) -> None:
    state = _TurnState()
    state.answer = {"id": uuid4(), "markdown": "正文。", "duration_ms": 46700}

    body = _subscribe_body(monkeypatch, state)

    # 走的是 find_agent_turn_answer 的回放分支：不重新生成，不二次计费。
    assert '"replayed": true' in body
    assert '"duration_ms": 46700' in body


def test_two_tabs_watching_one_turn_both_get_the_same_answer(monkeypatch) -> None:
    """双页签：两个订阅者都只是读者，谁都不会再生成一次正文。"""
    answer = {"id": uuid4(), "markdown": "同一段正文。", "duration_ms": 1200}
    bodies = []
    for _ in range(2):
        state = _TurnState()
        state.answer = answer
        bodies.append(_subscribe_body(monkeypatch, state))

    assert bodies[0] == bodies[1]
    assert bodies[0].count("event: done") == 1


def test_subscriber_reports_a_stop_written_by_another_tab(monkeypatch) -> None:
    state = _TurnState()
    state.drafts = ["写到一半"]
    state.aborted = True

    body = _subscribe_body(monkeypatch, state)

    assert "event: aborted" in body
    assert "event: delta" not in body
    assert "event: done" not in body


def test_subscriber_says_so_when_the_job_ended_without_an_answer(monkeypatch) -> None:
    state = _TurnState()
    state.job_status = "failed"

    body = _subscribe_body(monkeypatch, state)

    assert "event: error" in body
    assert "没能生成正文" in body
    assert "event: done" not in body


def test_an_answer_that_landed_is_never_reported_as_a_failed_turn(monkeypatch) -> None:
    """worker 先提交正文、再标记成功，读者必须按同样的顺序读。

    倒过来读会在这两次提交之间读到「已成功且没有正文」——一个并不存在的状态，
    后果是把一轮刚刚写完的正文报成失败。
    """
    state = _TurnState()
    state.job_status = "succeeded"
    state.answer = {"id": uuid4(), "markdown": "写完了的正文。", "duration_ms": 1000}

    body = _subscribe_body(monkeypatch, state)

    assert "event: done" in body
    assert "event: error" not in body


def test_a_requeued_turn_keeps_the_reader_waiting_rather_than_failing_it(monkeypatch) -> None:
    """优雅退出把 job 放回 queued —— 那是重排，不是失败，不该报 error。"""
    state = _TurnState()
    state.job_status = "queued"
    state.drafts = ["新一轮开头"]

    class _Finisher:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> str:
            self.calls += 1
            if self.calls >= 3:
                state.answer = {"id": uuid4(), "markdown": "重排后写完的正文。", "duration_ms": 900}
            return state.drafts[0]

    state.draft_now = _Finisher()  # type: ignore[method-assign]

    body = _subscribe_body(monkeypatch, state)

    assert "event: error" not in body
    assert "event: done" in body
    assert "重排后写完的正文。" in body


def test_a_restarted_draft_is_not_replayed_as_duplicated_prose(monkeypatch) -> None:
    """job 重排后草稿从头开始：已发出的收不回来，但也绝不能再发一遍。"""
    state = _TurnState()
    state.drafts = ["第一次的开头", "第二次完全不同的开头"]

    original = state.draft_now

    def draft_now() -> str:
        if state.polls >= 3:
            state.answer = {"id": uuid4(), "markdown": "第二次完全不同的开头，写完了。", "duration_ms": 800}
        return original()

    state.draft_now = draft_now  # type: ignore[method-assign]

    body = _subscribe_body(monkeypatch, state)

    assert body.count("event: delta") == 1
    assert "第二次完全不同的开头" not in body.split("event: done")[0]
    assert "event: done" in body


def test_subscriber_gives_up_politely_instead_of_hanging_forever(monkeypatch) -> None:
    from backend.app.api.routes import recommendations as route

    monkeypatch.setattr(route, "SUBSCRIBE_MAX_SECONDS", 0)
    state = _TurnState()

    body = _subscribe_body(monkeypatch, state)

    assert "event: error" in body
    assert "还在生成中" in body


def test_a_stopped_turn_is_refused_before_the_stream_opens(monkeypatch) -> None:
    from backend.app.api.routes import recommendations as route

    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_get_recommendation_session_or_404", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(route, "agent_turn_aborted", lambda *_args, **_kwargs: True)

    with pytest.raises(HTTPException) as raised:
        route.stream_recommendation_answer(uuid4(), "turn-1", current_user=object(), db=object())

    assert raised.value.status_code == 409


def test_the_endpoint_no_longer_knows_how_to_generate_anything(monkeypatch) -> None:
    """回归护栏：正文的所有者是 worker job，不是这个请求。

    这个断言看着像洁癖，其实是问题四的根：只要 API 还能自己生成一次，
    「关页签就丢正文、重开又重新付费」这条路径就还在。
    """
    from backend.app.api.routes import recommendations as route

    source = pathlib.Path(route.__file__).read_text(encoding="utf-8")

    assert "stream_openai_compatible_chat" not in source
    assert "insert_agent_answer_message" not in source
    assert "fallback_answer_markdown" not in source


# -- SSE parsing ---------------------------------------------------------


class _FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self) -> None:
        self.closed = True


def _stream(monkeypatch: pytest.MonkeyPatch, lines: list[bytes]):
    response = _FakeResponse(lines)
    monkeypatch.setattr(
        "backend.app.ai.llm_client.request.urlopen",
        lambda *args, **kwargs: response,
    )
    chunks = list(
        stream_openai_compatible_chat(
            base_url="https://example.test/v1",
            api_key_secret_ref=None,
            model_name="test-model",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.4,
            top_p=0.9,
            max_tokens=100,
            timeout_seconds=30,
        )
    )
    return chunks, response


def test_stream_yields_content_deltas_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks, response = _stream(
        monkeypatch,
        [
            b'data: {"choices":[{"delta":{"content":"\\u6309"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"\\u4f60"}}]}\n',
            b"data: [DONE]\n",
        ],
    )

    assert "".join(chunks) == "按你"
    assert response.closed is True


def test_stream_skips_blank_lines_and_unparsable_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks, _ = _stream(
        monkeypatch,
        [
            b"\n",
            b": heartbeat\n",
            b"data: not-json\n",
            b'data: {"choices":[{"delta":{}}]}\n',
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
            b"data: [DONE]\n",
        ],
    )

    assert "".join(chunks) == "ok"


def test_stream_stops_at_done_and_ignores_trailing_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks, _ = _stream(
        monkeypatch,
        [
            b'data: {"choices":[{"delta":{"content":"a"}}]}\n',
            b"data: [DONE]\n",
            b'data: {"choices":[{"delta":{"content":"b"}}]}\n',
        ],
    )

    assert "".join(chunks) == "a"


def test_stream_hangs_up_when_the_node_budget_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`timeout_seconds` 是节点整体超时，不是两个包之间的间隔。

    urlopen 的 timeout 每来一个 token 就重置 —— 配 180 秒的 Writer，只要上游
    一直滴字就能跑十分钟。所以流自己也要掐表。
    """
    import backend.app.ai.llm_client as client

    ticks = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    monkeypatch.setattr(client.time, "perf_counter", lambda: next(ticks, 999.0))

    with pytest.raises(LlmCallError) as raised:
        _stream(monkeypatch, [
            b'data: {"choices":[{"delta":{"content":"first"}}]}',
            b'data: {"choices":[{"delta":{"content":"second"}}]}',
        ])

    assert "budget" in str(raised.value)


def test_a_stream_inside_its_budget_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app.ai.llm_client as client

    monkeypatch.setattr(client.time, "perf_counter", lambda: 0.0)

    chunks, response = _stream(monkeypatch, [
        b'data: {"choices":[{"delta":{"content":"first"}}]}',
        b'data: [DONE]',
    ])

    assert chunks == ["first"]
    # 断开也好、正常收尾也好，连接都必须关掉。
    assert response.closed is True


def test_stream_wraps_transport_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any):
        raise TimeoutError("read timed out")

    monkeypatch.setattr("backend.app.ai.llm_client.request.urlopen", boom)

    with pytest.raises(LlmCallError):
        list(
            stream_openai_compatible_chat(
                base_url="https://example.test/v1",
                api_key_secret_ref=None,
                model_name="test-model",
                messages=[],
                temperature=None,
                top_p=None,
                max_tokens=None,
                timeout_seconds=1,
            )
        )


def test_stream_request_sets_the_stream_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def capture(req: Any, *args: Any, **kwargs: Any):
        import json as _json

        captured.update(_json.loads(req.data.decode("utf-8")))
        return _FakeResponse([b"data: [DONE]\n"])

    monkeypatch.setattr("backend.app.ai.llm_client.request.urlopen", capture)
    list(
        stream_openai_compatible_chat(
            base_url="https://example.test/v1",
            api_key_secret_ref=None,
            model_name="test-model",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.4,
            top_p=None,
            max_tokens=None,
            timeout_seconds=30,
        )
    )

    assert captured["stream"] is True
    assert "tools" not in captured
