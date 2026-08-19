import json
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.services.recommendation_answer_draft import read_answer_draft
from backend.app.api.routes.utils import (
    ensure_recommendation_session_visible,
)
from backend.app.db import get_db, session_scope
from backend.app.services.recommendation_flow import (
    _build_recommendation_session_summary,
    agent_history_context,
    agent_turn_aborted,
    find_agent_turn_job,
    insert_agent_aborted_message,
    _create_recommendation_session,
    find_agent_turn_answer,
    find_agent_turn_brief,
    _enqueue_recommendation_agent_job,
    _filter_recommendation_session_summaries,
    _get_recommendation_session_or_404,
    _get_recommendation_session_overview_or_404,
    _insert_recommendation_message,
    _list_recommendation_messages,
    _list_recommendation_session_overview_rows,
    _list_running_recommendation_session_ids,
    _recommendation_page_overview,
    _recommendation_quick_actions,
    _recommendation_session_is_processing,
    _touch_recommendation_session,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

# 一次输入的上限。4000 是给手打需求定的，一份上传的需求文档轻松超过；
# 正文由前端从附件正文取出后走同一个字段，所以两处共用这个上限。
AGENT_INPUT_MAX_CHARS = 20000
# 与 image_multimodal_max_count 同量级；再多一次对话也读不过来。
AGENT_MAX_IMAGE_ATTACHMENTS = 6

# 自建部署的 Caddy 开着 encode gzip，会把 SSE 攒在缓冲区里等压缩，
# 逐字流式就变成一次性吐完。no-transform 让代理不要动响应体；
# X-Accel-Buffering 是给 nginx 一类反代看的，Caddy 无视它也无害。
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# 订阅节奏。草稿由 worker 每约 500ms 落一次，读得比写快一点就够了；再快只是
# 在给数据库加空转查询。
SUBSCRIBE_POLL_SECONDS = 0.3
# 一次连接最多跟多久。Writer 实测约 47 秒；留到 5 分钟是为了覆盖 job 被部署
# 打断后重排、整轮从头再跑的情况。超了如实说「还在写」，不假装失败。
SUBSCRIBE_MAX_SECONDS = 300
# 任务状态查得比草稿稀：草稿是每一拍都要看的东西，任务状态只是「还有没有人
# 在写」的兜底判据，跟前端 1.2 秒的轮询节奏对齐就够了。
JOB_STATUS_EVERY_N_POLLS = 4
_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "missing"}
TURN_WITHOUT_ANSWER_MESSAGE = "这一轮没能生成正文，请重新提问。"
WRITER_STILL_RUNNING_MESSAGE = "正文还在生成中，稍后重新打开这个会话就能看到完整内容。"


class RecommendationMessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    content_type: str
    metadata_json: dict[str, Any]
    created_at: str


class RecommendationSessionSummaryOut(BaseModel):
    session: dict[str, Any]
    display: dict[str, Any]
    agent_status: dict[str, Any] = Field(default_factory=dict)
    activity: dict[str, Any]
    debug_ref: dict[str, Any]


class RecommendationPageOut(BaseModel):
    recent_sessions: list[RecommendationSessionSummaryOut]
    running_sessions: list[RecommendationSessionSummaryOut]
    overview: dict[str, Any]
    quick_actions: list[dict[str, Any]]
    polling_hint: dict[str, Any]


class RecommendationSessionStatusOut(BaseModel):
    session: dict[str, Any]
    display: dict[str, Any]
    agent_status: dict[str, Any] = Field(default_factory=dict)
    activity: dict[str, Any]
    debug_ref: dict[str, Any]


@router.get("/sessions/recent", response_model=list[RecommendationSessionSummaryOut])
def list_recent_recommendation_session_summaries(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    mode: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(all|running|idle)$",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=500),
) -> list[dict[str, Any]]:
    scan_limit = min(200, max(limit + offset, limit * 4))
    rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=mode,
        limit=scan_limit,
        offset=0,
        q=q,
    )
    summaries = [
        _build_recommendation_session_summary(db, session=row) for row in rows
    ]
    filtered = _filter_recommendation_session_summaries(summaries, status_filter)
    return filtered[offset : offset + limit]


