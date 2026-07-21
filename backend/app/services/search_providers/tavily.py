"""Tavily adapter.

Uses urllib rather than a HTTP client library to match ai/llm_client.py — httpx
is only a dev dependency here, and outbound calls in this codebase go through
the standard library.
"""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from backend.app.services.search_providers.base import (
    SearchError,
    SearchHit,
    SearchRequest,
)


class TavilyAdapter:
    name = "tavily"

    def search(
        self,
        search_request: SearchRequest,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
        extra_config: dict[str, Any],
    ) -> list[SearchHit]:
        payload: dict[str, Any] = {
            "query": search_request.query,
            "max_results": int(extra_config.get("max_results") or search_request.max_results),
            "search_depth": str(extra_config.get("search_depth") or search_request.search_depth),
            "include_raw_content": bool(
                extra_config.get("include_raw_content", search_request.include_raw_content)
            ),
        }
        for key in ("include_domains", "exclude_domains", "topic", "days"):
            if extra_config.get(key) is not None:
                payload[key] = extra_config[key]
        payload.update(search_request.extra)

        endpoint = base_url.rstrip("/") + "/search"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise SearchError(f"Tavily HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise SearchError(f"Tavily request failed: {exc.reason}") from exc

        try:
            data = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise SearchError(f"Tavily response is not valid JSON: {response_body[:300]}") from exc

        results = data.get("results")
        if not isinstance(results, list):
            raise SearchError("Tavily response has no results array.")
        return [hit for hit in (self._to_hit(item) for item in results) if hit is not None]

    def _to_hit(self, item: Any) -> SearchHit | None:
        if not isinstance(item, dict):
            return None
        url_value = str(item.get("url") or "").strip()
        if not url_value:
            return None
        raw_content = item.get("raw_content")
        return SearchHit(
            url=url_value,
            title=str(item.get("title") or "").strip(),
            snippet=str(item.get("content") or "").strip(),
            raw_content=(str(raw_content).strip() or None) if raw_content else None,
            published_at=str(item.get("published_date") or "").strip() or None,
            score=float(item["score"]) if isinstance(item.get("score"), (int, float)) else None,
            provider=self.name,
        )
