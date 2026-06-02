from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class EmbeddingCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingResult:
    embedding: list[float]
    prompt_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    raw_response_json: dict[str, Any]


def call_openai_compatible_embedding(
    *,
    base_url: str,
    api_key_secret_ref: str | None,
    model_name: str,
    input_text: str,
    dimensions: int | None,
    timeout_seconds: int,
) -> EmbeddingResult:
    api_key = _get_api_key(api_key_secret_ref)
    endpoint = base_url.rstrip("/") + "/embeddings"
    payload: dict[str, Any] = {
        "model": model_name,
        "input": input_text,
    }
    if dimensions is not None:
        payload["dimensions"] = int(dimensions)

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
        raise EmbeddingCallError(f"Embedding HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise EmbeddingCallError(f"Embedding request failed: {exc.reason}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        response_json = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise EmbeddingCallError(f"Embedding response is not valid JSON: {response_body[:500]}") from exc

    try:
        raw_embedding = response_json["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        message = f"Embedding response missing data[0].embedding: {response_body[:500]}"
        raise EmbeddingCallError(message) from exc

    if not isinstance(raw_embedding, list) or not all(isinstance(item, int | float) for item in raw_embedding):
        raise EmbeddingCallError("Embedding response is not a numeric vector.")

    embedding = [float(item) for item in raw_embedding]
    if dimensions is not None and len(embedding) != int(dimensions):
        raise EmbeddingCallError(
            f"Embedding dimension mismatch: expected {dimensions}, got {len(embedding)}."
        )

    usage = response_json.get("usage") or {}
    return EmbeddingResult(
        embedding=embedding,
        prompt_tokens=_optional_int(usage.get("prompt_tokens")),
        total_tokens=_optional_int(usage.get("total_tokens")),
        latency_ms=latency_ms,
        raw_response_json=response_json,
    )


def embedding_to_pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(_format_float(value) for value in embedding) + "]"


def _get_api_key(api_key_secret_ref: str | None) -> str | None:
    if not api_key_secret_ref:
        return None
    api_key = os.getenv(api_key_secret_ref)
    if not api_key:
        raise EmbeddingCallError(f"Environment variable is not configured: {api_key_secret_ref}")
    return api_key


def _format_float(value: float) -> str:
    return format(float(value), ".10g")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
