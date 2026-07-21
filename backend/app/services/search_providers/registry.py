"""Adapter lookup: provider row -> adapter implementation."""

from __future__ import annotations

from backend.app.services.search_providers.base import SearchAdapter, SearchError
from backend.app.services.search_providers.tavily import TavilyAdapter

_ADAPTERS: dict[str, SearchAdapter] = {
    TavilyAdapter.name: TavilyAdapter(),
}


def available_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(name: str) -> SearchAdapter:
    adapter = _ADAPTERS.get((name or "").strip().lower())
    if adapter is None:
        raise SearchError(
            f"Unknown search adapter: {name!r}. Available: {', '.join(available_adapters())}"
        )
    return adapter
