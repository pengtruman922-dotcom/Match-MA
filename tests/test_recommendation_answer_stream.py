"""The streamed answer: SSE parsing, deterministic links, usable fallback."""

import asyncio
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import pytest

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


def _stream_route_body(monkeypatch: pytest.MonkeyPatch, *, configured: bool, fail_stream: bool = False) -> str:
    from backend.app.api.routes import recommendations as route

    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_get_recommendation_session_or_404", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(route, "agent_turn_aborted", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(route, "find_agent_turn_answer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "find_agent_turn_brief", lambda *_args, **_kwargs: _BRIEF)
    monkeypatch.setattr(route, "_touch_recommendation_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "insert_agent_answer_message", lambda *_args, **_kwargs: uuid4())

    @contextmanager
    def fake_scope():
        yield object()

    monkeypatch.setattr(route, "session_scope", fake_scope)
    if configured:
        monkeypatch.setattr(route, "_get_default_node_config", lambda *_args, **_kwargs: {
            "base_url": "https://example.invalid",
            "api_key_secret_ref": "x",
            "model_name": "writer",
            "temperature": 0.4,
            "top_p": 1,
            "max_tokens": 1000,
            "timeout_seconds": 30,
        })
        monkeypatch.setattr(route, "_render_prompt_messages", lambda *_args, **_kwargs: [])

        def stream(*_args, **_kwargs):
            if fail_stream:
                raise RuntimeError("writer failed")
            yield "推荐杭州XX精密制造。"

        monkeypatch.setattr(route, "stream_openai_compatible_chat", stream)
    else:
        monkeypatch.setattr(
            route,
            "_get_default_node_config",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("not configured")),
        )

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


def test_unconfigured_writer_streams_and_persists_the_rule_fallback(monkeypatch) -> None:
    body = _stream_route_body(monkeypatch, configured=False)

    assert "event: done" in body
    assert "30 家去重候选" in body
    assert "](/targets/t-1)" in body
    assert '"duration_ms":' in body


def test_writer_stream_failure_still_finishes_with_the_same_fallback(monkeypatch) -> None:
    body = _stream_route_body(monkeypatch, configured=True, fail_stream=True)

    assert "event: error" in body
    assert "event: done" in body
    assert "30 家去重候选" in body


def test_abort_that_lands_after_stream_connect_prevents_answer_and_persistence(monkeypatch) -> None:
    """The abort marker wins even when another tab already opened the SSE."""
    from backend.app.api.routes import recommendations as route

    checks = iter([False, True])
    persisted: list[str] = []
    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_get_recommendation_session_or_404", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(route, "agent_turn_aborted", lambda *_args, **_kwargs: next(checks, True))
    monkeypatch.setattr(route, "find_agent_turn_answer", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "find_agent_turn_brief", lambda *_args, **_kwargs: _BRIEF)
    monkeypatch.setattr(route, "_touch_recommendation_session", lambda *_args, **_kwargs: None)

    def persist(*_args, **_kwargs):
        persisted.append("answer")
        return uuid4()

    monkeypatch.setattr(route, "insert_agent_answer_message", persist)

    @contextmanager
    def fake_scope():
        yield object()

    monkeypatch.setattr(route, "session_scope", fake_scope)
    monkeypatch.setattr(route, "_get_default_node_config", lambda *_args, **_kwargs: {
        "base_url": "https://example.invalid",
        "api_key_secret_ref": "x",
        "model_name": "writer",
        "temperature": 0.4,
        "top_p": 1,
        "max_tokens": 1000,
        "timeout_seconds": 30,
    })
    monkeypatch.setattr(route, "_render_prompt_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(route, "stream_openai_compatible_chat", lambda *_args, **_kwargs: iter(["不应落库"]))

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

    body = asyncio.run(collect())

    assert "event: aborted" in body
    assert "event: delta" not in body
    assert "event: done" not in body
    assert persisted == []


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
