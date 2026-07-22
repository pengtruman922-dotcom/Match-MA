"""The agent loop: call the model, run whatever tools it asks for, repeat.

This is the whole mechanism behind every agent framework — send the tool
schemas, and when the reply carries tool_calls instead of an answer, execute
them, append the results, and ask again. Keeping it here rather than inside a
job handler means the research flow only has to supply tools and prompts, and
the loop itself can be tested without a model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.app.ai.llm_client import ChatCompletionResult, ToolCall

# 每个工具返回给模型的字符数上限。一次网页抓取可能是几万字，几轮就撑爆上下文。
DEFAULT_TOOL_RESULT_LIMIT = 8000


@dataclass
class ToolLoopUsage:
    llm_calls: int = 0
    tool_calls_by_name: dict[str, int] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0

    def record_llm(self, result: ChatCompletionResult) -> None:
        self.llm_calls += 1
        self.prompt_tokens += result.prompt_tokens or 0
        self.completion_tokens += result.completion_tokens or 0
        self.total_tokens += result.total_tokens or 0
        self.latency_ms += result.latency_ms

    def record_tool(self, name: str) -> None:
        self.tool_calls_by_name[name] = self.tool_calls_by_name.get(name, 0) + 1


@dataclass
class ToolLoopResult:
    result: ChatCompletionResult
    messages: list[dict[str, Any]]
    usage: ToolLoopUsage
    hit_iteration_limit: bool


def run_tool_loop(
    *,
    chat: Callable[..., ChatCompletionResult],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    execute_tool: Callable[[ToolCall], Any],
    max_iterations: int = 12,
    tool_result_limit: int = DEFAULT_TOOL_RESULT_LIMIT,
    final_turn_instruction: str = "已达到工具调用上限。请立即基于已获得的信息输出最终结果，不要再调用任何工具。",
) -> ToolLoopResult:
    """Drive `chat` until it answers instead of asking for tools.

    `chat` is called as chat(messages=..., tools=...) so the caller can bind
    model, credentials and sampling parameters ahead of time. `execute_tool`
    receives one ToolCall and returns anything JSON-serialisable; raising is
    allowed — the error goes back to the model as that tool's result, which it
    can usually recover from, rather than losing the whole run.
    """
    conversation = list(messages)
    usage = ToolLoopUsage()

    for iteration in range(max_iterations):
        result = chat(messages=conversation, tools=tools)
        usage.record_llm(result)
        if not result.tool_calls:
            return ToolLoopResult(
                result=result,
                messages=conversation,
                usage=usage,
                hit_iteration_limit=False,
            )

        conversation.append(result.assistant_message or _assistant_message_from(result))
        for call in result.tool_calls:
            usage.record_tool(call.name)
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _tool_result_content(call, execute_tool, tool_result_limit),
                }
            )

    # 用光预算：不带工具再要一轮，保证总有结构化产出而不是半截对话。
    conversation.append({"role": "user", "content": final_turn_instruction})
    result = chat(messages=conversation, tools=None)
    usage.record_llm(result)
    return ToolLoopResult(
        result=result,
        messages=conversation,
        usage=usage,
        hit_iteration_limit=True,
    )


def _tool_result_content(
    call: ToolCall,
    execute_tool: Callable[[ToolCall], Any],
    limit: int,
) -> str:
    if call.arguments_error:
        return json.dumps({"error": call.arguments_error}, ensure_ascii=False)
    try:
        value = execute_tool(call)
    except Exception as exc:  # noqa: BLE001 - 工具失败要回传给模型，不是终止运行
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原长度 {len(text)} 字符）"


def _assistant_message_from(result: ChatCompletionResult) -> dict[str, Any]:
    """Rebuild the assistant turn when the provider did not echo it back."""
    return {
        "role": "assistant",
        "content": result.raw_output_text or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_arguments},
            }
            for call in result.tool_calls
        ],
    }
