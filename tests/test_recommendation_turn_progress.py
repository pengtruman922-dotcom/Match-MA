"""The two backend additions the second batch needs: retry and one-shot progress.

Both exist to break the same chain. The page used to decide on its own that a
turn had failed (301 ticks ≈ 361s, while a real production turn took 376.8s and
was killed by it), show a retry button, and let the user start a second billed
agent run alongside the first one that was still working.

So: the server is the only thing that may call a turn failed, and a retry is
refused outright while the original is still alive.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.routes import recommendations as route

SESSION_ID = UUID("00000000-0000-0000-0000-0000000000b1")
TURN_ID = "turn-1"


def _user(is_admin: bool = False):
    return SimpleNamespace(user_id=uuid4(), is_admin=is_admin)


def _message(message_type: str, turn_id: str = TURN_ID, content: str = "{}") -> dict:
    return {
        "id": uuid4(),
        "role": "tool",
        "content": content,
        "content_type": "json",
        "metadata_json": {"message_type": message_type, "turn_id": turn_id},
    }


def _install(monkeypatch, *, job_status="running", messages=None):
    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_a, **_k: None)
    monkeypatch.setattr(route, "_get_recommendation_session_or_404", lambda *_a, **_k: {})
    monkeypatch.setattr(
        route,
        "find_agent_turn_job",
        lambda *_a, **_k: None if job_status == "missing" else {
            "status": job_status,
            "error_code": "stale_running_job" if job_status == "failed" else None,
            "error_message": "Running job exceeded stale lock timeout.",
        },
    )
    monkeypatch.setattr(
        route,
        "_list_recommendation_messages",
        lambda *_a, **_k: messages if messages is not None else [],
    )


def _progress(monkeypatch, **kwargs):
    _install(monkeypatch, **kwargs)
    return route.get_recommendation_agent_turn_progress(
        SESSION_ID, TURN_ID, current_user=_user(), db=object()
    )


# -- progress: one request instead of two --------------------------------


def test_progress_reports_a_running_turn_without_calling_it_failed(monkeypatch) -> None:
    body = _progress(
        monkeypatch,
        job_status="running",
        messages=[_message("agent_understanding"), _message("agent_step")],
    )

    assert body["job_status"] == "running"
    assert body["failed"] is False
    assert body["error_message"] is None
    assert len(body["messages"]) == 2


def test_progress_carries_the_turns_messages_so_one_request_is_enough(monkeypatch) -> None:
    """两个请求合并成一个，顺带消掉「两次读取相隔一瞬而互相矛盾」的窗口。"""
    body = _progress(
        monkeypatch,
        job_status="succeeded",
        messages=[
            _message("agent_step"),
            _message("agent_brief"),
            _message("agent_answer"),
            _message("agent_step", turn_id="another-turn"),
        ],
    )

    assert body["has_brief"] is True
    assert body["has_answer"] is True
    assert body["has_question"] is False
    # 别的轮次不能混进来。
    assert len(body["messages"]) == 3


def test_progress_reports_a_stop_written_by_another_tab(monkeypatch) -> None:
    body = _progress(monkeypatch, job_status="succeeded", messages=[_message("agent_aborted")])

    assert body["aborted"] is True
    assert body["failed"] is False


def test_only_the_backend_gets_to_say_a_turn_failed(monkeypatch) -> None:
    body = _progress(monkeypatch, job_status="failed", messages=[_message("agent_step")])

    assert body["failed"] is True
    assert body["error_code"] == "stale_running_job"
    assert "回收" in body["error_message"]


def test_the_raw_error_stays_with_the_admin(monkeypatch) -> None:
    _install(monkeypatch, job_status="failed", messages=[])

    consultant = route.get_recommendation_agent_turn_progress(
        SESSION_ID, TURN_ID, current_user=_user(is_admin=False), db=object()
    )
    admin = route.get_recommendation_agent_turn_progress(
        SESSION_ID, TURN_ID, current_user=_user(is_admin=True), db=object()
    )

    assert consultant["error_detail"] is None
    assert "stale lock" in admin["error_detail"]


def test_a_turn_whose_job_row_is_gone_is_not_silently_running(monkeypatch) -> None:
    body = _progress(monkeypatch, job_status="missing", messages=[])

    assert body["job_status"] == "missing"
    assert body["failed"] is False


# -- retry: never start a second paid run alongside a live one -----------


def _retry_guard(monkeypatch, *, job_status: str, aborted: bool = False):
    monkeypatch.setattr(route, "agent_turn_aborted", lambda *_a, **_k: aborted)
    monkeypatch.setattr(
        route,
        "find_agent_turn_job",
        lambda *_a, **_k: None if job_status == "missing" else {"status": job_status},
    )
    return route._reject_retry_of_a_live_turn(object(), SESSION_ID, TURN_ID)


@pytest.mark.parametrize("job_status", ["queued", "retry_waiting", "running"])
def test_retrying_a_turn_that_is_still_alive_is_refused(monkeypatch, job_status) -> None:
    """假失败 → 用户重试 → 并发开第二个付费任务，这条链子在这里被切断。"""
    with pytest.raises(HTTPException) as raised:
        _retry_guard(monkeypatch, job_status=job_status)

    assert raised.value.status_code == 409
    assert job_status in raised.value.detail


@pytest.mark.parametrize("job_status", ["failed", "cancelled", "succeeded", "missing"])
def test_retrying_a_turn_that_actually_ended_is_allowed(monkeypatch, job_status) -> None:
    assert _retry_guard(monkeypatch, job_status=job_status) is None


def test_a_stopped_turn_may_be_retried_even_while_its_job_winds_down(monkeypatch) -> None:
    """中止是用户自己的决定，标记一写就是终态，不必等 job 收尾。"""
    assert _retry_guard(monkeypatch, job_status="running", aborted=True) is None


def test_retry_marker_is_optional_and_absent_by_default() -> None:
    plain = route.RecommendationAgentTurnRequest(mode="buyer_to_target", user_message="找标的")
    retry = route.RecommendationAgentTurnRequest(
        mode="buyer_to_target", user_message="找标的", retry_of_turn_id=TURN_ID
    )

    assert plain.retry_of_turn_id is None
    assert retry.retry_of_turn_id == TURN_ID


def test_a_retry_without_its_session_is_rejected(monkeypatch) -> None:
    """没有会话就没有「哪一轮」可重试；放过去会新建一个会话冒充重试。"""
    payload = route.RecommendationAgentTurnRequest(
        mode="buyer_to_target", user_message="找标的", retry_of_turn_id=TURN_ID
    )

    with pytest.raises(HTTPException) as raised:
        route.create_recommendation_agent_turn(payload, current_user=_user(), db=object())

    assert raised.value.status_code == 400
