"""The streamed answer: SSE parsing, deterministic links, usable fallback."""

from typing import Any

import pytest

from backend.app.ai.llm_client import LlmCallError, stream_openai_compatible_chat
from backend.app.services.recommendation_answer import (
    backfill_target_links,
    fallback_answer_markdown,
    plain_text_for_copy,
    target_link_map,
)

_BRIEF: dict[str, Any] = {
    "mode": "buyer_to_target",
    "understanding": "华东 · 精密制造 · 净利≥2000万",
    "total_eligible": 56,
    "recommended": [
        {
            "id": "t-1",
            "name": "杭州XX精密制造",
            "facts": {"net_profit_text": "2800万", "region": "浙江杭州", "can_control": "是", "pe_ratio": 8.5},
            "reason_points": ["产线与买方互补"],
            "watch_out": "应收账款偏高",
        },
        {
            "id": "t-2",
            "name": "苏州XX电子",
            "facts": {"net_profit_text": "3100万", "region": "江苏苏州"},
            "reason_points": [],
            "other_buyer_in_deep_progress": True,
        },
    ],
    "runner_ups": [{"name": "常州XX自动化", "note": "要价偏高"}],
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


def test_link_map_only_covers_candidates_the_turn_recommended() -> None:
    assert target_link_map(_BRIEF) == {"杭州XX精密制造": "t-1", "苏州XX电子": "t-2"}
    assert target_link_map({"recommended": [{"name": "无 id 的"}]}) == {}


def test_copy_text_strips_links_back_to_bare_names() -> None:
    linked = backfill_target_links("推荐杭州XX精密制造。", {"杭州XX精密制造": "t-1"})

    assert plain_text_for_copy(linked) == "推荐杭州XX精密制造。"


# -- fallback ------------------------------------------------------------


def test_fallback_answer_quotes_the_hard_numbers() -> None:
    markdown = fallback_answer_markdown(_BRIEF)

    assert "56 家" in markdown
    assert "净利 2800万" in markdown
    assert "浙江杭州" in markdown
    assert "可控股 是" in markdown
    assert "PE 8.5" in markdown
    assert "应收账款偏高" in markdown


def test_fallback_answer_flags_deep_progress_without_naming_the_buyer() -> None:
    markdown = fallback_answer_markdown(_BRIEF)

    assert "正与其他买家深入推进" in markdown


def test_fallback_answer_survives_an_empty_brief() -> None:
    markdown = fallback_answer_markdown({})

    assert markdown.strip()


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
