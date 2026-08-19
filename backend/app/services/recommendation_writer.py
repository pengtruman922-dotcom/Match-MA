"""The Writer stage: turn one agent brief into the prose the user gets.

Owned by the worker, not by the browser. Until 2026-08-19 this ran inside the
`/answer-stream` request and persisted only *after* the stream loop finished,
so closing the tab stopped the generator on a `yield` and the whole paid
generation evaporated — the session stayed on a yellow dot forever, and
reopening it silently generated (and billed) the answer a second time.

Now the agent job keeps going after the brief: it streams, flushes the prose to
a draft row every few hundred milliseconds, and writes the answer itself. The
SSE endpoint became a reader of that draft. Nothing about the user-visible
protocol changed.

Two invariants hold the whole thing together:

* **A half-finished draft is never promoted to an answer.** Only a stream that
  ended normally, or a complete rule-built fallback, may write `agent_answer`.
* **Abort wins.** The stop marker is re-checked before every flush and once
  more inside the terminal advisory lock, together with "has someone already
  answered this turn".
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.ai.llm_client import stream_openai_compatible_chat
from backend.app.shutdown import WorkerShutdown
from backend.app.services.recommendation_answer import (
    backfill_target_links,
    build_answer_prompt_variables,
    fallback_answer_markdown,
    sanitize_writer_output,
    target_link_map,
)
from backend.app.services.recommendation_answer_draft import (
    delete_answer_draft,
    upsert_answer_draft,
)
from backend.app.services.recommendation_flow import (
    _touch_recommendation_session,
    insert_agent_answer_message,
)

# 节流：每约 500ms 或约 20 个 delta 落一次草稿。每个 token 提交一次会把一次
# 写作变成几百个事务；反过来攒太久，断连时丢的就不只是几个字。
DRAFT_FLUSH_INTERVAL_SECONDS = 0.5
DRAFT_FLUSH_DELTA_COUNT = 20

# Writer 段的兜底墙钟。`stream_openai_compatible_chat` 的 timeout 是单次读取的
# 超时，一个每 30 秒吐一个字的上游可以永远不触发它。实测 Writer 约 47 秒，
# 所以节点的 timeout_seconds 足够宽松。
#
# 刻意与 AGENT_WALL_CLOCK_BUDGET_SECONDS 分开计时：编排和写作是两段不同的活，
# 混成一个数就没法回答「到底是哪一段慢」。统一超时语义是第三批的事。
DEFAULT_WRITER_BUDGET_SECONDS = 180


class WriterBudgetExceeded(Exception):
    """The stream outlived the Writer own wall clock; fall back to rules."""


@dataclass(frozen=True)
class WriterOutcome:
    status: str            # "answered" | "aborted"
    generation_mode: str   # "llm" | "fallback" | ""
    markdown: str
    message_id: UUID | None
    duration_ms: int
    error_message: str | None = None
    already_existed: bool = False


def _forbidden_ids(link_map: dict[str, Any]) -> list[str]:
    """Flatten the link map values; a repeated target name maps to a list."""
    ids: list[str] = []
    for entry in link_map.values():
        ids.extend(entry if isinstance(entry, list) else [entry])
    return [str(value) for value in ids]


def run_writer_stage(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    brief: dict[str, Any],
    node_config: dict[str, Any] | None,
    render_messages: Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]],
    is_aborted: Callable[[], bool],
    checkpoint: Callable[[], None] | None = None,
    stream_fn: Callable[..., Iterator[str]] = stream_openai_compatible_chat,
    budget_seconds: float | None = None,
    flush_interval_seconds: float = DRAFT_FLUSH_INTERVAL_SECONDS,
    flush_delta_count: int = DRAFT_FLUSH_DELTA_COUNT,
) -> WriterOutcome:
    """Produce and persist this turn answer. Commits as it goes.

    `checkpoint` is the worker interrupt hook: it may raise (WorkerShutdown) to
    abandon the stage without writing anything, which is safe precisely because
    a draft is never promoted.

    `render_messages` is injected rather than imported: prompt rendering lives
    in the jobs layer, and a service reaching back up into `jobs.handlers` both
    inverts the dependency and closes an import cycle through the handlers
    package `__init__`.
    """
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return max(0, int((time.perf_counter() - started) * 1000))

    def discard_draft() -> None:
        delete_answer_draft(db, session_id=session_id, turn_id=turn_id)
        db.commit()

    link_map = target_link_map(brief)
    budget = budget_seconds
    if budget is None:
        budget = float((node_config or {}).get("timeout_seconds") or DEFAULT_WRITER_BUDGET_SECONDS)

    # 上一次运行留下的草稿要先清掉：job 被部署打断后会重排，读者按「已发出多少」
    # 取增量，带着旧草稿续写会让它读到一段前后不接的文本。
    discard_draft()
    if is_aborted():
        return WriterOutcome("aborted", "", "", None, elapsed_ms())

    error_message: str | None = None
    if node_config is None:
        markdown = backfill_target_links(fallback_answer_markdown(brief), link_map)
        generation_mode = "fallback"
    else:
        chunks: list[str] = []
        pending = 0
        last_flush = time.perf_counter()

        def flush() -> bool:
            """Persist the prose so far. False means the turn was stopped."""
            if checkpoint is not None:
                checkpoint()
            if is_aborted():
                return False
            upsert_answer_draft(
                db,
                session_id=session_id,
                turn_id=turn_id,
                markdown="".join(chunks),
            )
            db.commit()
            return True

        try:
            for delta in stream_fn(
                base_url=node_config["base_url"],
                api_key_secret_ref=node_config["api_key_secret_ref"],
                api_key_encrypted=node_config.get("api_key_encrypted"),
                model_name=node_config["model_name"],
                messages=render_messages(node_config, build_answer_prompt_variables(brief)),
                temperature=node_config["temperature"],
                top_p=node_config["top_p"],
                max_tokens=node_config["max_tokens"],
                timeout_seconds=node_config["timeout_seconds"] or 180,
            ):
                chunks.append(delta)
                pending += 1
                now = time.perf_counter()
                if pending >= flush_delta_count or now - last_flush >= flush_interval_seconds:
                    if not flush():
                        discard_draft()
                        return WriterOutcome("aborted", "", "", None, elapsed_ms())
                    pending = 0
                    last_flush = now
                if now - started >= budget:
                    raise WriterBudgetExceeded(
                        f"Writer exceeded its {budget:.0f}s budget after {len(chunks)} chunks."
                    )
        except WorkerShutdown:
            # worker 要停，不是上游写不出来。什么都不写：这一轮的 job 会被放回
            # 队列重跑，而兜底正文一旦落库就再也换不回真正的正文了。
            raise
        except Exception as exc:  # noqa: BLE001 - 生成失败要给出可用兜底，不是空气泡
            # 半截草稿到此为止：它不会变成 answer，规则兜底才会。
            traceback.print_exc()
            error_message = str(exc)
            if is_aborted():
                discard_draft()
                return WriterOutcome("aborted", "", "", None, elapsed_ms())
            markdown = backfill_target_links(fallback_answer_markdown(brief), link_map)
            generation_mode = "fallback"
        else:
            markdown = sanitize_writer_output(
                "".join(chunks),
                forbidden_ids=_forbidden_ids(link_map),
                forbidden_phrases=[str(value) for value in brief.get("follow_up_suggestions") or []],
            )
            if not markdown:
                markdown = fallback_answer_markdown(brief)
                generation_mode = "fallback"
            else:
                generation_mode = "llm"
            # 回填放在落库这一步：流式增量里做替换要处理跨 chunk 的半个名字，
            # 而读者在 done 事件里拿到的就是最终带链接的正文。
            markdown = backfill_target_links(markdown, link_map)

    if checkpoint is not None:
        checkpoint()
    duration_ms = elapsed_ms()
    write = insert_agent_answer_message(
        db,
        session_id=session_id,
        turn_id=turn_id,
        markdown=markdown,
        model_name=(node_config or {}).get("model_name"),
        generation_mode=generation_mode,
        duration_ms=duration_ms,
    )
    if write.status == "aborted":
        discard_draft()
        return WriterOutcome("aborted", "", "", None, duration_ms)
    if write.status == "inserted":
        _touch_recommendation_session(db, session_id)
    delete_answer_draft(db, session_id=session_id, turn_id=turn_id)
    db.commit()
    return WriterOutcome(
        status="answered",
        generation_mode=generation_mode,
        markdown=markdown,
        message_id=write.message_id,
        duration_ms=duration_ms,
        error_message=error_message,
        already_existed=write.status == "already_exists",
    )
