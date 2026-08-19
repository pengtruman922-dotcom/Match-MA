"""Graceful shutdown: a deploy must not turn a running turn into a failure.

Before this, `worker.py` had no signal handling at all. Railway sends SIGTERM
then SIGKILL on every deploy, so a job in flight simply vanished — and because
`locked_at` is stamped once at claim time and never refreshed, nothing noticed
until the stale sweep 1800 seconds later. On the agent turn, whose
`max_attempts` is 1, that sweep is a hard failure rather than a retry: the
three `stale_running_job` failures on 2026-08-18 are deploy windows, not slow
models.

The distinction these tests protect is release-versus-fail. A released job goes
back to the queue with its attempt intact and without touching any of the
business-entity failure finalisers, because nothing failed.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.app import shutdown as shutdown_module
from backend.app import worker
from backend.app.jobs.heartbeat import JobHeartbeat
from backend.app.jobs.queue import JobClaim
from backend.app.shutdown import (
    WorkerShutdown,
    raise_if_shutting_down,
    request_shutdown,
    reset_shutdown,
    shutdown_requested,
    wait_for_shutdown,
)

JOB_ID = UUID("00000000-0000-0000-0000-0000000000f1")


@pytest.fixture(autouse=True)
def _clean_shutdown_flag():
    # 进程级全局状态：不清理会漏给下一个用例。
    reset_shutdown()
    yield
    reset_shutdown()


def _agent_job() -> JobClaim:
    return JobClaim(
        id=JOB_ID,
        job_type="recommendation_agent",
        queue_name="llm",
        entity_type="recommendation_session",
        entity_id=uuid4(),
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=1,
    )


# -- the flag ------------------------------------------------------------


def test_raise_if_shutting_down_is_silent_until_a_signal_arrives() -> None:
    raise_if_shutting_down()

    request_shutdown("SIGTERM")

    assert shutdown_requested() is True
    with pytest.raises(WorkerShutdown):
        raise_if_shutting_down()


def test_the_idle_sleep_ends_the_moment_shutdown_is_requested() -> None:
    """time.sleep 会睡满；一个正在空转轮询的 worker 不该让部署多等两秒。"""
    request_shutdown("SIGTERM")

    assert wait_for_shutdown(30.0) is True


def test_the_first_reason_wins_so_the_log_names_the_real_trigger() -> None:
    request_shutdown("SIGTERM")
    request_shutdown("SIGINT")

    assert shutdown_module.shutdown_reason() == "SIGTERM"


# -- run_once: release, do not fail --------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.released: list[tuple[UUID, str]] = []
        self.failed: list[UUID] = []
        self.finalisers: list[str] = []
        self.succeeded: list[UUID] = []

    def install(self, monkeypatch: pytest.MonkeyPatch, *, execute) -> None:
        from contextlib import contextmanager

        @contextmanager
        def fake_scope():
            yield object()

        monkeypatch.setattr(worker, "session_scope", fake_scope)
        monkeypatch.setattr(worker, "requeue_stale_running_jobs", lambda *_a, **_k: 0)
        monkeypatch.setattr(worker, "claim_next_job", lambda *_a, **_k: _agent_job())
        monkeypatch.setattr(worker, "execute_job", execute)
        monkeypatch.setattr(
            worker,
            "mark_job_succeeded",
            lambda *_a, **kwargs: self.succeeded.append(kwargs["job_id"]),
        )
        monkeypatch.setattr(
            worker,
            "mark_job_failed",
            lambda *_a, **kwargs: self.failed.append(kwargs["job_id"]),
        )
        monkeypatch.setattr(
            worker,
            "release_job_for_shutdown",
            lambda *_a, **kwargs: (
                self.released.append((kwargs["job_id"], kwargs["worker_id"])) or "queued"
            ),
        )
        monkeypatch.setattr(
            worker,
            "_finalize_attachment_job_failure",
            lambda *_a, **_k: self.finalisers.append("attachment"),
        )
        monkeypatch.setattr(
            worker,
            "_mark_related_business_update_failed_if_final",
            lambda *_a, **_k: self.finalisers.append("business_update"),
        )


def test_a_shutdown_mid_job_releases_it_without_failing_anything(monkeypatch) -> None:
    recorder = _Recorder()

    def execute(_db, _job):
        raise WorkerShutdown("SIGTERM")

    recorder.install(monkeypatch, execute=execute)

    assert worker.run_once(queue_name="llm", worker_id="worker-1") is True
    assert recorder.released == [(JOB_ID, "worker-1")]
    assert recorder.failed == []
    assert recorder.succeeded == []
    # 释放不是失败：这两个收尾会把附件与业务更新一起判死。
    assert recorder.finalisers == []


def test_an_ordinary_error_still_takes_the_failure_path(monkeypatch) -> None:
    """回归护栏：新增的 except 分支不能把真实失败一起吞成「释放」。"""
    recorder = _Recorder()

    def execute(_db, _job):
        raise RuntimeError("model returned nonsense")

    recorder.install(monkeypatch, execute=execute)

    assert worker.run_once(queue_name="llm", worker_id="worker-1") is True
    assert recorder.failed == [JOB_ID]
    assert recorder.released == []
    assert recorder.finalisers == ["attachment", "business_update"]


def test_the_loop_stops_claiming_once_a_signal_has_arrived(monkeypatch) -> None:
    calls = {"n": 0}

    def run_once(**_kwargs):
        calls["n"] += 1
        request_shutdown("SIGTERM")
        return True

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr(worker, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        ["worker", "--queue", "llm", "--sleep", "0"],
    )

    worker.main()

    assert calls["n"] == 1


# -- heartbeat -----------------------------------------------------------


def test_the_lease_is_refreshed_at_most_once_per_interval() -> None:
    """每个 flush 刷一次租约就是写放大；心跳的价值在于间隔，不在于频率。"""
    now = {"t": 1000.0}
    touched: list[UUID] = []
    heartbeat = JobHeartbeat(
        object(),
        JOB_ID,
        interval_seconds=30.0,
        clock=lambda: now["t"],
        touch=lambda _db, *, job_id: touched.append(job_id),
    )

    assert heartbeat.beat() is False
    now["t"] += 10
    assert heartbeat.beat() is False
    now["t"] += 25
    assert heartbeat.beat() is True
    now["t"] += 1
    assert heartbeat.beat() is False
    assert touched == [JOB_ID]


def test_a_forced_beat_ignores_the_interval() -> None:
    touched: list[UUID] = []
    heartbeat = JobHeartbeat(
        object(),
        JOB_ID,
        clock=lambda: 0.0,
        touch=lambda _db, *, job_id: touched.append(job_id),
    )

    assert heartbeat.beat(force=True) is True
    assert touched == [JOB_ID]


# -- the handler honours the flag ----------------------------------------


def test_the_agent_turn_checkpoint_raises_instead_of_reporting_an_abort(monkeypatch) -> None:
    """停止是用户的决定（终结这一轮），关机是我们的（把 job 还回去）。

    两者共用同一个检查点，所以必须是两种不同的结果，不能都返回 True。
    """
    from backend.app.jobs.handlers import recommendation as handler

    monkeypatch.setattr(handler, "agent_turn_aborted", lambda *_a, **_k: False)
    monkeypatch.setattr(handler, "_resolve_entity_id", lambda *_a, **_k: uuid4())
    monkeypatch.setattr(
        handler,
        "_get_default_node_config",
        lambda *_a, **_k: {"node_name": "n", "base_url": "", "api_key_secret_ref": "",
                           "model_name": "m", "temperature": 0, "top_p": 1,
                           "max_tokens": 10, "timeout_seconds": 30,
                           "response_format": "json_object"},
    )

    def parse(*_a, **_k):
        raise AssertionError("shutdown must be noticed before any model call is paid for")

    monkeypatch.setattr(handler, "parse_recommendation_intent", parse)

    request_shutdown("SIGTERM")
    job = SimpleNamespace(
        id=uuid4(),
        job_type="recommendation_agent",
        payload_json={
            "mode": "buyer_to_target",
            "turn_id": "turn-1",
            "user_message": "制造业",
            "history_context": "",
        },
    )

    with pytest.raises(WorkerShutdown):
        handler._handle_recommendation_agent(object(), job)
