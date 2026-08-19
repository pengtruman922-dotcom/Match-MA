"""Recommendation session/candidate/report flow logic shared with API routes."""

import re
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


def _build_recommendation_session_bundle(
    db: Session,
    *,
    session_id: UUID,
    include_canceled: bool,
    current_user: CurrentUser,
) -> dict[str, Any]:
    session = _get_recommendation_session_or_404(db, session_id)
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    selected_items = _list_selected_items(
        db,
        session_id=session_id,
        include_canceled=include_canceled,
        limit=500,
        offset=0,
    )
    reports = _list_recommendation_reports(db, session_id=session_id, limit=100, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    initial_candidates = _enrich_candidates_with_selection(
        candidate_sets["initial_candidates"],
        selected_items,
    )
    reranked_candidates = _enrich_candidates_with_selection(
        candidate_sets["reranked_candidates"],
        selected_items,
    )
    # Candidate messages are an immutable recommendation snapshot, whereas a
    # buyer-seller relation can be created or move stage while the page is
    # polling.  Recompute relation annotations on every bundle read so a
    # locally-created "已在推进" badge cannot revert after the next refresh and
    # the other-buyer deep-progress warning stays current.
    mode = str(session["mode"])
    initial_candidates = _annotate_candidate_relations(
        db, {"candidates": initial_candidates}, mode=mode
    )["candidates"]
    reranked_candidates = _annotate_candidate_relations(
        db, {"candidates": reranked_candidates}, mode=mode
    )["candidates"]
    initial_candidates = _annotate_candidate_ownership(
        db,
        {"candidates": initial_candidates},
        mode=mode,
        current_user=current_user,
    )["candidates"]
    reranked_candidates = _annotate_candidate_ownership(
        db,
        {"candidates": reranked_candidates},
        mode=mode,
        current_user=current_user,
    )["candidates"]
    latest_candidates = reranked_candidates or initial_candidates
    candidate_source = "reranked_candidates" if reranked_candidates else (
        "initial_candidates" if initial_candidates else "none"
    )
    return {
        "session": session,
        "messages": messages,
        "initial_candidates": initial_candidates,
        "reranked_candidates": reranked_candidates,
        "latest_candidates": latest_candidates,
        "candidate_source": candidate_source,
        "selected_items": selected_items,
        "reports": reports,
        "debug": {
            "selected_count": len([item for item in selected_items if item.get("canceled_at") is None]),
            "canceled_selected_count": len([item for item in selected_items if item.get("canceled_at") is not None]),
            "message_count": len(messages),
            "report_count": len(reports),
            "initial_candidate_count": len(initial_candidates),
            "reranked_candidate_count": len(reranked_candidates),
            "latest_candidate_count": len(latest_candidates),
            "candidate_source": candidate_source,
            "engine_hint": "rule_sql_python_deep_eval_v1",
        },
    }


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
                and job.job_type in (
                      'recommendation_report_generate', 'recommendation_agent'
                    )
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
    preview_limit: int,
) -> dict[str, Any]:
    session_id = session["id"]
    messages = _list_recommendation_messages(db, session_id=session_id, limit=500, offset=0)
    selected_items = _list_selected_items(
        db,
        session_id=session_id,
        include_canceled=True,
        limit=500,
        offset=0,
    )
    reports = _list_recommendation_reports(db, session_id=session_id, limit=50, offset=0)
    candidate_sets = _extract_recommendation_candidate_sets(messages)
    initial_candidates = _enrich_candidates_with_selection(
        candidate_sets["initial_candidates"],
        selected_items,
    )
    reranked_candidates = _enrich_candidates_with_selection(
        candidate_sets["reranked_candidates"],
        selected_items,
    )
    latest_candidates = reranked_candidates or initial_candidates
    candidate_source = "reranked_candidates" if reranked_candidates else (
        "initial_candidates" if initial_candidates else "none"
    )
    report_jobs = _get_recommendation_report_jobs(db, session_id=session_id)
    report_status = _build_recommendation_report_status(reports=reports, jobs=report_jobs)
    selected_status = _build_recommendation_selected_status(selected_items)
    agent_status = _build_recommendation_agent_status(
        db,
        session_id=session_id,
        messages=messages,
    )
    activity = _build_recommendation_activity(
        session=session,
        messages=messages,
        reports=reports,
        report_status=report_status,
    )
    return {
        "session": session,
        "display": _recommendation_session_display(session, messages=messages),
        "candidate_counts": {
            "initial": len(initial_candidates),
            "reranked": len(reranked_candidates),
            "latest": len(latest_candidates),
        },
        "latest_candidates_preview": latest_candidates[:preview_limit],
        "candidate_source": candidate_source,
        "report_status": report_status,
        "selected_status": selected_status,
        "agent_status": agent_status,
        "activity": activity,
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
    return (
        (summary.get("agent_status") or {}).get("status") in {"queued", "running", "retry_waiting", "writing"}
        or summary["report_status"].get("status") in {"queued", "running", "retry_waiting", "generating"}
    )


def _build_recommendation_agent_status(
    db: Session,
    *,
    session_id: UUID,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Terminal state for the latest Agent turn, including the Writer gap.

    Writer runs in the SSE request rather than a background job.  A brief with
    no answer/abort therefore remains ``writing`` even after the Agent job has
    succeeded; this is the server-side signal used by every tab's yellow dot.
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
    if status_filter == "failed":
        return [
            summary
            for summary in summaries
            if summary["report_status"].get("status") == "failed"
        ]
    if status_filter == "generated":
        return [summary for summary in summaries if summary["report_status"].get("status") == "generated"]
    if status_filter == "selected":
        return [
            summary
            for summary in summaries
            if int(summary["selected_status"].get("active_count") or 0) > 0
        ]
    if status_filter == "idle":
        return [
            summary
            for summary in summaries
            if not _recommendation_session_is_processing(summary)
            and summary["report_status"].get("status") != "failed"
        ]
    return summaries


def _recommendation_session_polling_hint(
    summary: dict[str, Any],
    *,
    session_id: UUID,
) -> dict[str, Any]:
    enabled = _recommendation_session_is_processing(summary)
    watched_jobs = []
    latest_report_job = summary["report_status"].get("latest_job")
    if latest_report_job and latest_report_job.get("status") in {"queued", "running", "retry_waiting"}:
        watched_jobs.append(
            {
                "job_type": latest_report_job.get("job_type"),
                "job_id": latest_report_job.get("id"),
                "queue_name": latest_report_job.get("queue_name"),
                "status": latest_report_job.get("status"),
            }
        )
    return {
        "enabled": enabled,
        "interval_ms": 3000 if enabled else None,
        "endpoint": f"/api/v1/recommendations/sessions/{session_id}/page-state",
        "status_endpoint": f"/api/v1/recommendations/sessions/{session_id}/status",
        "bundle_endpoint": f"/api/v1/recommendations/sessions/{session_id}/bundle",
        "watched_jobs": watched_jobs,
        "reason": "report_running" if enabled else "terminal_or_not_requested",
    }


def _recommendation_page_overview(
    recent_summaries: list[dict[str, Any]],
    running_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_count = 0
    generated_report_count = 0
    selected_count = 0
    for summary in recent_summaries:
        if summary["report_status"].get("status") == "failed":
            failed_count += 1
        generated_report_count += int(summary["report_status"].get("generated_count") or 0)
        selected_count += int(summary["selected_status"].get("active_count") or 0)
    return {
        "recent_session_count": len(recent_summaries),
        "running_session_count": len(running_summaries),
        "failed_session_count": failed_count,
        "generated_report_count": generated_report_count,
        "active_selected_item_count": selected_count,
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


def _build_recommendation_report_status(
    *,
    reports: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_report = reports[0] if reports else None
    latest_job = jobs[0] if jobs else None
    status_counts = _count_by_key(reports, "status")
    job_status = latest_job.get("status") if latest_job else None
    report_status = latest_report.get("status") if latest_report else None
    running_statuses = {"queued", "running", "retry_waiting"}
    if job_status in running_statuses or report_status == "generating":
        aggregate_status = "generating"
    elif job_status == "failed" or report_status == "failed":
        aggregate_status = "failed"
    elif status_counts.get("generated", 0) > 0:
        aggregate_status = "generated"
    else:
        aggregate_status = "not_requested"
    return {
        "requested": bool(reports or jobs),
        "status": aggregate_status,
        "latest_report": _compact_recommendation_report(latest_report) if latest_report else None,
        "latest_job": _compact_background_job(latest_job) if latest_job else None,
        "total_count": len(reports),
        "generated_count": int(status_counts.get("generated", 0)),
        "generating_count": int(status_counts.get("generating", 0)),
        "failed_count": int(status_counts.get("failed", 0)),
        "archived_count": int(status_counts.get("archived", 0)),
    }


def _build_recommendation_selected_status(selected_items: list[dict[str, Any]]) -> dict[str, Any]:
    active_items = [item for item in selected_items if item.get("canceled_at") is None]
    return {
        "active_count": len(active_items),
        "canceled_count": len(selected_items) - len(active_items),
        "latest_selected_at": active_items[0].get("selected_at") if active_items else None,
        "latest_item": _compact_selected_item(active_items[0]) if active_items else None,
    }


def _build_recommendation_activity(
    *,
    session: dict[str, Any],
    messages: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    report_status: dict[str, Any],
) -> dict[str, Any]:
    timestamps = [
        session.get("updated_at"),
        messages[-1].get("created_at") if messages else None,
        reports[0].get("created_at") if reports else None,
        (report_status.get("latest_job") or {}).get("finished_at")
        or (report_status.get("latest_job") or {}).get("started_at")
        or (report_status.get("latest_job") or {}).get("created_at"),
    ]
    latest_activity_at = max([value for value in timestamps if value] or [None])
    return {
        "latest_activity_at": latest_activity_at,
        "message_count": len(messages),
        "report_count": len(reports),
        "last_message": _compact_recommendation_message(messages[-1]) if messages else None,
    }


def _get_recommendation_report_jobs(db: Session, *, session_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, job_type, status, priority, queue_name, entity_type, entity_id,
              result_json, error_code, error_message, attempt_count, max_attempts,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'recommendation_report_generate'
              and (
                payload_json ->> 'session_id' = :session_id_text
                or entity_id in (
                  select id
                  from recommendation_report
                  where session_id = :session_id
                    and team_id = :team_id
                    and workspace_id = :workspace_id
                )
              )
            order by created_at desc
            limit 50
            """
        ),
        {
            "session_id": session_id,
            "session_id_text": str(session_id),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _compact_recommendation_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": report.get("id"),
        "session_id": report.get("session_id"),
        "report_type": report.get("report_type"),
        "title": report.get("title"),
        "status": report.get("status"),
        "generated_by_model": report.get("generated_by_model"),
        "prompt_version": report.get("prompt_version"),
        "created_at": report.get("created_at"),
        "metadata_json": report.get("metadata_json"),
    }


def _compact_background_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job.get("id"),
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "queue_name": job.get("queue_name"),
        "entity_type": job.get("entity_type"),
        "entity_id": job.get("entity_id"),
        "error_code": job.get("error_code"),
        "error_message": job.get("error_message"),
        "attempt_count": job.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "updated_at": job.get("updated_at"),
    }


def _compact_selected_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "seller_target_id": item.get("seller_target_id"),
        "seller_target_name": item.get("seller_target_name"),
        "buyer_intent_id": item.get("buyer_intent_id"),
        "buyer_intent_name": item.get("buyer_intent_name"),
        "buyer_party_id": item.get("buyer_party_id"),
        "buyer_name": item.get("buyer_name"),
        "recommendation_level": item.get("recommendation_level"),
        "selected_at": item.get("selected_at"),
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


def _list_selected_items(
    db: Session,
    *,
    session_id: UUID,
    include_canceled: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    where = ["ri.session_id = :session_id", "ri.team_id = :team_id", "ri.workspace_id = :workspace_id"]
    if not include_canceled:
        where.append("ri.canceled_at is null")
    rows = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where {' and '.join(where)}
            order by ri.selected_at desc
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


def _list_recommendation_reports(
    db: Session,
    *,
    session_id: UUID,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            select {_report_select_columns()}
            from recommendation_report
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at desc
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


def _extract_recommendation_candidate_sets(
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    initial_candidates: list[dict[str, Any]] = []
    reranked_candidates: list[dict[str, Any]] = []
    initial_message_id: str | None = None
    reranked_message_id: str | None = None
    reranked_at: str | None = None

    for message in messages:
        if message.get("content_type") != "json":
            continue

        content = _json_loads(message.get("content") or "{}")
        metadata = message.get("metadata_json") if isinstance(message.get("metadata_json"), dict) else {}
        message_type = str(
            metadata.get("message_type")
            or content.get("message_type")
            or _infer_recommendation_candidate_message_type(content)
            or ""
        )
        candidates = content.get("candidates")
        if not isinstance(candidates, list):
            continue

        if message_type == "reranked_candidates":
            reranked_candidates = _normalize_candidates(candidates)
            reranked_message_id = str(message["id"])
            reranked_at = message.get("created_at")
        elif message_type == "initial_candidates":
            initial_candidates = _normalize_candidates(candidates)
            initial_message_id = str(message["id"])

    return {
        "initial_candidates": initial_candidates,
        "reranked_candidates": reranked_candidates,
        "initial_message_id": initial_message_id,
        "reranked_message_id": reranked_message_id,
        "reranked_at": reranked_at,
    }


def _infer_recommendation_candidate_message_type(content: dict[str, Any]) -> str | None:
    candidates = content.get("candidates")
    if not isinstance(candidates, list):
        return None
    if not candidates:
        return "initial_candidates"

    has_rerank_score = any(
        isinstance(candidate, dict)
        and isinstance(candidate.get("evidence_json"), dict)
        and isinstance(candidate["evidence_json"].get("score"), dict)
        and candidate["evidence_json"]["score"].get("rerank_score") is not None
        for candidate in candidates
    )
    return "reranked_candidates" if has_rerank_score else "initial_candidates"


def _normalize_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    normalized_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            normalized_candidates.append(dict(candidate))
    return normalized_candidates


def _enrich_candidates_with_selection(
    candidates: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected_by_pair = {
        _candidate_pair_key(selected_item): selected_item
        for selected_item in selected_items
        if selected_item.get("canceled_at") is None
    }
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        selected_item = selected_by_pair.get(_candidate_pair_key(item))
        if selected_item is not None:
            item["selected"] = True
            item["selected_item_id"] = selected_item.get("id")
            item["selected_at"] = selected_item.get("selected_at")
        else:
            item["selected"] = False
            item["selected_item_id"] = None
            item["selected_at"] = None
        enriched.append(_with_frontend_candidate_fields(item))
    return enriched


def _enrich_candidates_for_frontend(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_with_frontend_candidate_fields(candidate) for candidate in candidates]


def _with_frontend_candidate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    item = dict(candidate)
    mode = str(item.get("mode") or "")
    if mode == "buyer_to_target":
        primary_entity_type = "seller_target"
        primary_entity_id = item.get("seller_target_id")
        counterpart_entity_type = "buyer_intent"
        counterpart_entity_id = item.get("buyer_intent_id")
        title = item.get("seller_target_name")
        subtitle = _join_display_parts([item.get("buyer_intent_name"), item.get("buyer_name")])
        action_label = "add_target_to_recommendation"
    else:
        primary_entity_type = "buyer_intent"
        primary_entity_id = item.get("buyer_intent_id")
        counterpart_entity_type = "seller_target"
        counterpart_entity_id = item.get("seller_target_id")
        title = item.get("buyer_intent_name") or item.get("buyer_name")
        subtitle = _join_display_parts([item.get("buyer_name"), item.get("seller_target_name")])
        action_label = "add_buyer_to_recommendation"

    score_breakdown = _candidate_score_breakdown(item)
    display_meta = _candidate_display_meta(item, score_breakdown)
    display_badges = _candidate_display_badges(item, score_breakdown)
    item.update(
        {
            "primary_entity_type": primary_entity_type,
            "primary_entity_id": primary_entity_id,
            "counterpart_entity_type": counterpart_entity_type,
            "counterpart_entity_id": counterpart_entity_id,
            "display_title": title,
            "display_subtitle": subtitle,
            "display_meta": display_meta,
            "display_badges": display_badges,
            "score_breakdown": score_breakdown,
            "card_json": {
                "title": title,
                "subtitle": subtitle,
                "meta": display_meta,
                "badges": display_badges,
                "score": item.get("score"),
                "recommendation_level": item.get("recommendation_level"),
                "selected": bool(item.get("selected")),
                "action_label": action_label,
                "primary_entity_type": primary_entity_type,
                "primary_entity_id": str(primary_entity_id) if primary_entity_id else None,
                "counterpart_entity_type": counterpart_entity_type,
                "counterpart_entity_id": str(counterpart_entity_id) if counterpart_entity_id else None,
            },
        }
    )
    return item


def _candidate_score_breakdown(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
    return {
        "rule_score": score_json.get("rule_score"),
        "rerank_score": score_json.get("rerank_score"),
        "rerank_boost": score_json.get("rerank_boost"),
        "rerank_model": score_json.get("rerank_model"),
        "hard_mismatches": score_json.get("hard_mismatches") or [],
        "excluded_hit": score_json.get("excluded_hit"),
        "deep_eval_grade": score_json.get("deep_eval_grade"),
        "deep_eval_model": score_json.get("deep_eval_model"),
        "final_score": score_json.get("final_score") or candidate.get("score"),
    }


def _candidate_display_meta(candidate: dict[str, Any], score_breakdown: dict[str, Any]) -> list[str]:
    meta = [
        f"score {candidate.get('score')}",
        f"level {candidate.get('recommendation_level')}",
    ]
    if score_breakdown.get("rerank_score") is not None:
        meta.append(f"rerank {float(score_breakdown['rerank_score']):.2f}")
    return [item for item in meta if item and not item.endswith("None")]


def _candidate_display_badges(candidate: dict[str, Any], score_breakdown: dict[str, Any]) -> list[str]:
    badges = [str(candidate.get("recommendation_level") or "unrated")]
    if score_breakdown.get("deep_eval_grade"):
        badges.append(f"深评{score_breakdown['deep_eval_grade']}档")
    if score_breakdown.get("excluded_hit"):
        badges.append("命中排除项")
    elif score_breakdown.get("hard_mismatches"):
        badges.append("硬性条件不符")
    if score_breakdown.get("rerank_score") is not None:
        badges.append("reranked")
    if candidate.get("selected"):
        badges.append("selected")
    return badges


def _join_display_parts(parts: list[Any]) -> str | None:
    values = [str(part) for part in parts if part]
    return " / ".join(values) if values else None


def _candidate_pair_key(item: dict[str, Any]) -> tuple[str | None, str | None]:
    seller_target_id = item.get("seller_target_id")
    buyer_intent_id = item.get("buyer_intent_id")
    return (
        str(seller_target_id) if seller_target_id else None,
        str(buyer_intent_id) if buyer_intent_id else None,
    )


def _get_active_selected_item_for_pair(
    db: Session,
    *,
    session_id: UUID,
    buyer_intent_id: UUID | None,
    seller_target_id: UUID | None,
) -> dict[str, Any] | None:
    if buyer_intent_id is None or seller_target_id is None:
        return None
    row = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where ri.session_id = :session_id
              and ri.buyer_intent_id = :buyer_intent_id
              and ri.seller_target_id = :seller_target_id
              and ri.team_id = :team_id
              and ri.workspace_id = :workspace_id
              and ri.canceled_at is null
            order by ri.selected_at desc
            limit 1
            """
        ),
        {
            "session_id": session_id,
            "buyer_intent_id": buyer_intent_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _list_selected_items_for_report(
    db: Session,
    *,
    session_id: UUID,
    selected_item_ids: list[UUID] | None,
) -> list[dict[str, Any]]:
    where = [
        "ri.session_id = :session_id",
        "ri.team_id = :team_id",
        "ri.workspace_id = :workspace_id",
        "ri.canceled_at is null",
    ]
    params: dict[str, Any] = {
        "session_id": session_id,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    statement = text(
        f"""
        select {_selected_item_select_columns()}
        from recommendation_selected_item ri
        left join seller_target st on st.id = ri.seller_target_id
        left join buyer_intent bi on bi.id = ri.buyer_intent_id
        left join buyer_party bp on bp.id = ri.buyer_party_id
        where {' and '.join(where)}
        order by ri.rank_at_selection nulls last, ri.selected_at asc
        """
    )
    if selected_item_ids is not None:
        if not selected_item_ids:
            return []
        where.append("ri.id in :selected_item_ids")
        params["selected_item_ids"] = tuple(selected_item_ids)
        statement = text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where {' and '.join(where)}
            order by ri.rank_at_selection nulls last, ri.selected_at asc
            """
        ).bindparams(bindparam("selected_item_ids", expanding=True))

    rows = db.execute(statement, params).mappings().all()
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


def _annotate_candidate_relations(db: Session, result: dict[str, Any], *, mode: str) -> dict[str, Any]:
    """Mark existing relations and both directions of anonymous deep progress.

    Recommendation and progress meet here: a candidate the buyer is already
    working is shown apart from fresh ones instead of silently re-ranked, and a
    target or intent deep in progress elsewhere is flagged without naming the
    other relation or exposing its stage.
    """
    candidates = result.get("candidates") or []
    if not candidates:
        return result

    pairs = [
        (str(candidate["buyer_intent_id"]), str(candidate["seller_target_id"]))
        for candidate in candidates
        if candidate.get("buyer_intent_id") and candidate.get("seller_target_id")
    ]
    if not pairs:
        return result

    intent_ids = sorted({intent for intent, _ in pairs})
    target_ids = sorted({target for _, target in pairs})
    rows = db.execute(
        text(
            """
            select id, buyer_intent_id::text as buyer_intent_id,
                   seller_target_id::text as seller_target_id, status
            from buyer_seller_relation
            where team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
              and buyer_intent_id in :intent_ids
              and seller_target_id in :target_ids
            """
        ).bindparams(
            bindparam("intent_ids", expanding=True),
            bindparam("target_ids", expanding=True),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "intent_ids": intent_ids,
            "target_ids": target_ids,
        },
    ).mappings().all()

    exact: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        exact[(row["buyer_intent_id"], row["seller_target_id"])] = {"id": row["id"], "status": row["status"]}

    # Seller-side warning: do not constrain by candidate intent IDs, otherwise
    # the query hides exactly the “other buyer is in due diligence” relation.
    target_deep_rows = db.execute(
        text(
            """
            select buyer_intent_id::text as buyer_intent_id,
                   seller_target_id::text as seller_target_id
            from buyer_seller_relation
            where team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
              and seller_target_id in :target_ids
              and status in :deep_statuses
            """
        ).bindparams(
            bindparam("target_ids", expanding=True),
            bindparam("deep_statuses", expanding=True),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "target_ids": target_ids,
            "deep_statuses": list(DEEP_PROGRESS_STATUSES),
        },
    ).mappings().all()
    deep_intents_by_target: dict[str, set[str]] = {}
    for row in target_deep_rows:
        deep_intents_by_target.setdefault(row["seller_target_id"], set()).add(row["buyer_intent_id"])

    # Buyer-side warning is the inverse dimension: this intent may already be
    # in due diligence or agreement with another target.
    intent_deep_rows = db.execute(
        text(
            """
            select buyer_intent_id::text as buyer_intent_id,
                   seller_target_id::text as seller_target_id
            from buyer_seller_relation
            where team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
              and buyer_intent_id in :intent_ids
              and status in :deep_statuses
            """
        ).bindparams(
            bindparam("intent_ids", expanding=True),
            bindparam("deep_statuses", expanding=True),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "intent_ids": intent_ids,
            "deep_statuses": list(DEEP_PROGRESS_STATUSES),
        },
    ).mappings().all()
    deep_targets_by_intent: dict[str, set[str]] = {}
    for row in intent_deep_rows:
        deep_targets_by_intent.setdefault(row["buyer_intent_id"], set()).add(row["seller_target_id"])

    for candidate in candidates:
        intent_id = str(candidate.get("buyer_intent_id") or "")
        target_id = str(candidate.get("seller_target_id") or "")
        relation = exact.get((intent_id, target_id))
        candidate["relation_id"] = str(relation["id"]) if relation else None
        candidate["relation_status"] = relation["status"] if relation else None
        seller_has_other = bool(
            deep_intents_by_target.get(target_id, set()) - {intent_id}
        )
        buyer_has_other = bool(
            deep_targets_by_intent.get(intent_id, set()) - {target_id}
        )
        candidate["seller_target_has_other_deep_progress"] = seller_has_other
        candidate["buyer_intent_has_other_deep_progress"] = buyer_has_other
        # Compatibility for clients deployed before the directional fields:
        # choose the correct meaning for the current recommendation direction.
        candidate["deep_progress_elsewhere"] = (
            seller_has_other if mode == "buyer_to_target" else buyer_has_other
        )
    return result


def _annotate_candidate_ownership(
    db: Session,
    result: dict[str, Any],
    *,
    mode: str,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Overlay the primary candidate's live owner and operation boundary."""
    candidates = result.get("candidates") or []
    if not candidates:
        return result

    if mode == "buyer_to_target":
        entity_ids = sorted(
            {str(candidate["seller_target_id"]) for candidate in candidates if candidate.get("seller_target_id")}
        )
        table = "seller_target"
        id_key = "seller_target_id"
        prefix = "seller_target"
    else:
        entity_ids = sorted(
            {str(candidate["buyer_intent_id"]) for candidate in candidates if candidate.get("buyer_intent_id")}
        )
        table = "buyer_intent"
        id_key = "buyer_intent_id"
        prefix = "buyer_intent"
    if not entity_ids:
        return result

    rows = db.execute(
        text(
            f"""
            select entity.id::text as entity_id,
                   entity.owner_user_id::text as owner_user_id,
                   owner.name as owner_name
            from {table} entity
            left join app_user owner on owner.id = entity.owner_user_id
            where entity.team_id = :team_id
              and entity.workspace_id = :workspace_id
              and entity.deleted_at is null
              and entity.id in :entity_ids
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_ids": entity_ids,
        },
    ).mappings().all()
    ownership = {row["entity_id"]: row for row in rows}
    current_user_id = str(current_user.user_id)

    for candidate in candidates:
        row = ownership.get(str(candidate.get(id_key) or ""))
        owner_user_id = str(row["owner_user_id"]) if row and row.get("owner_user_id") else None
        owned_by_current_user = owner_user_id == current_user_id
        candidate[f"{prefix}_owner_user_id"] = owner_user_id
        candidate[f"{prefix}_owner_name"] = row.get("owner_name") if row else None
        candidate[f"{prefix}_owned_by_current_user"] = owned_by_current_user
        candidate[f"{prefix}_operation_allowed"] = current_user.is_admin or owned_by_current_user
    return result


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


def _get_selected_item_or_404(db: Session, selected_item_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_selected_item_select_columns()}
            from recommendation_selected_item ri
            left join seller_target st on st.id = ri.seller_target_id
            left join buyer_intent bi on bi.id = ri.buyer_intent_id
            left join buyer_party bp on bp.id = ri.buyer_party_id
            where ri.id = :selected_item_id
              and ri.team_id = :team_id
              and ri.workspace_id = :workspace_id
            """
        ),
        {
            "selected_item_id": selected_item_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected item not found.")
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


def _optional_uuid_from_mapping(value: Any, key: str) -> UUID | None:
    if not isinstance(value, dict) or not value.get(key):
        return None
    return _optional_uuid(value[key])


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _refresh_session_selected_count(db: Session, session_id: UUID) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set selected_count = (
                  select count(*)
                  from recommendation_selected_item
                  where session_id = :session_id
                    and canceled_at is null
                ),
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _enqueue_recommendation_report_job(
    db: Session,
    *,
    report_id: UUID,
    session_id: UUID,
    selected_item_ids: list[str],
) -> UUID:
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'recommendation_report_generate', 120, 'llm',
              'recommendation_report', :report_id, :idempotency_key, :payload_json,
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
            "report_id": report_id,
            "idempotency_key": f"recommendation_report_generate:{report_id}",
            "payload_json": {
                "report_id": str(report_id),
                "session_id": str(session_id),
                "selected_item_ids": selected_item_ids,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "recommendation_report_job_api"},
        },
    ).mappings().one()
    return row["id"]


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
    """
    for message in _agent_turn_messages(db, session_id, turn_id):
        if message["message_type"] == "agent_answer":
            return {
                "id": message.get("id"),
                "markdown": message["decoded_content"].get("markdown") or "",
                "duration_ms": int(message["decoded_content"].get("duration_ms") or 0),
            }
    return None


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


def insert_agent_answer_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    markdown: str,
    model_name: str | None,
    generation_mode: str,
    duration_ms: int = 0,
) -> UUID | None:
    """Persist the answer only if the turn has not been stopped.

    This check shares the turn advisory lock with the abort marker. It is the
    final database guard for an SSE that started before another tab stopped the
    turn; the marker wins and no answer row is written.
    """
    _lock_agent_turn_terminal_write(db, session_id, turn_id)
    if agent_turn_aborted(db, session_id, turn_id):
        return None
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
    return row["id"]


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
    """Turns that actually completed, oldest first.

    A turn only counts once both halves exist. A stopped turn, or one whose
    write-up never landed, is dropped whole: half a turn reads to the model as
    an unanswered question and pulls the next turn into answering it again.
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

    complete = [
        turns[turn_id]
        for turn_id in order
        if not turns[turn_id]["aborted"] and turns[turn_id]["question"] and turns[turn_id]["answer"]
    ]
    return complete[-AGENT_HISTORY_MAX_TURNS:]


def agent_history_context(db: Session, session_id: UUID) -> str:
    """Previous turns, verbatim, tagged so the agent cannot mistake them for now.

    Verbatim rather than summarised on purpose: the consultant's follow-up
    ("把第二家换掉") is written against the exact words on their screen, so
    anything the agent reads that differs from what the user read is a chance
    to misunderstand. Tool results stay out — the agent re-screens every turn
    and replaying old result sets would only spend context on stale numbers.
    """
    turns = _agent_history_turns(db, session_id)
    blocks: list[str] = []
    budget = AGENT_HISTORY_MAX_CHARS
    # 从最近一轮往回收，装不下就停 —— 丢掉的永远是最旧的整轮。
    for turn in reversed(turns):
        block = f"<user>：{turn['question']}\n<AI>：{turn['answer']}"
        if len(block) > budget:
            break
        budget -= len(block)
        blocks.append(block)
    if not blocks:
        return ""
    return "<history_context>\n{}\n</history_context>".format("\n\n".join(reversed(blocks)))


def _ensure_recommendation_report_visible(db: Session, current_user: CurrentUser, report_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from recommendation_report rr
            where rr.id = :report_id
              and rr.team_id = :team_id
              and rr.workspace_id = :workspace_id
              and {recommendation_report_visible_sql("rr")}
            """
        ),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation report not found.")


def _refresh_session_report_count(db: Session, session_id: UUID) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set report_count = (
                  select count(*)
                  from recommendation_report
                  where session_id = :session_id
                    and status <> 'archived'
                ),
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


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


def _session_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_session_select_columns()}")


def _message_select_columns() -> str:
    return """
      id, session_id, role, content, content_type,
      metadata_json, created_at::text as created_at
    """


def _message_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_message_select_columns()}")


def _selected_item_select_columns() -> str:
    return """
      ri.id, ri.session_id, ri.mode,
      ri.seller_target_id, st.target_name as seller_target_name,
      ri.buyer_intent_id, bi.intent_name as buyer_intent_name,
      ri.buyer_party_id, bp.buyer_name,
      ri.rank_at_selection, ri.recommendation_level, ri.match_summary,
      ri.risk_summary, ri.gap_summary, ri.reason_snapshot,
      ri.evidence_snapshot_json, ri.selected_at::text as selected_at,
      ri.canceled_at::text as canceled_at, ri.selected_by, ri.metadata_json
    """


def _selected_item_returning_statement(prefix_sql: str):
    return text(
        f"""
        with changed as (
          {prefix_sql}
          returning *
        )
        select
          changed.id, changed.session_id, changed.mode,
          changed.seller_target_id, st.target_name as seller_target_name,
          changed.buyer_intent_id, bi.intent_name as buyer_intent_name,
          changed.buyer_party_id, bp.buyer_name,
          changed.rank_at_selection, changed.recommendation_level,
          changed.match_summary, changed.risk_summary, changed.gap_summary,
          changed.reason_snapshot, changed.evidence_snapshot_json,
          changed.selected_at::text as selected_at,
          changed.canceled_at::text as canceled_at,
          changed.selected_by, changed.metadata_json
        from changed
        left join seller_target st on st.id = changed.seller_target_id
        left join buyer_intent bi on bi.id = changed.buyer_intent_id
        left join buyer_party bp on bp.id = changed.buyer_party_id
        """
    )


def _report_select_columns() -> str:
    return """
      id, session_id, report_type, selected_item_ids_json, title,
      markdown_content, file_path, file_format, status,
      generated_by_model, prompt_version,
      created_at::text as created_at, metadata_json
    """


def _report_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_report_select_columns()}")


def _recommendation_level(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "recommended"
    if score >= 35:
        return "possible"
    return "weak"


def _summary_text(items: list[str], *, fallback: str | None = None) -> str | None:
    if items:
        return "；".join(items[:4])
    return fallback


def _yes_like(value: Any) -> bool:
    return str(value or "").lower() in {"yes", "likely", "true", "1"}


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
