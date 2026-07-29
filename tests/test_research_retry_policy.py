from backend.app.ai.llm_client import LlmCallError
from backend.app.jobs.retry_policy import is_transient_research_error


def test_only_transient_research_errors_are_retried() -> None:
    assert is_transient_research_error(LlmCallError("LLM HTTP 429: rate limit"))
    assert is_transient_research_error(LlmCallError("LLM HTTP 503: service unavailable"))
    assert is_transient_research_error(LlmCallError("LLM request failed: timed out"))

    assert not is_transient_research_error(LlmCallError("LLM HTTP 400: invalid prompt"))
    assert not is_transient_research_error(ValueError("Research output is not a JSON object"))
    assert not is_transient_research_error(RuntimeError("programming error"))


def test_transient_cause_is_detected_through_wrapping() -> None:
    try:
        try:
            raise LlmCallError("LLM HTTP 502: bad gateway")
        except LlmCallError as exc:
            raise ValueError("research failed") from exc
    except ValueError as wrapped:
        assert is_transient_research_error(wrapped)
