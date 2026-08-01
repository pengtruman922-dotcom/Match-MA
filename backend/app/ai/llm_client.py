from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from backend.app.services.model_secrets import ModelSecretError, decrypt_model_secret


class LlmCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # 参数解析失败时保留原文，便于把错误回传给模型而不是直接失败。
    raw_arguments: str
    arguments_error: str | None = None


@dataclass(frozen=True)
class ChatCompletionResult:
    raw_output_text: str
    parsed_output_json: dict[str, Any] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    # choices[0].message 原样保留：工具循环要把它按原样放回 messages。
    assistant_message: dict[str, Any] | None = None


def call_openai_compatible_chat(
    *,
    base_url: str,
    api_key_secret_ref: str | None,
    model_name: str,
    messages: list[dict[str, Any]],
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    timeout_seconds: int,
    api_key_encrypted: str | None = None,
    response_format: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> ChatCompletionResult:
    api_key = _get_api_key(api_key_secret_ref, api_key_encrypted)
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if top_p is not None:
        payload["top_p"] = float(top_p)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        # 部分 OpenAI 兼容层在同时传 tools 和 response_format 时会冲突，
        # 工具调用时不强制 json_object 格式。
    elif response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.perf_counter()
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LlmCallError(f"LLM HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise LlmCallError(f"LLM request failed: {exc.reason}") from exc
    except (TimeoutError, ConnectionError) as exc:
        # 读超时从 urlopen 抛的是裸 TimeoutError（OSError 子类），不是 URLError。
        # 不包起来它就绕过了调用方的 except LlmCallError —— 失败分支写 trace 的
        # 代码不会执行，一次 15 分钟的挂死最后什么记录都不留。
        # `from exc` 必须保留：重试判定靠 __cause__ 链认出 TimeoutError。
        raise LlmCallError(f"LLM request timed out or dropped after {timeout_seconds}s: {exc!r}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        response_json = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LlmCallError(f"LLM response is not valid JSON: {response_body[:500]}") from exc

    try:
        choice = response_json["choices"][0]
        assistant_message = choice["message"]
        if not isinstance(assistant_message, dict):
            raise TypeError("message is not an object")
    except (KeyError, IndexError, TypeError) as exc:
        message = f"LLM response missing choices[0].message: {response_body[:500]}"
        raise LlmCallError(message) from exc

    tool_calls = _parse_tool_calls(assistant_message.get("tool_calls"))
    raw_output_text = assistant_message.get("content") or ""
    # 请求工具时 content 为空是正常的；只有既没内容也没工具调用才是坏响应。
    if not raw_output_text and not tool_calls:
        raise LlmCallError(
            f"LLM response has neither content nor tool_calls: {response_body[:500]}"
        )

    usage = response_json.get("usage") or {}
    parsed_output_json = _parse_json_object(raw_output_text)
    return ChatCompletionResult(
        raw_output_text=raw_output_text,
        parsed_output_json=parsed_output_json,
        prompt_tokens=_optional_int(usage.get("prompt_tokens")),
        completion_tokens=_optional_int(usage.get("completion_tokens")),
        total_tokens=_optional_int(usage.get("total_tokens")),
        latency_ms=latency_ms,
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason"),
        assistant_message=assistant_message,
    )


def _parse_tool_calls(value: Any) -> tuple[ToolCall, ...]:
    """Read tool calls out of an assistant message.

    Malformed arguments are carried through rather than raised: the loop can
    hand the error back to the model, which usually retries correctly, whereas
    failing the call throws away every tool result gathered so far.
    """
    if not isinstance(value, list):
        return ()
    calls: list[ToolCall] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        raw_arguments = function.get("arguments")
        if isinstance(raw_arguments, dict):
            arguments, raw_text, argument_error = raw_arguments, json.dumps(
                raw_arguments, ensure_ascii=False
            ), None
        else:
            raw_text = str(raw_arguments or "").strip()
            arguments, argument_error = {}, None
            if raw_text:
                try:
                    decoded = json.loads(raw_text)
                except json.JSONDecodeError as exc:
                    argument_error = f"arguments is not valid JSON: {exc}"
                else:
                    if isinstance(decoded, dict):
                        arguments = decoded
                    else:
                        argument_error = "arguments is not a JSON object"
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call_{index}"),
                name=name,
                arguments=arguments,
                raw_arguments=raw_text,
                arguments_error=argument_error,
            )
        )
    return tuple(calls)


def _get_api_key(api_key_secret_ref: str | None, api_key_encrypted: str | None = None) -> str | None:
    if api_key_encrypted:
        try:
            return decrypt_model_secret(api_key_encrypted)
        except ModelSecretError as exc:
            raise LlmCallError(str(exc)) from exc
    if not api_key_secret_ref:
        return None
    api_key = os.getenv(api_key_secret_ref)
    if not api_key:
        raise LlmCallError(f"Environment variable is not configured: {api_key_secret_ref}")
    return api_key


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _strip_code_fence(cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
