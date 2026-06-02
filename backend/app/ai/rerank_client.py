from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class RerankCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class RerankItem:
    index: int
    relevance_score: float


@dataclass(frozen=True)
class RerankResult:
    results: list[RerankItem]
    raw_response_json: dict[str, Any]
    model_name: str
    latency_ms: int
    total_tokens: int | None


def call_dashscope_compatible_rerank(
    *,
    base_url: str,
    api_key_secret_ref: str | None,
    model_name: str,
    query: str,
    documents: list[str],
    top_n: int | None = None,
    instruct: str | None = None,
    timeout_seconds: int = 60,
) -> RerankResult:
    if not query.strip():
        raise RerankCallError("Rerank query is empty.")
    if not documents:
        raise RerankCallError("Rerank documents are empty.")

    api_key = _get_api_key(api_key_secret_ref)
    endpoint = _rerank_endpoint(base_url)
    payload: dict[str, Any] = {
        "model": model_name,
        "query": query,
        "documents": documents,
    }
    if top_n is not None:
        payload["top_n"] = int(top_n)
    if instruct:
        payload["instruct"] = instruct

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
        raise RerankCallError(f"Rerank HTTP {exc.code}: {error_body}") from exc
    except error.URLError as exc:
        raise RerankCallError(f"Rerank request failed: {exc.reason}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        response_json = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RerankCallError(f"Rerank response is not valid JSON: {response_body[:500]}") from exc

    raw_results = response_json.get("results")
    if not isinstance(raw_results, list):
        raise RerankCallError(f"Rerank response missing results array: {response_body[:500]}")

    results: list[RerankItem] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        try:
            results.append(
                RerankItem(
                    index=int(item["index"]),
                    relevance_score=float(item["relevance_score"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not results:
        raise RerankCallError(f"Rerank response contains no usable results: {response_body[:500]}")

    usage = response_json.get("usage") or {}
    return RerankResult(
        results=results,
        raw_response_json=response_json,
        model_name=str(response_json.get("model") or model_name),
        latency_ms=latency_ms,
        total_tokens=_optional_int(usage.get("total_tokens")),
    )


def _rerank_endpoint(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/reranks"):
        return cleaned
    return cleaned + "/reranks"


def _get_api_key(api_key_secret_ref: str | None) -> str | None:
    if not api_key_secret_ref:
        return None
    api_key = os.getenv(api_key_secret_ref)
    if not api_key:
        raise RerankCallError(f"Environment variable is not configured: {api_key_secret_ref}")
    return api_key


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
