"""Narrow retry rules for expensive research jobs.

The generic worker historically retries every failed job up to max_attempts.
That is acceptable for cheap/idempotent tasks, but a research attempt can use
several searches and LLM calls.  Only failures that are likely to disappear on
their own may replay the whole run.
"""

from __future__ import annotations

import re
from urllib import error

from backend.app.jobs.queue import JobClaim

RESEARCH_JOB_TYPES = frozenset({"seller_target_research", "seller_target_research_map"})
_TRANSIENT_HTTP_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "temporary failure",
    "connection reset",
    "connection refused",
    "remote end closed",
    "service unavailable",
    "too many requests",
    "rate limit",
)


def is_transient_research_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, ConnectionError, error.URLError)):
            return True
        message = str(current).lower()
        match = re.search(r"(?:llm\s+)?http\s+(\d{3})", message)
        if match and int(match.group(1)) in _TRANSIENT_HTTP_CODES:
            return True
        if any(marker in message for marker in _TRANSIENT_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def research_failure_is_final(job: JobClaim, exc: BaseException) -> bool:
    return job.attempt_count >= job.max_attempts or not is_transient_research_error(exc)
