from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from backend.app.services.model_secrets import ModelSecretError, decrypt_model_secret
from backend.app.shutdown import interruptible, raise_if_shutting_down


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


# 分块读的块大小。只影响墙钟的检查粒度，不影响吞吐。
_READ_CHUNK_BYTES = 65536


def _read_within_budget(response: Any, *, timeout_seconds: int, started: float) -> str:
    """把响应体读完，但整体不超过节点预算。

    `urlopen(timeout=...)` 只约束**单次 socket 操作**，所以一个慢慢吐字节的服务端
    能让一次调用远远超出预算 —— 流式路径的 docstring 早就写明了这件事并自己量墙钟，
    但缓冲式这一支一直只有那道 per-op 超时，而所有非流式节点都走它。

    **事故（2026-08-27 生产实测）**：一条 1462 字的买家需求，`buyer_intent_semantic_parser`
    配的是 300 秒，实际跑了 26 分钟仍未返回，job 一直 running、trace 一条没有（trace 是
    调用返回后才写的），前端就一直停在「语义解析中」。没有任何报错，因为确实没超时。

    分块读而不是另起看门狗线程：和流式那个循环同一个形状，也不引入新的并发面。
    """
    chunks: list[bytes] = []
    while True:
        if time.perf_counter() - started >= timeout_seconds:
            raise LlmCallError(
                f"LLM response exceeded the node budget of {timeout_seconds}s "
                f"（已读 {sum(len(chunk) for chunk in chunks)} 字节）"
            )
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


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
            # 关机时这个 response 会被从信号侧关掉，下面的 read 立刻抛错 ——
            # 否则一次 SIGTERM 要等满整个 timeout_seconds 才轮得到检查点，
            # 而容器只给十几秒。
            with interruptible(response):
                response_body = _read_within_budget(
                    response, timeout_seconds=timeout_seconds, started=started
                )
    except error.HTTPError as exc:
        raise_if_shutting_down()
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LlmCallError(f"LLM HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise_if_shutting_down()
        raise LlmCallError(f"LLM request failed: {exc.reason}") from exc
    except (TimeoutError, ConnectionError) as exc:
        # 读超时从 urlopen 抛的是裸 TimeoutError（OSError 子类），不是 URLError。
        # 不包起来它就绕过了调用方的 except LlmCallError —— 失败分支写 trace 的
        # 代码不会执行，一次 15 分钟的挂死最后什么记录都不留。
        # `from exc` 必须保留：重试判定靠 __cause__ 链认出 TimeoutError。
        raise_if_shutting_down()
        raise LlmCallError(f"LLM request timed out or dropped after {timeout_seconds}s: {exc!r}") from exc
    except (OSError, ValueError) as exc:
        # 我们自己关掉 fd 之后，重试的那次读会抛 EBADF / read of closed file。
        # 先认关机，再退回普通失败 —— 这两者的处置完全相反：一个是把 job 放回
        # 队列（不消耗 attempts），一个是判这一轮失败。
        raise_if_shutting_down()
        raise LlmCallError(f"LLM request failed: {exc!r}") from exc

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


def stream_openai_compatible_chat(
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
) -> Iterator[str]:
    """Yield content deltas from an OpenAI-compatible `stream: true` response.

    Deliberately separate from `call_openai_compatible_chat` and deliberately
    tool-free. Streaming a turn that carries tools means reassembling
    tool_call arguments from per-index fragments, which is the messiest part of
    the protocol; the only turn we stream is the final, tool-free write-up, so
    that work is avoided rather than done. Anything needing tools keeps using
    the buffered call.

    `timeout_seconds` is enforced **twice**, on purpose. `urlopen` applies it
    per socket operation, which on a stream resets with every token — a node
    configured for 180 seconds could run for ten minutes as long as the tokens
    kept dripping. So the loop also measures its own wall clock and hangs up
    when the node's budget is spent. That is what makes the number an
    administrator sets mean the whole execution rather than the gap between
    two packets.
    """
    api_key = _get_api_key(api_key_secret_ref, api_key_encrypted)
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if top_p is not None:
        payload["top_p"] = float(top_p)
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.perf_counter()
    req = request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        response = request.urlopen(req, timeout=timeout_seconds)
    except error.HTTPError as exc:
        raise_if_shutting_down()
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LlmCallError(f"LLM HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise_if_shutting_down()
        raise LlmCallError(f"LLM stream failed: {exc.reason}") from exc
    except (TimeoutError, ConnectionError) as exc:
        raise_if_shutting_down()
        raise LlmCallError(f"LLM stream timed out after {timeout_seconds}s: {exc!r}") from exc

    try:
        # 关机时这个 response 会被从信号侧关掉，阻塞中的那次读立刻抛错，
        # 于是检查点在几微秒之后而不是几百秒之后。
        with interruptible(response):
            for raw_line in response:
                if time.perf_counter() - started >= timeout_seconds:
                    # 主动断开：`finally` 里的 close 仍会执行。上游还在滴字，
                    # 但这个节点的预算已经花完了。
                    raise LlmCallError(
                        f"LLM stream exceeded the node budget of {timeout_seconds}s"
                    )
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    # provider 偶发的心跳/注释行，跳过而不是终止整个流。
                    continue
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield str(delta)
    except (TimeoutError, ConnectionError) as exc:
        raise_if_shutting_down()
        raise LlmCallError(f"LLM stream dropped after {timeout_seconds}s: {exc!r}") from exc
    except (OSError, ValueError) as exc:
        raise_if_shutting_down()
        raise LlmCallError(f"LLM stream failed: {exc!r}") from exc
    finally:
        response.close()


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