@router.get("/page", response_model=RecommendationPageOut)
def get_recommendation_page(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    mode: str | None = None,
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, Any]:
    recent_rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=mode,
        limit=limit,
        offset=0,
    )
    recent_summaries = [
        _build_recommendation_session_summary(db, session=row) for row in recent_rows
    ]

    recent_ids = {str(summary["session"]["id"]) for summary in recent_summaries}
    running_summaries = [
        summary for summary in recent_summaries if _recommendation_session_is_processing(summary)
    ]
    for session_id in _list_running_recommendation_session_ids(db, current_user=current_user, limit=20):
        if str(session_id) in recent_ids:
            continue
        row = _get_recommendation_session_overview_or_404(db, session_id)
        ensure_recommendation_session_visible(db, current_user, session_id)
        if mode and row.get("mode") != mode:
            continue
        running_summaries.append(_build_recommendation_session_summary(db, session=row))

    overview = _recommendation_page_overview(recent_summaries, running_summaries)
    return {
        "recent_sessions": recent_summaries,
        "running_sessions": running_summaries,
        "overview": overview,
        "quick_actions": _recommendation_quick_actions(overview),
        "polling_hint": {
            "enabled": overview["running_session_count"] > 0,
            "interval_ms": 3000,
            "endpoint_template": "/api/v1/recommendations/sessions/{session_id}/status",
        },
    }


@router.get("/sessions/{session_id}/status", response_model=RecommendationSessionStatusOut)
def get_recommendation_session_status(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    session = _get_recommendation_session_overview_or_404(db, session_id)
    return _build_recommendation_session_summary(db, session=session)


class RecommendationAgentTurnRequest(BaseModel):
    mode: str = Field(pattern="^(buyer_to_target)$")
    session_id: UUID | None = None
    # 一段需求原文，或后续对话里的补充。上传的需求文件由前端取正文后走同一个字段。
    user_message: str = Field(min_length=1, max_length=AGENT_INPUT_MAX_CHARS)
    # 图片没有正文可以先取出来给用户看，所以只传 id，由 worker 交给多模态模型直读。
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=AGENT_MAX_IMAGE_ATTACHMENTS)


class RecommendationAgentTurnOut(BaseModel):
    session_id: UUID
    turn_id: str
    job_id: UUID
    queue_name: str


