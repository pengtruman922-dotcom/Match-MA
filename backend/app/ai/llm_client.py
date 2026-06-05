from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class LlmCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatCompletionResult:
    raw_output_text: str
    parsed_output_json: dict[str, Any] | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: int


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
    response_format: str | None = None,
) -> ChatCompletionResult:
    api_key = _get_api_key(api_key_secret_ref)
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
    if response_format == "json_object":
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

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        response_json = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LlmCallError(f"LLM response is not valid JSON: {response_body[:500]}") from exc

    try:
        raw_output_text = response_json["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        message = f"LLM response missing choices[0].message.content: {response_body[:500]}"
        raise LlmCallError(message) from exc

    usage = response_json.get("usage") or {}
    parsed_output_json = _parse_json_object(raw_output_text)
    return ChatCompletionResult(
        raw_output_text=raw_output_text,
        parsed_output_json=parsed_output_json,
        prompt_tokens=_optional_int(usage.get("prompt_tokens")),
        completion_tokens=_optional_int(usage.get("completion_tokens")),
        total_tokens=_optional_int(usage.get("total_tokens")),
        latency_ms=latency_ms,
    )


def _get_api_key(api_key_secret_ref: str | None) -> str | None:
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
