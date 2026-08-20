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
    interruptible,
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
        # 真的 JobClaim 有这个字段。替身缺字段 = 把「调用方读了个不存在的属性」
        # 这种错误推迟到生产才发现。
        correlation_id=uuid4(),
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


# -- the in-flight teardown ----------------------------------------------
#
# 2026-08-19 自建环境实测暴露的一条：信号处理是对的、标志位也置上了，但释放要等到
# 一个检查点，而检查点只存在于模型/工具调用之间（实测间隔 5~185 秒），容器只给
# 10 秒宽限。SIGTERM 落在一次长模型调用中间 = SIGKILL，job 照样挂满 1800 秒。
# 所以关机还必须把在途的 HTTP 响应拆掉，让阻塞中的读立刻抛错。


class _FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_shutdown_tears_down_whatever_request_is_in_flight() -> None:
    response = _FakeResponse()

    with interruptible(response):
        assert response.closed is False
        request_shutdown("SIGTERM")
        assert response.closed is True


def test_a_finished_request_is_not_closed_later() -> None:
    """注册要随调用结束解除，否则关机会去关一个早就还给连接池的对象。"""
    response = _FakeResponse()

    with interruptible(response):
        pass

    request_shutdown("SIGTERM")

    assert response.closed is False


def test_no_new_model_call_starts_once_shutdown_is_under_way() -> None:
    """已经在关机了还去付一次模型调用的钱，等于白花。"""
    request_shutdown("SIGTERM")

    with pytest.raises(WorkerShutdown):
        with interruptible(_FakeResponse()):
            raise AssertionError("the body must not run")


def test_closing_one_response_cannot_stop_the_others_from_closing() -> None:
    class _Angry(_FakeResponse):
        def close(self) -> None:
            raise RuntimeError("already detached")

    good = _FakeResponse()
    with interruptible(_Angry()), interruptible(good):
        request_shutdown("SIGTERM")

    assert good.closed is True


def _stream_response(monkeypatch, lines):
    """A urlopen whose read blocks until the test closes it, like a real one."""

    class _Blocking:
        def __init__(self) -> None:
            self.closed = False

        def __iter__(self):
            for line in lines:
                if self.closed:
                    raise ValueError("read of closed file")
                yield line

        def close(self) -> None:
            self.closed = True

    response = _Blocking()
    monkeypatch.setattr(
        "backend.app.ai.llm_client.request.urlopen",
        lambda *args, **kwargs: response,
    )
    return response


def test_a_shutdown_mid_stream_surfaces_as_shutdown_not_as_a_model_failure(monkeypatch) -> None:
    """这是整条链路的关键分辨：同一个 OSError，两种完全相反的处置。

    普通失败 → 这一轮判失败；关机 → job 放回队列且不消耗 attempts。认错了的话，
    优雅退出就变成了「每次部署都判死一轮推荐」。
    """
    from backend.app.ai.llm_client import stream_openai_compatible_chat

    _stream_response(monkeypatch, [
        b'data: {"choices":[{"delta":{"content":"first"}}]}',
        b'data: {"choices":[{"delta":{"content":"second"}}]}',
    ])

    stream = stream_openai_compatible_chat(
        base_url="https://example.test/v1",
        api_key_secret_ref=None,
        model_name="m",
        messages=[],
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )
    assert next(stream)  # 第一个 delta 正常拿到
    request_shutdown("SIGTERM")

    with pytest.raises(WorkerShutdown):
        next(stream)


def test_an_ordinary_dropped_stream_is_still_a_model_failure(monkeypatch) -> None:
    from backend.app.ai.llm_client import LlmCallError, stream_openai_compatible_chat

    class _Broken:
        def __iter__(self):
            raise OSError("connection reset by peer")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "backend.app.ai.llm_client.request.urlopen",
        lambda *args, **kwargs: _Broken(),
    )

    stream = stream_openai_compatible_chat(
        base_url="https://example.test/v1",
        api_key_secret_ref=None,
        model_name="m",
        messages=[],
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )

    with pytest.raises(LlmCallError):
        next(stream)


def test_a_tool_that_hits_shutdown_does_not_report_itself_as_a_failed_tool(monkeypatch) -> None:
    """深评是在工具里调模型的，关机必须穿透工具循环而不是变成一行 error 回给模型。"""
    from backend.app.ai.llm_client import ToolCall
    from backend.app.ai.tool_loop import _tool_result_content

    call = ToolCall(id="1", name="deep_evaluate_candidates", arguments={}, raw_arguments="{}")

    def explode(_call):
        raise WorkerShutdown("SIGTERM")

    with pytest.raises(WorkerShutdown):
        _tool_result_content(call, explode, 8000)


def test_an_ordinary_tool_failure_still_goes_back_to_the_model() -> None:
    from backend.app.ai.llm_client import ToolCall
    from backend.app.ai.tool_loop import _tool_result_content

    call = ToolCall(id="1", name="search_targets", arguments={}, raw_arguments="{}")

    def explode(_call):
        raise ValueError("bad filter")

    assert "bad filter" in _tool_result_content(call, explode, 8000)
