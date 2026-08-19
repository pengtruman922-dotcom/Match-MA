"""Keep a long-running job's lease fresh while it works.

The stale sweep reclaims jobs whose `locked_at` is older than the queue's
window. That timestamp is written once at claim time, so before this the sweep
was really asking "when was this claimed", and the only safe answer was a very
large window (1800s on the llm queue) — which is also how long a job whose
worker died stayed invisible.

Throttled on purpose: a Writer flushes prose every ~500ms and the agent commits
after every tool step, and a lease refresh per progress write would be a write
amplification with no information in it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.jobs.queue import touch_running_job

HEARTBEAT_INTERVAL_SECONDS = 30.0


class JobHeartbeat:
    """Refresh `background_job.locked_at`, at most once per interval.

    `beat()` does not commit. Callers pair it with the inline commit they were
    making anyway, so the lease lands in the same transaction as the progress
    it vouches for — a heartbeat that outlived its own rollback would be a lie.
    """

    def __init__(
        self,
        db: Session,
        job_id: UUID,
        *,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        touch: Callable[..., bool] = touch_running_job,
    ) -> None:
        self._db = db
        self._job_id = job_id
        self._interval = interval_seconds
        self._clock = clock
        self._touch = touch
        self._last_beat = clock()

    def beat(self, *, force: bool = False) -> bool:
        """Emit a lease refresh if the interval has elapsed. True if it did."""
        now = self._clock()
        if not force and now - self._last_beat < self._interval:
            return False
        self._last_beat = now
        self._touch(self._db, job_id=self._job_id)
        return True
