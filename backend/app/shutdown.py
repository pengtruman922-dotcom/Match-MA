"""Cooperative shutdown for the background worker.

Railway sends SIGTERM and then SIGKILL on every deploy. Without a handler the
process simply disappears mid-job, and nothing notices: `locked_at` is written
once when the job is claimed (`queue.claim_next_job`) and never refreshed, so
the only thing that ever reclaims it is the stale sweep — 1800 seconds later on
the llm queue. For `recommendation_agent`, whose `max_attempts` is 1, that
sweep is not a retry but a hard failure of a turn the user sat watching.

The 3 `stale_running_job` failures on 2026-08-18 are this, not slow models: the
agent's own wall-clock budget is 240s and a single call tops out at the node
timeout, so nothing in that job can legitimately reach 1800 seconds.

Lives beside `worker.py` rather than under `jobs/` so that anything reaching a
checkpoint can import it. `backend.app.jobs.__init__` pulls in the whole
handlers package, so an import from there closes a cycle for every service the
handlers themselves use — the Writer being the first one to need it.

Two halves, deliberately separate:

* between jobs — the loop simply stops claiming, which needs no cooperation
  from any handler and covers every queue;
* inside a job — handlers that call `raise_if_shutting_down` at a checkpoint
  raise `WorkerShutdown`, and the worker hands that job **back** to the queue.

A checkpoint is only useful if the process reaches one before SIGKILL. It does
not, on its own: checkpoints sit *between* model and tool calls, and 2026-08-19
measurements on the self-hosted stack put those 5 to 185 seconds apart while
Docker allows 10 seconds and Railway a similar order. A SIGTERM landing inside
a model call therefore used to be a SIGKILL, and the job hung until the stale
sweep — the very failure this module exists to prevent.

So the shutdown also **tears down whatever HTTP response is in flight**
(`interruptible`). The blocked read raises at once, the next checkpoint is
microseconds away, and the release happens in the grace period instead of
thirty minutes later.

Handing back is not failing. A released job keeps its attempt (see
`queue.release_job_for_shutdown`) because being interrupted by our own deploy
is not one of the chances the user gets.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

# Module-level rather than passed around: signal handlers have no argument of
# their own, and a worker process consumes exactly one queue.
_shutdown = threading.Event()
_reason = ""
_signal_count = 0

# Reentrant on purpose. The signal handler runs *in the thread that was
# interrupted*, which may be the very thread holding this lock to register a
# response. A plain Lock would deadlock the handler against itself.
_in_flight_lock = threading.RLock()
_in_flight: set[Any] = set()


class _Closeable(Protocol):
    def close(self) -> None: ...


@contextmanager
def interruptible(closeable: _Closeable) -> Iterator[None]:
    """Expose a live HTTP response so a shutdown can tear it down mid-read.

    CPython's signal handling is what makes this work: a blocking socket read
    is interrupted by the signal, the handler runs (closing the file
    descriptor), and PEP 475 then retries the read — which now fails on a
    closed socket. The caller sees an ordinary exception a few microseconds
    after the signal instead of blocking for the rest of the model's timeout.

    Refuses to start at all once shutdown is under way: paying for a model call
    whose result is about to be thrown away is the same waste as letting it run.
    """
    raise_if_shutting_down()
    with _in_flight_lock:
        _in_flight.add(closeable)
    try:
        yield
    finally:
        with _in_flight_lock:
            _in_flight.discard(closeable)


def _close_in_flight() -> None:
    with _in_flight_lock:
        pending = list(_in_flight)
        _in_flight.clear()
    for closeable in pending:
        try:
            closeable.close()
        except Exception:  # noqa: BLE001 - 关机路上不能再抛
            pass
    if pending:
        print(f"Closed {len(pending)} in-flight request(s) on shutdown.",
              file=sys.stderr, flush=True)


class WorkerShutdown(Exception):
    """Raised at a handler checkpoint so the job is released, not failed.

    Never caught by the ordinary `except Exception` failure path in
    `worker.run_once` — that path marks the job failed and runs the failure
    finalisers, which is exactly the wrong outcome for a deploy restart.
    """


def request_shutdown(reason: str) -> None:
    global _reason
    if not _shutdown.is_set():
        _reason = reason
        _shutdown.set()
        print(f"Worker shutdown requested ({reason}); finishing at the next checkpoint.",
              file=sys.stderr, flush=True)
        # 顺序要紧：先置标志再拆连接，这样被打断的读抬头看到的一定是
        # 「在关机」而不是「网络抖了一下」。
        _close_in_flight()


def shutdown_requested() -> bool:
    return _shutdown.is_set()


def shutdown_reason() -> str:
    return _reason


def raise_if_shutting_down() -> None:
    """Checkpoint for long handlers. Cheap enough to call in a stream loop."""
    if _shutdown.is_set():
        raise WorkerShutdown(_reason or "shutdown requested")


def wait_for_shutdown(timeout: float) -> bool:
    """Sleep that a signal cuts short, so idle polling exits immediately."""
    return _shutdown.wait(timeout)


def reset_shutdown() -> None:
    """Test hook. Process state is global; tests must not leak it to each other."""
    global _reason, _signal_count
    _shutdown.clear()
    _reason = ""
    _signal_count = 0
    with _in_flight_lock:
        _in_flight.clear()


def install_signal_handlers() -> None:
    """Arm SIGTERM/SIGINT. Only valid from the main thread, which `main()` is."""

    def handle(signum: int, _frame: object) -> None:
        global _signal_count
        _signal_count += 1
        if _signal_count > 1:
            # A second signal means the sender is not willing to wait. Restore
            # the default disposition and let it do what it would have done.
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
            return
        request_shutdown(signal.Signals(signum).name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handle)
