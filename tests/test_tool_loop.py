"""The agent loop and the tool-calling half of the LLM client."""

import json

import pytest

from backend.app.ai.llm_client import (
    ChatCompletionResult,
    LlmCallError,
    ToolCall,
    _parse_tool_calls,
)
from backend.app.ai.tool_loop import run_tool_loop


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _reply(text: str = "", *, tool_calls: tuple[ToolCall, ...] = ()) -> ChatCompletionResult:
    parsed = None
    if text:
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            parsed = candidate if isinstance(candidate, dict) else None
    return ChatCompletionResult(
        raw_output_text=text,
        parsed_output_json=parsed,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=100,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        assistant_message={"role": "assistant", "content": text or None},
    )


class _ScriptedChat:
    """Returns pre-written replies and records what it was asked."""

    def __init__(self, replies: list[ChatCompletionResult]) -> None:
        self._replies = replies
        self.calls: list[dict] = []

    def __call__(self, *, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._replies[len(self.calls) - 1]


def test_loop_returns_immediately_when_the_model_answers() -> None:
    chat = _ScriptedChat([_reply('{"profile_sections": []}')])

    outcome = run_tool_loop(
        chat=chat,
        messages=[{"role": "user", "content": "调研这家公司"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=lambda call: pytest.fail("不应调用工具"),
    )

    assert outcome.result.raw_output_text == '{"profile_sections": []}'
    assert outcome.hit_iteration_limit is False
    assert outcome.usage.llm_calls == 1
    assert outcome.usage.tool_calls_by_name == {}
    assert outcome.json_finalization_attempted is False


def test_loop_finalizes_invalid_answer_without_tools() -> None:
    invalid = 'Explanation before ```json\n{"summary": "an "unescaped" quote"}\n```'
    chat = _ScriptedChat([_reply(invalid), _reply('{"profile_sections": []}')])

    outcome = run_tool_loop(
        chat=chat,
        messages=[{"role": "user", "content": "research this company"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=lambda call: pytest.fail("should not call a tool"),
    )

    assert outcome.result.parsed_output_json == {"profile_sections": []}
    assert outcome.usage.llm_calls == 2
    assert outcome.hit_iteration_limit is False
    assert outcome.json_finalization_attempted is True
    assert chat.calls[-1]["tools"] is None
    assert chat.calls[-1]["messages"][-2]["role"] == "assistant"
    assert chat.calls[-1]["messages"][-2]["content"] == invalid
    assert "valid JSON object" in chat.calls[-1]["messages"][-1]["content"]


def test_loop_feeds_tool_results_back_and_continues() -> None:
    chat = _ScriptedChat(
        [
            _reply(tool_calls=(_tool_call("web_search", {"query": "苏州中析生物"}),)),
            _reply('{"profile_sections": [{"section_code": "business_product"}]}'),
        ]
    )
    executed = []

    def execute(call):
        executed.append((call.name, call.arguments))
        return [{"title": "公司简介", "url": "https://example.com"}]

    outcome = run_tool_loop(
        chat=chat,
        messages=[{"role": "user", "content": "调研这家公司"}],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=execute,
    )

    assert executed == [("web_search", {"query": "苏州中析生物"})]
    assert outcome.usage.llm_calls == 2
    assert outcome.usage.tool_calls_by_name == {"web_search": 1}
    assert outcome.usage.total_tokens == 30

    second_turn = chat.calls[1]["messages"]
    assert second_turn[-2]["role"] == "assistant"
    tool_message = second_turn[-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call_1"
    assert "公司简介" in tool_message["content"]


def test_tool_failure_is_reported_to_the_model_not_raised() -> None:
    """一次抓取失败不该丢掉之前所有已取得的结果。"""
    chat = _ScriptedChat(
        [
            _reply(tool_calls=(_tool_call("fetch_page", {"url": "https://dead.example"}),)),
            _reply('{"not_found": ["ops_quality"]}'),
        ]
    )

    def execute(call):
        raise TimeoutError("页面无响应")

    outcome = run_tool_loop(
        chat=chat,
        messages=[{"role": "user", "content": "调研"}],
        tools=[],
        execute_tool=execute,
    )

    tool_message = chat.calls[1]["messages"][-1]
    assert json.loads(tool_message["content"])["error"] == "TimeoutError: 页面无响应"
    assert outcome.result.raw_output_text == '{"not_found": ["ops_quality"]}'


def test_malformed_arguments_go_back_to_the_model_without_running_the_tool() -> None:
    broken = ToolCall(
        id="call_1",
        name="web_search",
        arguments={},
        raw_arguments="{query: 缺引号}",
        arguments_error="arguments is not valid JSON: bad",
    )
    chat = _ScriptedChat([_reply(tool_calls=(broken,)), _reply("{}")])

    run_tool_loop(
        chat=chat,
        messages=[],
        tools=[],
        execute_tool=lambda call: pytest.fail("参数坏掉时不应执行工具"),
    )

    tool_message = chat.calls[1]["messages"][-1]
    assert "not valid JSON" in json.loads(tool_message["content"])["error"]


def test_tool_results_are_truncated_before_entering_the_context() -> None:
    """一次抓取可能返回几万字，不截断几轮就撑爆上下文。"""
    chat = _ScriptedChat([_reply(tool_calls=(_tool_call("fetch_page", {}),)), _reply("{}")])

    run_tool_loop(
        chat=chat,
        messages=[],
        tools=[],
        execute_tool=lambda call: "正" * 50000,
        tool_result_limit=100,
    )

    content = chat.calls[1]["messages"][-1]["content"]
    assert len(content) < 200
    assert "已截断" in content


def test_iteration_limit_forces_a_final_answer_without_tools() -> None:
    """预算用光时要收得回结论，而不是留下半截对话。"""
    looping = [_reply(tool_calls=(_tool_call("web_search", {"query": "q"}),)) for _ in range(3)]
    chat = _ScriptedChat([*looping, _reply('{"not_found": []}')])

    outcome = run_tool_loop(
        chat=chat,
        messages=[],
        tools=[{"type": "function", "function": {"name": "web_search"}}],
        execute_tool=lambda call: "结果",
        max_iterations=3,
    )

    assert outcome.hit_iteration_limit is True
    assert outcome.json_finalization_attempted is True
    assert outcome.usage.llm_calls == 4
    assert outcome.usage.tool_calls_by_name == {"web_search": 3}
    # 收尾那轮不带工具，否则模型可能继续要求调用
    assert chat.calls[-1]["tools"] is None
    assert chat.calls[-1]["messages"][-1]["role"] == "user"
    assert outcome.result.raw_output_text == '{"not_found": []}'


def test_client_reads_tool_calls_out_of_an_assistant_message() -> None:
    calls = _parse_tool_calls(
        [
            {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "web_search", "arguments": '{"query": "并购"}'},
            }
        ]
    )

    assert len(calls) == 1
    assert calls[0].id == "call_abc"
    assert calls[0].name == "web_search"
    assert calls[0].arguments == {"query": "并购"}
    assert calls[0].arguments_error is None


def test_client_keeps_unparsable_arguments_instead_of_dropping_the_call() -> None:
    calls = _parse_tool_calls(
        [{"id": "c1", "function": {"name": "web_search", "arguments": "{query: 缺引号}"}}]
    )

    assert calls[0].arguments == {}
    assert calls[0].raw_arguments == "{query: 缺引号}"
    assert "not valid JSON" in calls[0].arguments_error


def test_client_ignores_malformed_tool_call_entries() -> None:
    assert _parse_tool_calls(None) == ()
    assert _parse_tool_calls("not-a-list") == ()
    assert _parse_tool_calls([{"function": {"name": ""}}, {"no_function": True}]) == ()


def test_empty_reply_with_no_tool_calls_is_still_an_error(monkeypatch) -> None:
    """content 为空在请求工具时是正常的，但两者都没有就是坏响应。"""
    from backend.app.ai import llm_client

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"role": "assistant", "content": None}}]}).encode()

    monkeypatch.setattr(llm_client.request, "urlopen", lambda *args, **kwargs: _Response())

    with pytest.raises(LlmCallError, match="neither content nor tool_calls"):
        llm_client.call_openai_compatible_chat(
            base_url="https://example.com/v1",
            api_key_secret_ref=None,
            model_name="qwen-plus",
            messages=[],
            temperature=None,
            top_p=None,
            max_tokens=None,
            timeout_seconds=10,
        )


def test_tools_are_only_sent_when_provided(monkeypatch) -> None:
    """不传 tools 时请求体必须和改造前完全一致，其他节点不受影响。"""
    from backend.app.ai import llm_client

    sent = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            ).encode()

    def fake_urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode())
        return _Response()

    monkeypatch.setattr(llm_client.request, "urlopen", fake_urlopen)

    def call(**overrides):
        return llm_client.call_openai_compatible_chat(
            base_url="https://example.com/v1",
            api_key_secret_ref=None,
            model_name="qwen-plus",
            messages=[{"role": "user", "content": "hi"}],
            temperature=None,
            top_p=None,
            max_tokens=None,
            timeout_seconds=10,
            **overrides,
        )

    call()
    assert "tools" not in sent["payload"]
    assert "tool_choice" not in sent["payload"]

    call(tools=[{"type": "function", "function": {"name": "web_search"}}], tool_choice="auto")
    assert sent["payload"]["tools"][0]["function"]["name"] == "web_search"
    assert sent["payload"]["tool_choice"] == "auto"
