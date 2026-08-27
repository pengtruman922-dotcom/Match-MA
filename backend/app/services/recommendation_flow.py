"""Recommendation session/candidate/report flow logic shared with API routes."""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    owner_scope_required,
    recommendation_report_visible_sql,
    recommendation_session_visible_sql,
)
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column
from backend.app.services.relation_flow import DEEP_PROGRESS_STATUSES


def _list_recommendation_session_overview_rows(
    db: Session,
    *,
    current_user: CurrentUser,
    mode: str | None,
    limit: int,
    offset: int,
    q: str | None = None,
) -> list[dict[str, Any]]:
    where = ["rs.team_id = :team_id", "rs.workspace_id = :workspace_id", "rs.status <> 'archived'"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    if mode:
        where.append("rs.mode = :mode")
        params["mode"] = mode
    if owner_scope_required(current_user):
        where.append(recommendation_session_visible_sql("rs"))
        params["scope_user_id"] = current_user.user_id
    normalized_query = (q or "").strip()
    if normalized_query:
        where.append(
            """(
              (rs.mode = 'buyer_to_target' and coalesce(bi.intent_name, '') ilike :q)
              or (rs.mode = 'target_to_buyer' and coalesce(st.target_name, '') ilike :q)
              or (
                coalesce(rs.metadata_json ->> 'temporary_filter', 'false') = 'true'
                and coalesce(rs.anonymous_input_snapshot, '') ilike :q
              )
            )"""
        )
        params["q"] = f"%{normalized_query}%"

    rows = db.execute(
        text(
            f"""
            select {_session_overview_select_columns()}
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = coalesce(rs.buyer_party_id, bi.buyer_party_id)
            left join seller_target st on st.id = rs.seller_target_id
            left join app_user creator on creator.id = rs.created_by
            where {' and '.join(where)}
            order by rs.updated_at desc, rs.created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _get_recommendation_session_overview_or_404(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_session_overview_select_columns()}
            from recommendation_session rs
            left join buyer_intent bi on bi.id = rs.buyer_intent_id
            left join buyer_party bp on bp.id = coalesce(rs.buyer_party_id, bi.buyer_party_id)
            left join seller_target st on st.id = rs.seller_target_id
            left join app_user creator on creator.id = rs.created_by
            where rs.id = :session_id
              and rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation session not found.")
    return dict(row)


def _list_running_recommendation_session_ids(
    db: Session,
    *,
    current_user: CurrentUser,
    limit: int,
) -> list[UUID]:
    scope_join = ""
    scope_where = ""
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
    }
    if owner_scope_required(current_user):
        scope_join = """
            join recommendation_session rs
              on rs.id = running_jobs.session_id
             and rs.team_id = :team_id
             and rs.workspace_id = :workspace_id
        """
        scope_where = f"and {recommendation_session_visible_sql('rs')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
            with running_jobs as (
              select
                case
                  when job.job_type = 'recommendation_agent'
                    and job.entity_type = 'recommendation_session'
                    then job.entity_id
                  when job.payload_json ? 'session_id'
                    and job.payload_json ->> 'session_id'
                      ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    then nullif(job.payload_json ->> 'session_id', '')::uuid
                  else null
                end as session_id
              from background_job job
              where job.team_id = :team_id
                and job.workspace_id = :workspace_id
                and job.job_type = 'recommendation_agent'
                and job.status in ('queued', 'running', 'retry_waiting')
            )
            select distinct session_id
            from running_jobs
            {scope_join}
            where session_id is not null
            {scope_where}
            order by session_id
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return [row["session_id"] for row in rows if row.get("session_id") is not None]


def _build_recommendation_session_summary(
    db: Session,
    *,
    session: dict[str, Any],
) -> dict[str, Any]:
    session_id = session["id"]
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    agent_status = _build_recommendation_agent_status(
        db,
        session_id=session_id,
        messages=messages,
    )
    return {
        "session": session,
        "display": _recommendation_session_display(session, messages=messages),
        "agent_status": agent_status,
        "activity": _build_recommendation_activity(session=session, messages=messages),
        "debug_ref": {
            "entity_type": "recommendation_session",
            "entity_id": str(session_id),
            "route": f"/debug/entities/recommendation_session/{session_id}",
        },
    }


AGENT_SESSION_TITLE_MAX_CHARS = 24


def _agent_session_first_message(session: dict[str, Any]) -> str:
    """The question this conversation opened with.

    Stored twice on purpose: `anonymous_input_snapshot` is what the session
    search matches on, the snapshot json is the belt-and-braces copy for rows
    written before that column was populated.
    """
    snapshot = session.get("initial_condition_snapshot_json")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    for value in (session.get("anonymous_input_snapshot"), snapshot.get("first_message")):
        text_value = str(value or "").strip()
        if text_value:
            return text_value
    return ""


def _count_agent_turns(messages: list[dict[str, Any]] | None) -> int:
    if not messages:
        return 0
    turn_ids = {
        str((message.get("metadata_json") or {}).get("turn_id") or "")
        for message in messages
        if isinstance(message.get("metadata_json"), dict)
    }
    turn_ids.discard("")
    return len(turn_ids)


def _recommendation_session_display(
    session: dict[str, Any],
    *,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mode = session.get("mode")
    is_temporary_filter = bool((session.get("metadata_json") or {}).get("temporary_filter"))
    snapshot = session.get("initial_condition_snapshot_json")
    is_agent_session = bool((snapshot if isinstance(snapshot, dict) else {}).get("agent_session"))
    if is_agent_session:
        # 一屏全是「临时条件筛选」就等于没有标题；开场那句话才是用户认得出的东西。
        first_message = _agent_session_first_message(session)
        title = first_message[:AGENT_SESSION_TITLE_MAX_CHARS] or "新对话"
        if len(first_message) > AGENT_SESSION_TITLE_MAX_CHARS:
            title = f"{title}…"
        turn_count = _count_agent_turns(messages)
        return {
            "title": title,
            "subtitle": f"{turn_count} 轮对话" if turn_count else "尚未开始",
            "mode_label": "买家找标的" if mode == "buyer_to_target" else "标的找买家",
            "anchor": {"entity_type": None, "entity_id": None},
            "primary_action": "agent_chat",
            "turn_count": turn_count,
            "route": f"/recommend?session={session['id']}",
        }
    if is_temporary_filter:
        return {
            "title": "临时条件筛选",
            "subtitle": "仅查看结果，未关联业务对象",
            "mode_label": "买家找标的" if mode == "buyer_to_target" else "标的找买家",
            "anchor": {"entity_type": None, "entity_id": None},
            "primary_action": "temporary_filter",
            "turn_count": 0,
            "route": f"/recommendations/sessions/{session['id']}",
        }
    if mode == "buyer_to_target":
        title = session.get("buyer_intent_name") or session.get("buyer_name") or "买家找标的"
        subtitle = session.get("buyer_name")
        anchor = {"entity_type": "buyer_intent", "entity_id": _string_or_none(session.get("buyer_intent_id"))}
        primary_action = "recommend_targets"
    else:
        title = session.get("seller_target_name") or "标的找买家"
        subtitle = "推荐买家意向"
        anchor = {"entity_type": "seller_target", "entity_id": _string_or_none(session.get("seller_target_id"))}
        primary_action = "recommend_buyers"
    return {
        "title": title,
        "subtitle": subtitle,
        "mode_label": "买家找标的" if mode == "buyer_to_target" else "标的找买家",
        "anchor": anchor,
        "primary_action": primary_action,
        "turn_count": 0,
        "route": f"/recommendations/sessions/{session['id']}",
    }


def _recommendation_session_is_processing(summary: dict[str, Any]) -> bool:
    # 黄点/绿点判据。5A 删掉 rerank 一支、5B 删掉 report 一支后只剩 agent_status，
    # 它同时覆盖 Writer 间隙（有 brief 无 answer 时为 writing）—— 那个间隙现在由
    # worker 自己关掉，不再取决于有没有页签连着。
    return (summary.get("agent_status") or {}).get("status") in {
        "queued", "running", "retry_waiting", "writing",
    }


def _build_recommendation_agent_status(
    db: Session,
    *,
    session_id: UUID,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Terminal state for the latest Agent turn, including the Writer gap.

    A brief with no answer and no abort means the Writer is mid-flight, so the
    turn reads ``writing`` — the server-side signal behind every tab's yellow
    dot. That gap used to be unbounded because the Writer ran inside the SSE
    request: nobody connected, nobody wrote, and the dot stayed yellow forever.
    Since the agent job owns the Writer it closes on its own, whether or not a
    browser is watching.
    """
    latest_turn_id = ""
    for message in messages:
        metadata = message.get("metadata_json") if isinstance(message.get("metadata_json"), dict) else {}
        turn_id = str(metadata.get("turn_id") or "")
        if turn_id and str(message.get("role") or "") == "user":
            latest_turn_id = turn_id
    if not latest_turn_id:
        return {"status": "not_started", "turn_id": None, "writer_pending": False}

    message_types = {
        str((message.get("metadata_json") or {}).get("message_type") or "")
        for message in messages
        if isinstance(message.get("metadata_json"), dict)
        and str((message.get("metadata_json") or {}).get("turn_id") or "") == latest_turn_id
    }
    if "agent_aborted" in message_types:
        status = "aborted"
    elif "agent_answer" in message_types:
        status = "completed"
    elif "agent_question" in message_types:
        status = "waiting_user"
    elif "agent_brief" in message_types:
        status = "writing"
    else:
        job = find_agent_turn_job(db, session_id, latest_turn_id)
        job_status = str((job or {}).get("status") or "missing")
        status = "failed" if job_status in {"failed", "cancelled"} else job_status
    return {
        "status": status,
        "turn_id": latest_turn_id,
        "writer_pending": status == "writing",
    }


def _filter_recommendation_session_summaries(
    summaries: list[dict[str, Any]],
    status_filter: str | None,
) -> list[dict[str, Any]]:
    if not status_filter or status_filter == "all":
        return summaries
    if status_filter == "running":
        return [summary for summary in summaries if _recommendation_session_is_processing(summary)]
    if status_filter == "idle":
        # failed / generated / selected 三个取值随推荐报告与选中一起下线（阶段五 5B）：
        # 它们全部读 report_status / selected_status，那两块已经没有数据来源了。
        return [summary for summary in summaries if not _recommendation_session_is_processing(summary)]
    return summaries


def _recommendation_page_overview(
    recent_summaries: list[dict[str, Any]],
    running_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "recent_session_count": len(recent_summaries),
        "running_session_count": len(running_summaries),
    }


def _recommendation_quick_actions(overview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": "start_buyer_to_target",
            "label": "按买家找标的",
            "action": "open_buyer_selector",
            "route": None,
            "badge_count": None,
        },
        {
            "key": "start_target_to_buyer",
            "label": "按标的找买家",
            "action": "open_target_selector",
            "route": None,
            "badge_count": None,
        },
        {
            "key": "review_running",
            "label": "查看生成中",
            "action": "filter_running_sessions",
            "route": "/recommendations?status=running",
            "badge_count": overview.get("running_session_count"),
        },
    ]


def _build_recommendation_activity(
    *,
    session: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamps = [
        session.get("updated_at"),
        messages[-1].get("created_at") if messages else None,
    ]
    latest_activity_at = max([value for value in timestamps if value] or [None])
    return {
        "latest_activity_at": latest_activity_at,
        "message_count": len(messages),
        "last_message": _compact_recommendation_message(messages[-1]) if messages else None,
    }


def _compact_recommendation_message(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message.get("content") or "")
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "content_type": message.get("content_type"),
        "content_preview": content[:160],
        "metadata_json": message.get("metadata_json"),
        "created_at": message.get("created_at"),
    }


def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _list_recommendation_messages(
    db: Session,
    *,
    session_id: UUID,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_message_select_columns()}
            from recommendation_message
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at asc
            limit :limit offset :offset
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def target_facts_for_agent(target_row: dict[str, Any]) -> dict[str, Any]:
    """Facts for a target the agent pulled by id rather than through screening.

    Same formatter the screened candidates go through, so a target that entered
    by id quotes identical numbers to one that came out of the funnel.
    """
    return _target_facts(target_row)


def _money_text(value: Any) -> str | None:
    number = _optional_float(value)
    if number is None:
        return None
    if number >= 100000000:
        return f"{number / 100000000:.1f}亿".replace(".0亿", "亿")
    if number >= 10000:
        return f"{number / 10000:.0f}万"
    return str(int(number))


def _enum_label(column: str, value: Any) -> str | None:
    """Chinese label for a seller_target enum, straight from the registry.

    Going through the registry rather than a local dict is what keeps these
    labels from drifting away from the ones the rest of the system shows.
    """
    code = str(value or "").strip()
    if not code or code == "unknown":
        return None
    try:
        options = indicator_by_column("seller_target", column).enum_options or ()
    except KeyError:
        return None
    for option_code, option_label in options:
        if option_code == code:
            return option_label
    return code


def _target_facts(item: dict[str, Any]) -> dict[str, Any]:
    """The hard numbers a client manager reads first, in LLM-ready form.

    Raw values are kept alongside the formatted text so a table can sort on
    them; the text form is what the writer node quotes.
    """
    region = "".join(
        str(value) for value in (
            item.get("location_province"),
            item.get("location_city"),
            item.get("location_district"),
        ) if value
    )
    industry = " / ".join(
        str(value) for value in (item.get("industry_l1"), item.get("industry_l2")) if value
    )
    pe_ratio = _optional_float(item.get("pe_ratio"))
    debt_ratio = _optional_float(item.get("current_debt_ratio"))
    transfer_max = _optional_float(item.get("transfer_ratio_max"))
    facts: dict[str, Any] = {
        "industry": industry or None,
        "region": region or None,
        "revenue_yuan": _optional_float(item.get("current_revenue_yuan")),
        "revenue_text": _money_text(item.get("current_revenue_yuan")),
        "net_profit_yuan": _optional_float(item.get("current_net_profit_yuan")),
        "net_profit_text": _money_text(item.get("current_net_profit_yuan")),
        "total_profit_text": _money_text(item.get("current_total_profit_yuan")),
        "valuation_text": _money_text(item.get("valuation_yuan")),
        "asking_price_text": _money_text(item.get("asking_price_yuan")),
        "market_cap_text": _money_text(item.get("market_cap_yuan")),
        "pe_ratio": pe_ratio,
        "debt_ratio": debt_ratio,
        "can_control": _enum_label("can_control", item.get("can_control")),
        "can_consolidate": _enum_label("can_consolidate", item.get("can_consolidate")),
        "transfer_ratio_max": transfer_max,
        "listed_status": _enum_label("listed_status", item.get("listed_status")),
        "cash_flow_status": _enum_label("cash_flow_status", item.get("cash_flow_status")),
        "profitability_status": _enum_label("profitability_status", item.get("profitability_status")),
        "management_retention_possible": _enum_label(
            "management_retention_possible", item.get("management_retention_possible")
        ),
    }
    return {key: value for key, value in facts.items() if value is not None}


# 存在 critical 风险记录时的系统级降权（与买家条件无关，不影响三态）。


def _create_recommendation_session(
    db: Session,
    *,
    mode: str,
    buyer_intent_id: UUID | None,
    buyer_party_id: UUID | None,
    seller_target_id: UUID | None,
    user_message: str | None,
    initial_snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    created_by: UUID,
    is_temporary_filter: bool = False,
    input_snapshot_only: str | None = None,
) -> UUID:
    """Create a session.

    `user_message` both fills `anonymous_input_snapshot` and writes a first
    message; `input_snapshot_only` fills the column without writing anything.
    The agent flow needs the latter — it writes its own user message with a
    turn_id attached, and passing `user_message` here would store the question
    twice.
    """
    row = db.execute(
        text(
            """
            insert into recommendation_session (
              team_id, workspace_id, mode, buyer_intent_id, buyer_party_id,
              seller_target_id, anonymous_input_snapshot,
              initial_condition_snapshot_json, latest_condition_snapshot_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :mode, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :anonymous_input_snapshot,
              :initial_condition_snapshot_json, :latest_condition_snapshot_json,
              :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("initial_condition_snapshot_json", type_=JSONB),
            bindparam("latest_condition_snapshot_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "mode": mode,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "anonymous_input_snapshot": user_message or input_snapshot_only,
            "initial_condition_snapshot_json": _json_safe(initial_snapshot),
            "latest_condition_snapshot_json": _json_safe(initial_snapshot),
            "created_by": created_by,
            "metadata_json": {
                "source": "recommendation_candidate_api",
                "candidate_count": len(candidates),
                "temporary_filter": is_temporary_filter,
            },
        },
    ).mappings().one()
    if user_message:
        _insert_recommendation_message(
            db,
            session_id=row["id"],
            role="user",
            content_type="text",
            content=user_message,
            created_by=created_by,
        )
    return row["id"]


def _insert_recommendation_message(
    db: Session,
    *,
    session_id: UUID,
    role: str,
    content_type: str,
    content: str | dict[str, Any],
    metadata_json: dict[str, Any] | None = None,
    created_by: UUID = DEFAULT_ADMIN_USER_ID,
) -> None:
    db.execute(
        text(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, :role, :content,
              :content_type, :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "role": role,
            "content": content if isinstance(content, str) else _json_dumps(content),
            "content_type": content_type,
            "metadata_json": metadata_json or {},
            "created_by": created_by,
        },
    )


def _get_recommendation_session_or_404(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_session_select_columns()}
            from recommendation_session
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation session not found.")
    return dict(row)


def _get_buyer_party_id_for_intent(db: Session, buyer_intent_id: UUID) -> UUID | None:
    row = db.execute(
        text(
            """
            select buyer_party_id
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return row["buyer_party_id"] if row else None


def session_anchor_buyer_party_id(db: Session, session_id: UUID) -> UUID | None:
    """这个会话锚在哪个买家主体上；纯对话会话没有锚点，返回 None。

    深评的「买方自身情况」块要靠它才有内容。会话自己的 `buyer_party_id` 优先，
    没有则顺着 `buyer_intent_id` 取 —— 前端锚定时给的是需求 id，主体是推导出来
    的，两处都存是为了主体后来被换掉时这条会话仍指向当时那个。
    """
    row = db.execute(
        text(
            """
            select coalesce(rs.buyer_party_id, bi.buyer_party_id) as buyer_party_id
            from recommendation_session rs
            left join buyer_intent bi
              on bi.id = rs.buyer_intent_id
             and bi.deleted_at is null
            where rs.id = :session_id
              and rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return row["buyer_party_id"] if row else None


def attach_session_anchor(
    db: Session,
    *,
    session_id: UUID,
    buyer_intent_id: UUID,
    buyer_party_id: UUID | None,
) -> bool:
    """把锚点补写到一个还没有锚点的会话上，返回是否真的写了。

    对话可以先聊、后挂需求，所以补写要允许。但**只补空的**：已经锚定的会话
    换锚点，等于这一轮之前的回答换了买家却不留痕迹。
    """
    result = db.execute(
        text(
            """
            update recommendation_session
            set buyer_intent_id = :buyer_intent_id,
                buyer_party_id = coalesce(:buyer_party_id, buyer_party_id),
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and buyer_intent_id is null
            """
        ),
        {
            "session_id": session_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    return bool(result.rowcount)


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _agent_turn_messages(db: Session, session_id: UUID, turn_id: str) -> list[dict[str, Any]]:
    """Every message this agent turn produced, decoded."""
    decoded: list[dict[str, Any]] = []
    for message in _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0):
        metadata = message.get("metadata_json") if isinstance(message.get("metadata_json"), dict) else {}
        if str(metadata.get("turn_id") or "") != turn_id:
            continue
        if message.get("content_type") == "json":
            content = _json_loads(message.get("content") or "{}")
        else:
            content = {"text": message.get("content")}
        decoded.append({**message, "decoded_content": content, "message_type": metadata.get("message_type")})
    return decoded


def find_agent_turn_brief(db: Session, session_id: UUID, turn_id: str) -> dict[str, Any] | None:
    for message in _agent_turn_messages(db, session_id, turn_id):
        if message["message_type"] == "agent_brief":
            brief = message["decoded_content"].get("brief")
            if isinstance(brief, dict):
                return brief
    return None


def find_agent_turn_answer(db: Session, session_id: UUID, turn_id: str) -> dict[str, Any] | None:
    """The persisted answer, if this turn already produced one.

    This is what makes the stream resumable: a reconnect after the write has
    landed replays the stored text instead of paying for a second generation.

    One targeted row rather than a walk over `_agent_turn_messages`, which
    decodes up to 500 messages: the answer-stream subscriber calls this a few
    times a second while it waits for the worker to finish.
    """
    row = db.execute(
        text(
            """
            select id, content
            from recommendation_message
            where team_id = :team_id
              and workspace_id = :workspace_id
              and session_id = :session_id
              and metadata_json ->> 'message_type' = 'agent_answer'
              and metadata_json ->> 'turn_id' = :turn_id
            order by created_at asc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    ).mappings().one_or_none()
    if row is None:
        return None
    content = _json_loads(row["content"] or "{}")
    return {
        "id": row["id"],
        "markdown": content.get("markdown") or "",
        "duration_ms": int(content.get("duration_ms") or 0),
    }


def find_agent_turn_job(db: Session, session_id: UUID, turn_id: str) -> dict[str, Any] | None:
    """The queued job behind one agent turn, found by its deterministic key.

    Exists so the page can tell "still working" from "died" without going
    through the admin-only job API — a consultant has to be able to see why
    their own recommendation failed.
    """
    row = db.execute(
        text(
            """
            select status, error_code, error_message,
                   started_at::text as started_at, finished_at::text as finished_at
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and idempotency_key = :idempotency_key
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "idempotency_key": f"recommendation_agent:{session_id}:{turn_id}",
        },
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def agent_turn_aborted(db: Session, session_id: UUID, turn_id: str) -> bool:
    """Whether this turn carries a stop marker.

    The single source of truth for "was this turn stopped": the worker, the
    stream and the history builder all ask here. Three processes can race to
    finish a turn the user just stopped, so the rule is that the marker wins
    regardless of what else managed to land.
    """
    row = db.execute(
        text(
            """
            select 1
            from recommendation_message
            where team_id = :team_id
              and workspace_id = :workspace_id
              and session_id = :session_id
              and metadata_json ->> 'message_type' = 'agent_aborted'
              and metadata_json ->> 'turn_id' = :turn_id
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    ).first()
    return row is not None


def _lock_agent_turn_terminal_write(db: Session, session_id: UUID, turn_id: str) -> None:
    """Serialise the competing terminal writes for one Agent turn.

    The abort endpoint and the Writer SSE run in different requests. A plain
    ``if not aborted: insert answer`` check still has a race between the SELECT
    and INSERT. The transaction-scoped advisory lock makes the marker check and
    terminal write one ordered decision without adding a schema object.
    """
    db.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"recommendation-agent-turn:{session_id}:{turn_id}"},
    )


def insert_agent_aborted_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    created_by: UUID = DEFAULT_ADMIN_USER_ID,
) -> bool:
    """Mark a turn stopped, written the moment the user asks rather than when
    the worker notices — otherwise a closed tab would leave no record at all."""
    _lock_agent_turn_terminal_write(db, session_id, turn_id)
    if agent_turn_aborted(db, session_id, turn_id):
        return False
    _insert_recommendation_message(
        db,
        session_id=session_id,
        role="tool",
        content_type="json",
        content={"message_type": "agent_aborted", "turn_id": turn_id},
        metadata_json={"message_type": "agent_aborted", "turn_id": turn_id},
        created_by=created_by,
    )
    return True


def find_agent_answer_id(db: Session, session_id: UUID, turn_id: str) -> UUID | None:
    """The answer row's id, without decoding every message in the session.

    `find_agent_turn_answer` reads up to 500 messages and parses their JSON,
    which is fine for a page load and much too heavy to run while holding the
    turn's advisory lock.
    """
    row = db.execute(
        text(
            """
            select id
            from recommendation_message
            where team_id = :team_id
              and workspace_id = :workspace_id
              and session_id = :session_id
              and metadata_json ->> 'message_type' = 'agent_answer'
              and metadata_json ->> 'turn_id' = :turn_id
            order by created_at asc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "turn_id": turn_id,
        },
    ).mappings().one_or_none()
    return row["id"] if row is not None else None


@dataclass(frozen=True)
class AgentAnswerWrite:
    """Why the terminal write did or did not happen.

    "Stopped" and "someone already wrote it" both mean *this* caller wrote
    nothing, and collapsing them into a bare None got them confused: a second
    producer would report the finished turn to the browser as aborted and blank
    a perfectly good answer.
    """

    status: str  # "inserted" | "aborted" | "already_exists"
    message_id: UUID | None


def insert_agent_answer_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    markdown: str,
    model_name: str | None,
    generation_mode: str,
    duration_ms: int = 0,
) -> AgentAnswerWrite:
    """Persist the answer only if the turn is neither stopped nor already done.

    Both checks share the turn advisory lock with the abort marker, so "is it
    stopped", "is it already answered" and "write the answer" are one ordered
    decision. Without the second check two producers racing the same turn —
    a worker and an API instance mid-deploy, or two workers after a requeue —
    would each append their own answer and the turn would end up saying the
    same thing twice.
    """
    _lock_agent_turn_terminal_write(db, session_id, turn_id)
    if agent_turn_aborted(db, session_id, turn_id):
        return AgentAnswerWrite(status="aborted", message_id=None)
    existing_id = find_agent_answer_id(db, session_id, turn_id)
    if existing_id is not None:
        return AgentAnswerWrite(status="already_exists", message_id=existing_id)
    row = db.execute(
        _message_returning_statement(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, 'assistant', :content,
              'json', :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "content": _json_dumps(
                {
                    "message_type": "agent_answer",
                    "turn_id": turn_id,
                    "markdown": markdown,
                    "duration_ms": max(0, int(duration_ms or 0)),
                }
            ),
            "metadata_json": {
                "message_type": "agent_answer",
                "turn_id": turn_id,
                "model_name": model_name,
                "generation_mode": generation_mode,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    ).mappings().one()
    return AgentAnswerWrite(status="inserted", message_id=row["id"])


def _enqueue_recommendation_agent_job(
    db: Session,
    *,
    session_id: UUID,
    mode: str,
    turn_id: str,
    user_message: str,
    history_context: str,
    attachment_ids: list[str],
    created_by: UUID,
) -> UUID:
    """Queue one agent turn on the llm queue.

    max_attempts is 1 on purpose: a retry would re-run the whole tool loop and
    bill a second time, and the user is watching a progress line that already
    shows what the first attempt did. Failures surface as a failed turn, not as
    a silent second run.
    """
    payload = _json_loads(
        _json_dumps(
            {
                "session_id": session_id,
                "mode": mode,
                "turn_id": turn_id,
                "user_message": user_message,
                "history_context": history_context,
                "attachment_ids": attachment_ids,
            }
        )
    )
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'recommendation_agent', 100, 'llm',
              'recommendation_session', :session_id, :idempotency_key, :payload_json,
              1, :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "idempotency_key": f"recommendation_agent:{session_id}:{turn_id}",
            "payload_json": payload,
            "created_by": created_by,
            "metadata_json": {"source": "recommendation_agent_api", "turn_id": turn_id},
        },
    ).mappings().one()
    return row["id"]


AGENT_HISTORY_MAX_TURNS = 5
# 兜底而已，正常 5 轮远到不了。超了按整轮丢，不截断。
AGENT_HISTORY_MAX_CHARS = 40000


def _agent_history_turns(db: Session, session_id: UUID) -> list[dict[str, Any]]:
    """Turns the next one is allowed to read, oldest first.

    Two kinds qualify. A **completed** turn contributes both halves verbatim.
    A turn the user **stopped** contributes its question only — pressing stop
    usually means "I am still asking this, just not like that", and dropping
    the turn made the follow-up ("那就江苏吧") arrive with nothing to attach
    itself to.

    Everything else is still dropped whole: a turn that failed, or whose
    write-up never landed without the user asking it to stop, is a half turn
    the model would read as an unanswered question and answer a second time.
    """
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    order: list[str] = []
    turns: dict[str, dict[str, Any]] = {}
    pending_question: str | None = None

    def ensure(turn_id: str) -> dict[str, Any]:
        entry = turns.get(turn_id)
        if entry is None:
            entry = {"question": "", "answer": "", "aborted": False}
            turns[turn_id] = entry
            order.append(turn_id)
        return entry

    for message in messages:
        metadata = message.get("metadata_json") if isinstance(message.get("metadata_json"), dict) else {}
        turn_id = str(metadata.get("turn_id") or "")
        if str(message.get("role") or "") == "user":
            question = str(message.get("content") or "").strip()
            if turn_id:
                ensure(turn_id)["question"] = question
                pending_question = None
            else:
                # 早于 turn_id 落到用户消息上的那批行，只能靠先后顺序认亲。
                pending_question = question
            continue
        if not turn_id or message.get("content_type") != "json":
            continue
        entry = ensure(turn_id)
        if pending_question and not entry["question"]:
            entry["question"] = pending_question
            pending_question = None
        message_type = str(metadata.get("message_type") or "")
        if message_type == "agent_answer":
            # content 是 JSON 文本，不是 dict —— 表里这一列是 text。
            decoded = _json_loads(message.get("content") or "{}")
            entry["answer"] = str(decoded.get("markdown") or "").strip()
        elif message_type == "agent_aborted":
            entry["aborted"] = True

    usable = [
        turns[turn_id]
        for turn_id in order
        if turns[turn_id]["question"]
        and (turns[turn_id]["aborted"] or turns[turn_id]["answer"])
    ]
    # 中止轮占额度：那是用户真的说过的一句话，和已完成轮一样挤占最近 5 轮。
    return usable[-AGENT_HISTORY_MAX_TURNS:]


# 中止轮的标记。刻意不复用 <user>/<AI> 那对标签：模型见到成对标签就默认
# 「这一问已经被回答过」，而这里恰恰相反 —— 它没有被回答。
ABORTED_TURN_NOTE = (
    "用户主动中止了该轮，AI未作答；此输入仍属于当前需求，请与后续补充合并理解。"
)


def _history_block(turn: dict[str, Any]) -> str:
    if turn.get("aborted"):
        return (
            "<aborted_user_turn>\n"
            f"<user>：{turn['question']}\n"
            f"<turn_note>{ABORTED_TURN_NOTE}</turn_note>\n"
            "</aborted_user_turn>"
        )
    return f"<user>：{turn['question']}\n<AI>：{turn['answer']}"


def agent_history_context(db: Session, session_id: UUID) -> str:
    """Previous turns, verbatim, tagged so the agent cannot mistake them for now.

    Verbatim rather than summarised on purpose: the consultant's follow-up
    ("把第二家换掉") is written against the exact words on their screen, so
    anything the agent reads that differs from what the user read is a chance
    to misunderstand. Tool results stay out — the agent re-screens every turn
    and replaying old result sets would only spend context on stale numbers.

    A stopped turn appears as `<aborted_user_turn>`: the question, plus an
    explicit note that no answer was produced. It deliberately gets no empty
    `<AI>：` line and never carries prose that had already streamed before the
    stop — an empty answer slot reads as "the assistant said nothing", which is
    an invitation to answer it all over again.
    """
    turns = _agent_history_turns(db, session_id)
    blocks: list[str] = []
    budget = AGENT_HISTORY_MAX_CHARS
    # 从最近一轮往回收，装不下就停 —— 丢掉的永远是最旧的整轮。
    for turn in reversed(turns):
        block = _history_block(turn)
        if len(block) > budget:
            break
        budget -= len(block)
        blocks.append(block)
    if not blocks:
        return ""
    return "<history_context>\n{}\n</history_context>".format("\n\n".join(reversed(blocks)))


def _touch_recommendation_session(db: Session, session_id: UUID) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _session_select_columns() -> str:
    return """
      id, mode, buyer_intent_id, buyer_party_id, seller_target_id, status,
      selected_count, report_count, anonymous_input_snapshot,
      initial_condition_snapshot_json, latest_condition_snapshot_json,
      condition_overrides_json,
      created_at::text as created_at, updated_at::text as updated_at, metadata_json
    """


def _session_overview_select_columns() -> str:
    return """
      rs.id, rs.mode, rs.buyer_intent_id, rs.buyer_party_id, rs.seller_target_id, rs.status,
      rs.selected_count, rs.report_count, rs.anonymous_input_snapshot,
      rs.initial_condition_snapshot_json, rs.latest_condition_snapshot_json,
      rs.condition_overrides_json,
      rs.created_at::text as created_at, rs.updated_at::text as updated_at, rs.metadata_json,
      rs.created_by,
      creator.name as created_by_name,
      creator.username as created_by_username,
      bi.intent_name as buyer_intent_name,
      bp.buyer_name,
      st.target_name as seller_target_name
    """


def _message_select_columns() -> str:
    return """
      id, session_id, role, content, content_type,
      metadata_json, created_at::text as created_at
    """


def _message_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_message_select_columns()}")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, UUID):
            result[key] = str(item)
        elif isinstance(item, Decimal):
            result[key] = float(item)
        else:
            result[key] = item
    return result


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
