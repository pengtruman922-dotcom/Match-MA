"""Search adapter contract.

Adapters translate one search API into a common result shape. Everything above
this layer — the research loop, anchor validation, proposal building — works on
SearchHit alone, so adding Serper or Bing means adding a file here rather than
touching the research flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    # Full page text when the provider returns it; the research loop falls back
    # to its own fetch for high-value sources that come back thin.
    raw_content: str | None = None
    published_at: str | None = None
    score: float | None = None
    provider: str = ""

    def evidence_text(self) -> str:
        """The text anchor validation and extraction actually read."""
        return "\n".join(part for part in (self.title, self.snippet, self.raw_content or "") if part)


@dataclass
class SearchRequest:
    query: str
    max_results: int = 8
    include_raw_content: bool = True
    search_depth: str = "advanced"
    extra: dict[str, Any] = field(default_factory=dict)


class SearchError(RuntimeError):
    pass


class SearchAdapter(Protocol):
    name: str

    def search(
        self,
        request: SearchRequest,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
        extra_config: dict[str, Any],
    ) -> list[SearchHit]:
        ...
