"""Multi-turn context: what the next agent turn is allowed to read."""

import json
from typing import Any
from uuid import uuid4

import pytest

from backend.app.services import recommendation_flow
from backend.app.services.recommendation_flow import (
    AGENT_HISTORY_MAX_TURNS,
    agent_history_context,
)

SESSION_ID = uuid4()


def _user(text: str, *, turn_id: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {"message_type": "agent_user_message"}
    if turn_id:
        metadata["turn_id"] = turn_id
    return {"role": "user", "content": text, "content_type": "text", "metadata_json": metadata}


def _json_message(turn_id: str, message_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {"message_type": message_type, "turn_id": turn_id, **payload}
    return {
        "role": "tool",
        "content": json.dumps(body, ensure_ascii=False),
        "content_type": "json",
        "metadata_json": {"message_type": message_type, "turn_id": turn_id},
    }


def _answer(turn_id: str, markdown: str) -> dict[str, Any]:
    return _json_message(turn_id, "agent_answer", {"markdown": markdown})


def _aborted(turn_id: str) -> dict[str, Any]:
    return _json_message(turn_id, "agent_aborted", {})


def _turn(turn_id: str, question: str, answer: str) -> list[dict[str, Any]]:
    return [_user(question, turn_id=turn_id), _answer(turn_id, answer)]


@pytest.fixture
def messages(monkeypatch: pytest.MonkeyPatch):
    stored: list[dict[str, Any]] = []

    def fake_list(db, *, session_id, limit, offset):  # noqa: ANN001 - 测试替身
        return stored

    monkeypatch.setattr(recommendation_flow, "_list_recommendation_messages", fake_list)
    return stored


# -- 原文，不是摘要 -------------------------------------------------------


def test_history_carries_both_halves_verbatim(messages: list[dict[str, Any]]) -> None:
    messages.extend(_turn("t1", "华东精密制造，净利 2000 万以上", "给你三家：A、B、C。"))

    context = agent_history_context(None, SESSION_ID)

    assert context.startswith("<history_context>")
    assert context.endswith("</history_context>")
    assert "<user>：华东精密制造，净利 2000 万以上" in context
    assert "<AI>：给你三家：A、B、C。" in context


def test_history_is_empty_when_nothing_completed(messages: list[dict[str, Any]]) -> None:
    messages.append(_user("刚问完还没答", turn_id="t1"))

    assert agent_history_context(None, SESSION_ID) == ""


# -- 半截的轮次一律整轮丢掉 ------------------------------------------------


def test_stopped_turn_is_left_out_entirely(messages: list[dict[str, Any]]) -> None:
    messages.extend(_turn("t1", "第一问", "第一答"))
    messages.extend([_user("被停掉的问题", turn_id="t2"), _answer("t2", "半截答案"), _aborted("t2")])

    context = agent_history_context(None, SESSION_ID)

    assert "第一问" in context
    assert "被停掉的问题" not in context
    assert "半截答案" not in context


def test_turn_without_a_write_up_is_left_out(messages: list[dict[str, Any]]) -> None:
    messages.extend(_turn("t1", "第一问", "第一答"))
    # 素材落库了但正文没写（关页签），这一轮同样不该进上下文。
    messages.append(_user("第二问", turn_id="t2"))
    messages.append(_json_message("t2", "agent_brief", {"brief": {"understanding": "..."}}))

    context = agent_history_context(None, SESSION_ID)

    assert "第一问" in context
    assert "第二问" not in context


def test_stopped_turns_do_not_consume_the_turn_budget(messages: list[dict[str, Any]]) -> None:
    assert AGENT_HISTORY_MAX_TURNS == 5
    for index in range(AGENT_HISTORY_MAX_TURNS):
        messages.extend(_turn(f"ok{index}", f"问题{index}", f"回答{index}"))
    messages.extend([_user("停掉的", turn_id="stopped"), _aborted("stopped")])

    context = agent_history_context(None, SESSION_ID)

    assert context.count("<user>：") == AGENT_HISTORY_MAX_TURNS
    assert "问题0" in context


# -- 预算 -----------------------------------------------------------------


def test_only_the_last_five_turns_survive(messages: list[dict[str, Any]]) -> None:
    assert AGENT_HISTORY_MAX_TURNS == 5
    for index in range(AGENT_HISTORY_MAX_TURNS + 3):
        messages.extend(_turn(f"t{index}", f"问题{index}", f"回答{index}"))

    context = agent_history_context(None, SESSION_ID)

    assert context.count("<user>：") == AGENT_HISTORY_MAX_TURNS
    assert "问题0" not in context
    assert f"问题{AGENT_HISTORY_MAX_TURNS + 2}" in context


def test_over_budget_drops_whole_turns_and_never_truncates(
    messages: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recommendation_flow, "AGENT_HISTORY_MAX_CHARS", 120)
    messages.extend(_turn("old", "旧问题", "旧" * 100))
    messages.extend(_turn("new", "新问题", "新回答"))

    context = agent_history_context(None, SESSION_ID)

    assert "新问题" in context
    assert "旧问题" not in context
    # 丢掉的是整轮，绝不能留半截。
    assert "旧" not in context


# -- 早期数据 -------------------------------------------------------------


def test_user_messages_without_a_turn_id_still_find_their_answer(
    messages: list[dict[str, Any]],
) -> None:
    messages.append(_user("turn_id 落到用户消息之前写的行"))
    messages.append(_answer("t1", "对应的回答"))

    context = agent_history_context(None, SESSION_ID)

    assert "<user>：turn_id 落到用户消息之前写的行" in context
    assert "<AI>：对应的回答" in context