@router.post(
    "/agent-turn",
    response_model=RecommendationAgentTurnOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_recommendation_agent_turn(
    payload: RecommendationAgentTurnRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start one agent turn. Returns immediately; progress arrives by polling.

    A session created here has no anchor entity by design — the whole point of
    the page is that the consultant does not have to create a buyer intent
    first. The temporary-filter flag rides along so the existing guards keep
    relations from ever being created out of one.
    """
    user_message = payload.user_message.strip()
    if not user_message:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_message is required.")

    if payload.session_id is not None:
        ensure_recommendation_session_visible(db, current_user, payload.session_id)
        session = _get_recommendation_session_or_404(db, payload.session_id)
        if session["mode"] != payload.mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session mode does not match the request mode.",
            )
        session_id = payload.session_id
    else:
        session_id = _create_recommendation_session(
            db,
            mode=payload.mode,
            buyer_intent_id=None,
            buyer_party_id=None,
            seller_target_id=None,
            user_message=None,
            # 开场那句话也落进 anonymous_input_snapshot：会话搜索匹配的就是这一列。
            # 走 input_snapshot_only 而不是 user_message —— 后者会顺手再插一条
            # 消息，而这一轮的用户消息由下面带着 turn_id 自己写。
            input_snapshot_only=user_message,
            initial_snapshot={"agent_session": True, "first_message": user_message},
            candidates=[],
            created_by=current_user.user_id,
            is_temporary_filter=True,
        )

    # turn_id 先生成：用户消息也带上它，这一轮的问题和它的回答才有明确归属，
    # 「中止的轮次不进上下文」也才有得判断。
    turn_id = uuid4().hex
    history_context = agent_history_context(db, session_id)
    _insert_recommendation_message(
        db,
        session_id=session_id,
        role="user",
        content_type="text",
        content=user_message,
        metadata_json={"message_type": "agent_user_message", "turn_id": turn_id},
        created_by=current_user.user_id,
    )
    job_id = _enqueue_recommendation_agent_job(
        db,
        session_id=session_id,
        mode=payload.mode,
        turn_id=turn_id,
        user_message=user_message,
        history_context=history_context,
        attachment_ids=[str(value) for value in payload.attachment_ids],
        created_by=current_user.user_id,
    )
    _touch_recommendation_session(db, session_id)
    db.commit()
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "job_id": job_id,
        "queue_name": "llm",
    }


JOB_STATUS_MESSAGES = {
    "stale_running_job": "这一轮跑得太久被系统回收了。可以重试，或把需求说得更具体一些。",
}
DEFAULT_TURN_FAILURE_MESSAGE = "这一轮没能跑完。"


@router.get("/sessions/{session_id}/turns/{turn_id}/status")
def get_recommendation_agent_turn_status(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Whether this turn is still working, and if not, why it stopped.

    Polling the message table alone cannot tell "thinking" from "dead": a job
    that fails writes no message, so the page would spin until its own timeout.
    Scoped by session visibility rather than admin, because the person who has
    to read this is the consultant whose recommendation just failed.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)

    job = find_agent_turn_job(db, session_id, turn_id)
    job_status = str((job or {}).get("status") or "missing")
    failed = job_status in {"failed", "cancelled"}
    error_code = str((job or {}).get("error_code") or "") or None
    return {
        "session_id": str(session_id),
        "turn_id": turn_id,
        "job_status": job_status,
        "failed": failed,
        "aborted": agent_turn_aborted(db, session_id, turn_id),
        "error_code": error_code,
        "error_message": (
            JOB_STATUS_MESSAGES.get(error_code or "", DEFAULT_TURN_FAILURE_MESSAGE)
            if failed
            else None
        ),
        # 原始错误只给管理员：顾问看到的是上面那句人话。
        "error_detail": str((job or {}).get("error_message") or "") or None
        if failed and current_user.is_admin
        else None,
    }


@router.post(
    "/sessions/{session_id}/turns/{turn_id}/abort",
    status_code=status.HTTP_202_ACCEPTED,
)
def abort_recommendation_agent_turn(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Stop one agent turn wherever it happens to be.

    The marker is written here, immediately, rather than by whichever process
    is running — the tab may be closing, and a stop the database never heard
    about would come back as context on the next turn.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    if not agent_turn_aborted(db, session_id, turn_id):
        insert_agent_aborted_message(
            db,
            session_id=session_id,
            turn_id=turn_id,
            created_by=current_user.user_id,
        )
        _touch_recommendation_session(db, session_id)
        db.commit()
    return {"session_id": str(session_id), "turn_id": turn_id, "aborted": True}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/sessions/{session_id}/turns/{turn_id}/answer-stream")
def stream_recommendation_answer(
    session_id: UUID,
    turn_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream the final write-up for one agent turn — as a reader, not a writer.

    This endpoint used to *generate* the prose, and persisted it only after the
    stream loop finished. That made an already-paid-for answer depend on the
    browser staying connected: closing the tab lost it outright, and reopening
    the session generated and billed it a second time.

    The agent job owns the Writer now (`services/recommendation_writer`). All
    that happens here is: replay a finished answer, or follow the draft row the
    worker is filling in. The SSE contract the page consumes — `delta`, `done`,
    `error`, `aborted` — is deliberately unchanged, so the front end did not
    move with it.
    """
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)

    if agent_turn_aborted(db, session_id, turn_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This turn was stopped.",
        )

    existing = find_agent_turn_answer(db, session_id, turn_id)
    if existing is not None:
        replay = existing
        return StreamingResponse(
            iter([
                _sse("delta", {"text": replay["markdown"]}),
                _sse(
                    "done",
                    {
                        "markdown": replay["markdown"],
                        "message_id": str(replay["id"]),
                        "duration_ms": int(replay.get("duration_ms") or 0),
                        "replayed": True,
                    },
                ),
            ]),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    brief = find_agent_turn_brief(db, session_id, turn_id)
    if brief is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This turn has no writer brief yet; the agent may still be running.",
        )

    return StreamingResponse(
        _subscribe_to_answer(session_id, turn_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


def _subscribe_to_answer(session_id: UUID, turn_id: str):
    """Follow one turn's draft until it becomes an answer, a stop, or a failure.

    Every read opens its own session: the request-scoped one is already closed
    by the time a StreamingResponse generator runs.

    Deltas are suffixes of what has already been sent. A draft that stops being
    a prefix of that means the worker restarted the turn (a job released by a
    deploy and requeued), and there is no way to un-send bytes — so the reader
    skips silently to the new text and lets the final `done`, which carries the
    complete markdown, be what the page actually renders.
    """
    sent = ""
    polls = 0
    job_status = "running"
    deadline = time.monotonic() + SUBSCRIBE_MAX_SECONDS
    while True:
        with session_scope() as poll_db:
            if agent_turn_aborted(poll_db, session_id, turn_id):
                yield _sse("aborted", {"turn_id": turn_id, "message": "This turn was stopped."})
                return
            # 任务状态**必须**读在正文之前。worker 是「先提交正文、再标记成功」，
            # 倒过来读就会在这两次提交之间读到「已成功且没有正文」——一个并不
            # 存在的状态，而它的后果是把一轮刚写完的正文报成失败。
            # 隔几轮读一次即可：读到的状态偏旧只会让订阅多等一拍，而偏旧的状态
            # 仍然早于紧随其后的那次正文读取，上面那条不变式照样成立。
            if polls % JOB_STATUS_EVERY_N_POLLS == 0:
                job_status = str(
                    (find_agent_turn_job(poll_db, session_id, turn_id) or {}).get("status") or "missing"
                )
            polls += 1
            answer = find_agent_turn_answer(poll_db, session_id, turn_id)
            draft = "" if answer is not None else str(
                (read_answer_draft(poll_db, session_id=session_id, turn_id=turn_id) or {}).get(
                    "markdown"
                ) or ""
            )

        if answer is not None:
            yield _sse(
                "done",
                {
                    "markdown": answer["markdown"],
                    "message_id": str(answer["id"]),
                    # Real Writer duration, measured in the worker from the
                    # first token to the last — no longer whatever slice of it
                    # this particular connection happened to witness.
                    "duration_ms": int(answer.get("duration_ms") or 0),
                },
            )
            return

        if draft != sent:
            if draft.startswith(sent):
                yield _sse("delta", {"text": draft[len(sent):]})
            sent = draft

        if job_status in _TERMINAL_JOB_STATUSES:
            # 任务已经收尾却没有正文：真实失败，或者是发布窗口里那种「旧代码写完
            # brief 就停下」的遗留轮次。说清楚比转圈到超时好。
            yield _sse("error", {"message": TURN_WITHOUT_ANSWER_MESSAGE})
            return

        if time.monotonic() >= deadline:
            yield _sse("error", {"message": WRITER_STILL_RUNNING_MESSAGE})
            return

        time.sleep(SUBSCRIBE_POLL_SECONDS)


@router.get("/sessions/{session_id}/messages", response_model=list[RecommendationMessageOut])
def list_recommendation_messages(
    session_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    ensure_recommendation_session_visible(db, current_user, session_id)
    _get_recommendation_session_or_404(db, session_id)
    return _list_recommendation_messages(db, session_id=session_id, limit=limit, offset=offset)


# Region groups let phrases like 长三角 in region_scope_summary match concrete
# provinces. Province names are stored without 省/市 suffixes.

# Score caps: hard mismatches and exclusion hits sink candidates instead of
# deleting them (business rule: never hide an opportunity, but label it).


