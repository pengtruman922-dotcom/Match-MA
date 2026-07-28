"""What the target list shows about a target's state.

Two orthogonal things, deliberately kept apart after 施工单 0727:

- **交易状态** (`lifecycle_status`): 在售中 / 已售出 / 已停售. Human-owned, edited
  from the detail page, and the only thing recommendation screening reads.
- **AI 处理进度**: whether the consultant's last asynchronous request actually
  ran. Two pipelines feed it — 解析 (`information_status`) and 调研
  (`last_research_at` / `research_last_outcome`) — and they collapse into one
  column because only one of them is ever in flight at a time.

The retired `recommendation_status` used to answer both questions and neither
well: it gated recommendation *and* drove the list's "已解析/未解析" badge, so a
target whose facts were written outside the narrow promotion window stayed
invisible to recommendation while displaying as unparsed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

AI_PROCESSING_PARSING = "parsing"
AI_PROCESSING_RESEARCHING = "researching"
AI_PROCESSING_PARSE_FAILED = "parse_failed"
AI_PROCESSING_RESEARCH_FAILED = "research_failed"
AI_PROCESSING_COMPLETED = "completed"
AI_PROCESSING_NEVER = "never"

AI_PROCESSING_STATES: tuple[str, ...] = (
    AI_PROCESSING_PARSING,
    AI_PROCESSING_RESEARCHING,
    AI_PROCESSING_PARSE_FAILED,
    AI_PROCESSING_RESEARCH_FAILED,
    AI_PROCESSING_COMPLETED,
    AI_PROCESSING_NEVER,
)

# information_status values that mean "no parse has ever completed here".
_UNPROCESSED_INFORMATION_STATUSES = frozenset({"insufficient", ""})

# Statuses set while a pipeline is running.
_IN_FLIGHT = {
    "parsing": AI_PROCESSING_PARSING,
    "researching": AI_PROCESSING_RESEARCHING,
}


class AIProcessingBusyError(RuntimeError):
    """The target is already owned by the other asynchronous AI pipeline."""

    def __init__(self, current_status: str) -> None:
        self.current_status = current_status
        label = "解析" if current_status == "parsing" else "调研"
        super().__init__(f"该标的正在{label}中，请等待当前任务完成后再试。")


def acquire_ai_processing(
    db: Session,
    *,
    seller_target_id: UUID,
    desired_status: str,
    actor_user_id: UUID,
) -> None:
    """Atomically reserve a target for parse or research before enqueueing.

    The update and job insert share one transaction.  A failed reservation
    therefore cannot leave a queued job whose visible state was never set.
    """
    if desired_status not in _IN_FLIGHT:
        raise ValueError(f"Unsupported AI processing status: {desired_status}")
    acquired = db.execute(
        text(
            """
            update seller_target
            set information_status = :desired_status,
                updated_at = now(),
                updated_by = :updated_by
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and information_status not in ('parsing', 'researching')
            returning information_status
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "desired_status": desired_status,
            "updated_by": actor_user_id,
        },
    ).scalar_one_or_none()
    if acquired is not None:
        return
    current_status = db.execute(
        text(
            """
            select information_status
            from seller_target
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one_or_none()
    raise AIProcessingBusyError(str(current_status or "processing"))


def mark_parse_completed(
    db: Session,
    *,
    seller_target_id: UUID,
    actor_user_id: UUID,
) -> None:
    """Timestamp a successful parse and release its in-flight state if needed."""
    db.execute(
        text(
            """
            update seller_target
            set last_parse_at = now(),
                information_status = case
                  when information_status = 'parsing' then 'normal'
                  else information_status
                end,
                updated_at = now(),
                updated_by = :updated_by
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "updated_by": actor_user_id,
        },
    )


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ai_processing_state(target: Mapping[str, Any]) -> str:
    """Collapse both AI pipelines into the one state the list renders.

    Priority is "what is happening now" > "what just broke" > "what finished".
    A finished-but-empty research run (`no_public_information`) counts as
    completed: the run itself worked, so the consultant's action did take
    effect — reporting it as a failure would send them to retry for nothing.
    """
    information_status = str(target.get("information_status") or "")
    in_flight = _IN_FLIGHT.get(information_status)
    if in_flight:
        return in_flight
    parse_at = _as_datetime(target.get("last_parse_at"))
    research_at = _as_datetime(target.get("last_research_at"))
    research_outcome = str(target.get("research_last_outcome") or "")

    # Once both timestamps exist, the newest completed operation owns the
    # badge.  This prevents an old parse failure from masking a later successful
    # research run (and vice versa).
    if parse_at is not None or research_at is not None:
        if parse_at is not None and (research_at is None or parse_at >= research_at):
            return (
                AI_PROCESSING_PARSE_FAILED
                if information_status == "parse_failed"
                else AI_PROCESSING_COMPLETED
            )
        return (
            AI_PROCESSING_RESEARCH_FAILED
            if research_outcome == "failed"
            else AI_PROCESSING_COMPLETED
        )

    # Legacy rows predate last_parse_at.  Preserve their observable state until
    # they run either pipeline once under the new model.
    if information_status == "parse_failed":
        return AI_PROCESSING_PARSE_FAILED
    if research_outcome == "failed":
        return AI_PROCESSING_RESEARCH_FAILED

    researched = bool(target.get("last_research_at"))
    parsed = information_status not in _UNPROCESSED_INFORMATION_STATUSES
    if parsed or researched:
        return AI_PROCESSING_COMPLETED
    return AI_PROCESSING_NEVER


_AI_PROCESSING_LABELS = {
    AI_PROCESSING_PARSING: "正在解析录入材料",
    AI_PROCESSING_RESEARCHING: "正在检索公开信息",
    AI_PROCESSING_PARSE_FAILED: "最近一次解析失败，请查看更新记录或失败任务",
    AI_PROCESSING_RESEARCH_FAILED: "最近一次调研失败，请查看调研任务错误后重试",
    AI_PROCESSING_NEVER: "尚未解析材料，也未发起调研",
}


def ai_processing_detail(target: Mapping[str, Any]) -> str:
    """User-facing explanation for the server-computed AI state."""
    state = ai_processing_state(target)
    if state in _AI_PROCESSING_LABELS:
        return _AI_PROCESSING_LABELS[state]
    parse_at = _as_datetime(target.get("last_parse_at"))
    research_at = _as_datetime(target.get("last_research_at"))
    if parse_at is not None and (research_at is None or parse_at >= research_at):
        return f"最近一次解析已于 {parse_at.date().isoformat()} 完成"
    if research_at is not None:
        outcome = str(target.get("research_last_outcome") or "")
        suffix = "未找到公开信息" if outcome == "no_public_information" else "已补充公开信息"
        return f"最近一次调研已于 {research_at.date().isoformat()} 完成：{suffix}"
    return "AI 处理已完成"
