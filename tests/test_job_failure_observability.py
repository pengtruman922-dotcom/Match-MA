"""失败必须留下痕迹。

回归背景：一次调研任务跑了 15 分 49 秒后失败、重试一次才成功，事后能查到的
只有 attempt_count=2 —— 没有 trace，也没有错误信息。两个原因叠在一起：
读超时抛的是裸 TimeoutError，绕过了调用方写 trace 的 except 分支；而成功又会
把 error_message 清空。
"""

from __future__ import annotations

from urllib import error

import pytest

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.jobs.queue import mark_job_failed, mark_job_succeeded
from backend.app.jobs.retry_policy import is_transient_research_error


class _CaptureDb:
    def __init__(self) -> None:
        self.sql_text = ""
        self.params: dict = {}
        self.committed = False

    def execute(self, statement, params=None):
        self.sql_text = str(statement)
        self.params = params or {}
        return None

    def commit(self) -> None:
        self.committed = True


def _raise_on_urlopen(monkeypatch, exc: BaseException) -> None:
    def _boom(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr("backend.app.ai.llm_client.request.urlopen", _boom)


def _call(*, timeout_seconds: int):
    return call_openai_compatible_chat(
        base_url="https://example.invalid/v1",
        api_key_secret_ref=None,
        model_name="test-model",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.1,
        top_p=0.9,
        max_tokens=None,
        timeout_seconds=timeout_seconds,
    )


def test_read_timeout_becomes_llm_call_error(monkeypatch) -> None:
    _raise_on_urlopen(monkeypatch, TimeoutError("The read operation timed out"))

    with pytest.raises(LlmCallError) as caught:
        _call(timeout_seconds=900)

    # 包起来的目的是让调用方的 except LlmCallError 能接住并写下 failed trace。
    assert "900s" in str(caught.value)
    # 重试判定顺着 __cause__ 链认原始异常，包装不能把它弄丢。
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert is_transient_research_error(caught.value) is True


def test_connection_drop_becomes_llm_call_error(monkeypatch) -> None:
    _raise_on_urlopen(monkeypatch, ConnectionResetError("connection reset by peer"))

    with pytest.raises(LlmCallError) as caught:
        _call(timeout_seconds=60)

    assert is_transient_research_error(caught.value) is True


def test_url_error_still_wraps_as_before(monkeypatch) -> None:
    _raise_on_urlopen(monkeypatch, error.URLError("name resolution failed"))

    with pytest.raises(LlmCallError):
        _call(timeout_seconds=60)


def test_failed_attempt_is_appended_to_failure_history() -> None:
    db = _CaptureDb()

    mark_job_failed(
        db,
        job_id="00000000-0000-0000-0000-000000000001",
        error_message="LLM request timed out or dropped after 900s",
        error_code="llm_call_failed",
    )

    assert "'previous_failures'" in db.sql_text
    assert "coalesce(error_detail_json -> 'previous_failures'" in db.sql_text


def test_success_keeps_the_failure_history_it_would_otherwise_erase() -> None:
    db = _CaptureDb()

    mark_job_succeeded(db, job_id="00000000-0000-0000-0000-000000000001", result_json={})

    # 成功仍然清 error_code / error_message（当前状态确实不是失败），
    # 但历史必须挂住，否则"重试过几次、为什么"就永远查不到了。
    assert "error_message = null" in db.sql_text
    assert "error_detail_json ? 'previous_failures'" in db.sql_text
