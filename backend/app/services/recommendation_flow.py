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
from backend.app.services.industry_taxonomy import classify_terms, load_term_levels
from backend.app.services.recommendation_conditions import (
    condition_effect,
    merge_scenario_into_anchor,
    normalize_condition_effects,
    normalize_scenario_fields,
    suppress_pending_confirmation_fields,
)
from backend.app.services.relation_flow import DEEP_PROGRESS_STATUSES

# 分片并发后单请求不再承担全部候选，预算可以放宽到三片（见 handlers/recommendation.py）。
DEEP_EVAL_CANDIDATE_LIMIT = 45


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
    rerank_job = _get_latest_recommendation_rerank_job(db, session_id=session_id)
    rerank_status = _build_recommendation_rerank_status(
        rerank_job=rerank_job,
        reranked_candidates=reranked_candidates,
        candidate_sets=candidate_sets,
    )
    return {
        "session": session,
        "messages": messages,
        "initial_candidates": initial_candidates,
        "reranked_candidates": reranked_candidates,
        "latest_candidates": latest_candidates,
        "candidate_source": candidate_source,
        "rerank_status": rerank_status,
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
                  when job.job_type in (
                         'recommendation_deep_eval', 'recommendation_rerank', 'recommendation_agent'
                       )
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
                      'recommendation_deep_eval', 'recommendation_rerank',
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
    rerank_job = _get_latest_recommendation_rerank_job(db, session_id=session_id)
    rerank_status = _build_recommendation_rerank_status(
        rerank_job=rerank_job,
        reranked_candidates=reranked_candidates,
        candidate_sets=candidate_sets,
    )
    report_jobs = _get_recommendation_report_jobs(db, session_id=session_id)
    report_status = _build_recommendation_report_status(reports=reports, jobs=report_jobs)
    selected_status = _build_recommendation_selected_status(selected_items)
    activity = _build_recommendation_activity(
        session=session,
        messages=messages,
        reports=reports,
        rerank_status=rerank_status,
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
        "rerank_status": rerank_status,
        "report_status": report_status,
        "selected_status": selected_status,
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
        summary["rerank_status"].get("status") in {"queued", "running", "retry_waiting"}
        or summary["report_status"].get("status") in {"queued", "running", "retry_waiting", "generating"}
    )


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
            if summary["rerank_status"].get("status") == "failed"
            or summary["report_status"].get("status") == "failed"
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
            and summary["rerank_status"].get("status") != "failed"
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
    rerank_job_id = summary["rerank_status"].get("job_id")
    if rerank_job_id and summary["rerank_status"].get("status") in {"queued", "running", "retry_waiting"}:
        watched_jobs.append(
            {
                "job_type": "recommendation_deep_eval",
                "job_id": rerank_job_id,
                "queue_name": summary["rerank_status"].get("queue_name"),
                "status": summary["rerank_status"].get("status"),
            }
        )
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
        "reason": "rerank_or_report_running" if enabled else "terminal_or_not_requested",
    }


def _recommendation_page_overview(
    recent_summaries: list[dict[str, Any]],
    running_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_count = 0
    generated_report_count = 0
    selected_count = 0
    for summary in recent_summaries:
        if summary["rerank_status"].get("status") == "failed" or summary["report_status"].get("status") == "failed":
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
    rerank_status: dict[str, Any],
    report_status: dict[str, Any],
) -> dict[str, Any]:
    timestamps = [
        session.get("updated_at"),
        messages[-1].get("created_at") if messages else None,
        reports[0].get("created_at") if reports else None,
        rerank_status.get("finished_at") or rerank_status.get("started_at") or rerank_status.get("created_at"),
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


def _get_latest_recommendation_rerank_job(
    db: Session,
    *,
    session_id: UUID,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, status, queue_name, error_code, error_message,
              attempt_count, max_attempts, run_after::text as run_after,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at,
              result_json, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type in ('recommendation_deep_eval', 'recommendation_rerank')
              and entity_type = 'recommendation_session'
              and entity_id = :session_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def _build_recommendation_rerank_status(
    *,
    rerank_job: dict[str, Any] | None,
    reranked_candidates: list[dict[str, Any]],
    candidate_sets: dict[str, Any],
) -> dict[str, Any]:
    if rerank_job is None:
        return {
            "requested": False,
            "status": "not_requested",
            "job_id": None,
            "queue_name": None,
            "candidate_count": 0,
            "reranked_at": None,
            "error_code": None,
            "error_message": None,
        }

    return {
        "requested": True,
        "status": rerank_job.get("status"),
        "job_id": str(rerank_job["id"]),
        "queue_name": rerank_job.get("queue_name"),
        "candidate_count": len(reranked_candidates),
        "message_id": candidate_sets.get("reranked_message_id"),
        "reranked_at": candidate_sets.get("reranked_at") or rerank_job.get("finished_at"),
        "created_at": rerank_job.get("created_at"),
        "started_at": rerank_job.get("started_at"),
        "finished_at": rerank_job.get("finished_at"),
        "attempt_count": rerank_job.get("attempt_count"),
        "max_attempts": rerank_job.get("max_attempts"),
        "error_code": rerank_job.get("error_code"),
        "error_message": rerank_job.get("error_message"),
    }


def _get_rerank_anchor_for_session(db: Session, session: dict[str, Any]) -> dict[str, Any]:
    if session["mode"] == "buyer_to_target":
        buyer_intent_id = _optional_uuid(session.get("buyer_intent_id"))
        if buyer_intent_id is not None:
            return _get_buyer_intent_anchor(db, buyer_intent_id)
    if session["mode"] == "target_to_buyer":
        seller_target_id = _optional_uuid(session.get("seller_target_id"))
        if seller_target_id is not None:
            return _get_seller_target_anchor(db, seller_target_id)

    snapshot = session.get("latest_condition_snapshot_json")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    snapshot = session.get("initial_condition_snapshot_json")
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recommendation session has no rerank anchor.")


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


def _candidate_targets_for_intent(
    db: Session,
    intent: dict[str, Any],
    limit: int,
    disabled_scenario_ids: set[str] | None = None,
    semantic_query_lines: list[str] | None = None,
) -> dict[str, Any]:
    rows = db.execute(
        text(
            """
            select
              st.id as seller_target_id,
              st.target_name as seller_target_name,
              st.industry_l1,
              st.industry_l2,
              st.industry_pairs_json,
              st.location_province,
              st.location_city,
              st.location_district,
              st.current_revenue_yuan,
              st.current_net_profit_yuan,
              st.pe_ratio,
              st.valuation_yuan,
              st.asking_price_yuan,
              st.market_cap_yuan,
              st.current_debt_ratio,
              st.cash_flow_status,
              st.can_control,
              st.can_consolidate,
              st.transfer_ratio_max,
              st.transfer_ratio_min,
              st.listed_status,
              st.industry_l2,
              st.listing_market_region,
              st.current_total_profit_yuan,
              st.profitability_status,
              st.accepts_relocation,
              st.accepts_return_investment,
              st.management_retention_possible,
              st.risk_summary,
              st.gap_summary,
              st.business_summary,
              coalesce((
                select string_agg(section.content_text, E'\n')
                from entity_profile_section section
                where section.entity_type = 'seller_target'
                  and section.entity_id = st.id
                  and section.deleted_at is null
                  and section.review_status in ('accepted', 'auto_accepted')
              ), '') as profile_supplement_text,
              exists(
                select 1
                from buyer_intent_target_exclusion x
                where x.buyer_intent_id = :buyer_intent_id
                  and x.seller_target_id = st.id
                  and x.active = true
                  and x.canceled_at is null
              ) as is_excluded
            from seller_target st
            where st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
              and st.lifecycle_status = 'active'
            order by st.updated_at desc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": intent.get("id"),
        },
    ).mappings().all()

    intent = _with_resolved_exclusions(db, intent)
    scenarios = _effective_scenarios(db, intent, disabled_scenario_ids)
    scenario_ids = [scenario["id"] for scenario in scenarios if scenario["id"]]
    candidates: list[dict[str, Any]] = []
    excluded_count = 0
    conflict_count = 0
    semantic_terms = _semantic_query_terms(semantic_query_lines or [])
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            excluded_count += 1
            continue
        rule_score, evidence, gaps, meta = _score_against_scenarios(item, intent, scenarios)
        if meta["state"] == CANDIDATE_STATE_CONFLICT:
            conflict_count += 1
            continue
        score = rule_score
        candidate = _build_candidate_row(
            mode="buyer_to_target",
            seller_target_id=item["seller_target_id"],
            seller_target_name=item["seller_target_name"],
            buyer_intent_id=intent.get("id"),
            buyer_intent_name=intent.get("intent_name") or "临时买家需求",
            buyer_party_id=intent.get("buyer_party_id"),
            buyer_name=intent.get("buyer_name"),
            score=score,
            rule_score=rule_score,
            evidence=evidence,
            gaps=gaps,
            meta=meta,
            risk_summary=item.get("risk_summary") or item.get("gap_summary"),
            facts=_target_facts(item),
        )
        _apply_semantic_keyword_match(
            candidate,
            terms=semantic_terms,
            searchable_text="\n".join(
                str(value or "")
                for value in (
                    item.get("seller_target_name"),
                    item.get("business_summary"),
                    item.get("profile_supplement_text"),
                )
            ),
        )
        candidates.append(candidate)

    return _annotate_candidate_relations(
        db,
        _rank_and_report(
            candidates,
            limit=limit,
            scan_count=len(rows),
            excluded_count=excluded_count,
            conflict_count=conflict_count,
            scenario_ids=scenario_ids,
            scenarios=scenarios,
        ),
        mode="buyer_to_target",
    )


def search_targets_for_agent(
    db: Session,
    anchor: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """The agent's screening tool, bound to the same code path as everything else.

    Deliberately a thin public alias rather than a second implementation: the
    agent must not be able to screen by rules the rest of the system does not
    apply. `anchor` comes from `anchor_from_filters` and carries no id, so no
    scenario rows are loaded and the implicit single-scenario path is used.
    """
    return _candidate_targets_for_intent(db, anchor, limit)


def target_facts_for_agent(target_row: dict[str, Any]) -> dict[str, Any]:
    """Facts for a target the agent pulled by id rather than through screening.

    Same formatter the screened candidates go through, so a target that entered
    by id quotes identical numbers to one that came out of the funnel.
    """
    return _target_facts(target_row)


def _candidate_intents_for_target(
    db: Session,
    target: dict[str, Any],
    limit: int,
    semantic_query_lines: list[str] | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "seller_target_id": target.get("id"),
    }
    where = [
        "bi.team_id = :team_id",
        "bi.workspace_id = :workspace_id",
        "bi.deleted_at is null",
        "bi.status = 'active'",
    ]
    scenario_exists = """
        exists(
          select 1 from buyer_intent_scenario bis_prefilter
          where bis_prefilter.buyer_intent_id = bi.id
            and bis_prefilter.team_id = bi.team_id
            and bis_prefilter.workspace_id = bi.workspace_id
            and bis_prefilter.deleted_at is null
            and bis_prefilter.active = true
        )
    """
    pending_field = lambda field: f"""
        exists(
          select 1 from jsonb_array_elements(bi.needs_confirmation_json) pending
          where pending ->> 'field' = '{field}'
        )
    """

    target_l1_values, _ = _target_industry_values(target)
    if target_l1_values:
        params["target_industry_l1"] = list(target_l1_values)
        where.append(
            f"""(
              {scenario_exists}
              or {pending_field('industries_json')}
              or coalesce(bi.condition_effects_json ->> 'industries_json', 'required') <> 'required'
              or jsonb_array_length(bi.industries_json) = 0
              or exists(
                select 1 from jsonb_array_elements_text(bi.industries_json) required_industry(value)
                where required_industry.value = any(:target_industry_l1)
              )
            )"""
        )

    target_revenue = _optional_decimal(target.get("current_revenue_yuan"))
    if target_revenue is not None:
        params["target_revenue_yuan"] = target_revenue
        where.append(
            f"""(
              {scenario_exists}
              or {pending_field('min_revenue_yuan')}
              or coalesce(bi.condition_effects_json ->> 'min_revenue_yuan', 'required') <> 'required'
              or bi.min_revenue_yuan is null
              or bi.min_revenue_yuan <= :target_revenue_yuan
            )"""
        )

    if str(target.get("can_control") or "").strip().lower() == "no":
        where.append(
            f"""(
              {scenario_exists}
              or {pending_field('requires_control')}
              or coalesce(bi.condition_effects_json ->> 'requires_control', 'required') <> 'required'
              or bi.requires_control not in ('yes', 'likely')
              or bi.accepts_minority_investment in ('yes', 'likely')
            )"""
        )

    where_sql = " and ".join(where)
    rows = db.execute(
        text(
            f"""
            select
              bi.id as buyer_intent_id,
              bi.intent_name as buyer_intent_name,
              bi.buyer_party_id,
              bp.buyer_name,
              bi.industry_primary,
              bi.industry_secondary,
              bi.industries_json,
              bi.industry_l2_json,
              bi.excluded_industries_json,
              bi.region_scope_summary, bi.region_constraints_json,
              bi.min_revenue_yuan,
              bi.min_net_profit_yuan,
              bi.min_total_profit_yuan,
              bi.max_pe,
              bi.max_ps,
              bi.min_net_margin,
              bi.min_gross_margin,
              bi.min_valuation_yuan,
              bi.max_valuation_yuan,
              bi.min_market_cap_yuan,
              bi.max_market_cap_yuan,
              bi.max_debt_ratio,
              bi.requires_control,
              bi.requires_consolidation,
              bi.accepts_minority_investment,
              bi.desired_equity_ratio_min,
              bi.desired_equity_ratio_max,
              bi.preferred_listed_status, bi.acceptable_listed_status_json,
              bi.condition_effects_json,
              bi.listing_market_region,
              bi.acceptable_cash_flow_status_json,
              bi.acceptable_profitability_status_json,
              bi.requires_relocation,
              bi.requires_return_investment,
              bi.requires_team_retention,
              bi.major_risk_tolerance_summary,
              bi.raw_requirement_text,
              bi.intent_summary,
              bi.industry_focus_tags_json,
              bi.needs_confirmation_json,
              exists(
                select 1
                from buyer_intent_target_exclusion x
                where x.buyer_intent_id = bi.id
                  and x.seller_target_id = :seller_target_id
                  and x.active = true
                  and x.canceled_at is null
              ) as is_excluded
            from buyer_intent bi
            left join buyer_party bp on bp.id = bi.buyer_party_id
            where {where_sql}
            order by bi.updated_at desc
            """
        ),
        params,
    ).mappings().all()

    term_levels = load_term_levels(db)
    candidates: list[dict[str, Any]] = []
    excluded_count = 0
    conflict_count = 0
    semantic_terms = _semantic_query_terms(semantic_query_lines or [])
    for row in rows:
        item = dict(row)
        if item.pop("is_excluded"):
            excluded_count += 1
            continue
        item["id"] = item["buyer_intent_id"]
        item["excluded_terms_resolved"] = classify_terms(item.get("excluded_industries_json"), term_levels)
        scenarios = _effective_scenarios(db, item)
        rule_score, evidence, gaps, meta = _score_against_scenarios(target, item, scenarios)
        if meta["state"] == CANDIDATE_STATE_CONFLICT:
            conflict_count += 1
            continue
        candidates.append(
            _build_candidate_row(
                mode="target_to_buyer",
                seller_target_id=target.get("id"),
                # Every real and temporary anchor carries this display field.
                seller_target_name=target["target_name"] or "临时标的画像",
                buyer_intent_id=item["buyer_intent_id"],
                buyer_intent_name=item["buyer_intent_name"],
                buyer_party_id=item.get("buyer_party_id"),
                buyer_name=item.get("buyer_name"),
                score=rule_score,
                rule_score=rule_score,
                evidence=evidence,
                gaps=gaps,
                meta=meta,
                risk_summary=target.get("risk_summary") or target.get("gap_summary"),
            )
        )
        _apply_semantic_keyword_match(
            candidates[-1],
            terms=semantic_terms,
            searchable_text="\n".join(
                str(value or "")
                for value in (
                    item.get("buyer_name"),
                    item.get("buyer_intent_name"),
                    item.get("raw_requirement_text"),
                    item.get("intent_summary"),
                    item.get("industry_focus_tags_json"),
                )
            ),
        )

    return _annotate_candidate_relations(
        db,
        _rank_and_report(candidates, limit=limit, scan_count=len(rows), excluded_count=excluded_count, conflict_count=conflict_count),
        mode="target_to_buyer",
    )


# 每个方案的保底名额：宽方案不得把用户亲口写的窄方案整条挤出深评队列。
SCENARIO_MIN_QUOTA = 5


def _load_intent_scenarios(db: Session, buyer_intent_id: Any) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select id, label, sort_order, fields_json, needs_confirmation_json, condition_effects_json
            from buyer_intent_scenario
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and active = true
            order by sort_order, created_at
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [
        {
            "id": str(row["id"]),
            "label": row["label"],
            "fields": normalize_scenario_fields(row["fields_json"]),
            "needs_confirmation": row.get("needs_confirmation_json") or [],
            "condition_effects": normalize_condition_effects(row.get("condition_effects_json")),
        }
        for row in rows
    ]


def _effective_scenarios(
    db: Session,
    intent: dict[str, Any],
    disabled_scenario_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Scenarios to screen against, or a single implicit one.

    An intent with no scenario rows keeps exactly the old behaviour: one pass
    over its own fields. That is what makes the multi-scenario rollout additive
    for every intent already in the library.
    """
    intent_id = intent.get("id")
    scenarios = _load_intent_scenarios(db, intent_id) if intent_id else []
    if disabled_scenario_ids:
        scenarios = [item for item in scenarios if item["id"] not in disabled_scenario_ids]
    if not scenarios:
        return [{"id": None, "label": None, "fields": {}, "needs_confirmation": [], "condition_effects": {}}]
    return scenarios


def _score_against_scenarios(
    target: dict[str, Any],
    intent: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> tuple[float, list[str], list[str], dict[str, Any]]:
    """Score a candidate against every scenario and keep its best outcome.

    A candidate stays in the pool when at least one scenario does not conflict;
    the score reported is the best one, and every non-conflicting scenario is
    recorded so the card can show "最佳命中 / 同时满足".
    """
    best: tuple[float, list[str], list[str], dict[str, Any]] | None = None
    matched: list[str] = []
    matched_labels: list[str] = []
    effective_base = suppress_pending_confirmation_fields(intent)
    for scenario in scenarios:
        merged_intent = (
            merge_scenario_into_anchor(effective_base, scenario["fields"])
            if scenario["fields"]
            else effective_base
        )
        merged_intent = {
            **merged_intent,
            "condition_effects_json": {
                **(merged_intent.get("condition_effects_json") or {}),
                **(scenario.get("condition_effects") or {}),
            },
            "_scenario_fields": set(scenario["fields"]),
        }
        merged_intent = suppress_pending_confirmation_fields(
            merged_intent,
            scenario.get("needs_confirmation"),
        )
        score, evidence, gaps, meta = _score_target_against_intent(target, merged_intent)
        meta = {**meta, "scenario_id": scenario["id"], "scenario_label": scenario["label"]}
        if meta["state"] != CANDIDATE_STATE_CONFLICT and scenario["id"]:
            matched.append(scenario["id"])
            if scenario["label"]:
                matched_labels.append(scenario["label"])
        if best is None:
            best = (score, evidence, gaps, meta)
            continue
        best_is_conflict = best[3]["state"] == CANDIDATE_STATE_CONFLICT
        this_is_conflict = meta["state"] == CANDIDATE_STATE_CONFLICT
        if best_is_conflict and not this_is_conflict:
            best = (score, evidence, gaps, meta)
        elif best_is_conflict == this_is_conflict and score > best[0]:
            best = (score, evidence, gaps, meta)

    score, evidence, gaps, meta = best  # type: ignore[misc]
    meta = {**meta, "matched_scenarios": matched, "matched_scenario_labels": matched_labels}
    return score, evidence, gaps, meta


def _select_with_scenario_quota(
    candidates: list[dict[str, Any]],
    scenario_ids: list[str],
    keep: int,
) -> list[dict[str, Any]]:
    """Reserve a floor for every scenario before filling by global rank."""
    if len(candidates) <= keep or len(scenario_ids) <= 1:
        return candidates[:keep]
    chosen: dict[int, dict[str, Any]] = {}
    for scenario_id in scenario_ids:
        taken = 0
        for index, candidate in enumerate(candidates):
            if taken >= SCENARIO_MIN_QUOTA:
                break
            if scenario_id in (candidate.get("matched_scenarios") or []):
                chosen[index] = candidate
                taken += 1
    for index, candidate in enumerate(candidates):
        if len(chosen) >= keep:
            break
        chosen.setdefault(index, candidate)
    return [candidates[index] for index in sorted(chosen)[:keep]]


def _with_resolved_exclusions(db: Session, intent: dict[str, Any]) -> dict[str, Any]:
    """Attach dictionary-resolved exclusion levels once per request.

    The scorer runs per candidate and has no session, so the L1/L2 split of the
    buyer's exclusion terms is computed here and carried on the intent dict.
    """
    if intent.get("excluded_terms_resolved") is not None:
        return intent
    values = intent.get("excluded_industries_json")
    if not isinstance(values, list) or not values:
        return intent
    resolved = dict(intent)
    resolved["excluded_terms_resolved"] = classify_terms(values, load_term_levels(db))
    return resolved


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


def _build_candidate_row(
    *,
    mode: str,
    seller_target_id: Any,
    seller_target_name: Any,
    buyer_intent_id: Any,
    buyer_intent_name: Any,
    buyer_party_id: Any,
    buyer_name: Any,
    score: float,
    rule_score: float,
    evidence: list[str],
    gaps: list[str],
    meta: dict[str, Any],
    risk_summary: Any,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rank": 0,
        # 硬数据（净利/地区/控股/PE…）。SQL 本来就查出来了，过去在这里被丢掉，
        # 结果推荐文案只能写评价、写不出数字。Agent 与写作节点都靠它。
        "facts": facts or {},
        "mode": mode,
        "seller_target_id": seller_target_id,
        "seller_target_name": seller_target_name,
        "buyer_intent_id": buyer_intent_id,
        "buyer_intent_name": buyer_intent_name,
        "buyer_party_id": buyer_party_id,
        "buyer_name": buyer_name,
        "score": score,
        "recommendation_level": _recommendation_level(score),
        "match_state": meta["state"],
        "known_count": meta["known_count"],
        "missing_dimensions": meta["unknown_dimensions"],
        "best_scenario_id": meta.get("scenario_id"),
        "best_scenario_label": meta.get("scenario_label"),
        "matched_scenarios": meta.get("matched_scenarios") or [],
        "matched_scenario_labels": meta.get("matched_scenario_labels") or [],
        "match_summary": _summary_text(evidence, fallback="具备初步匹配基础"),
        "gap_summary": _summary_text(gaps) if gaps else None,
        "risk_summary": risk_summary,
        # 关系状态由 _annotate_candidate_relations 填充；默认无关系。
        "relation_id": None,
        "relation_status": None,
        "deep_progress_elsewhere": False,
        "seller_target_has_other_deep_progress": False,
        "buyer_intent_has_other_deep_progress": False,
        "evidence_json": {
            "matches": evidence,
            "gaps": gaps,
            "score": {
                "rule_score": rule_score,
                "final_score": score,
                "state": meta["state"],
                "known_count": meta["known_count"],
                "missing_dimensions": meta["unknown_dimensions"],
                "conflicts": meta["conflicts"],
                "excluded_hit": meta["excluded_hit"],
                "score_engine": meta["score_engine"],
            },
        },
    }


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


def _rank_and_report(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    scan_count: int,
    excluded_count: int,
    conflict_count: int,
    scenario_ids: list[str] | None = None,
    scenarios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Order the eligible pool and report the funnel so nothing truncates silently.

    Primary key is the optimistic score; ties break on how many dimensions were
    actually known, so a fully-verified target outranks a blank one that only
    scored well because unknowns were assumed to match. When the buyer wrote
    several scenarios, each one keeps a floor of the deep-eval budget.
    """
    candidates.sort(
        key=lambda candidate: (
            bool(candidate.get("semantic_keyword_matches")),
            candidate["score"],
            candidate["known_count"],
        ),
        reverse=True,
    )
    keep = max(limit, DEEP_EVAL_CANDIDATE_LIMIT)
    selected = _select_with_scenario_quota(candidates, scenario_ids or [], keep)
    for index, candidate in enumerate(selected, start=1):
        candidate["rank"] = index
    funnel = {
        "scan_count": scan_count,
        "excluded_count": excluded_count,
        "conflict_count": conflict_count,
        "eligible_count": len(candidates),
        "deep_eval_count": min(len(selected), DEEP_EVAL_CANDIDATE_LIMIT),
        "display_count": len(selected),
    }
    if scenario_ids:
        funnel["scenario_count"] = len(scenario_ids)
        funnel["eligible_by_scenario"] = {
            scenario_id: sum(
                1 for candidate in candidates if scenario_id in (candidate.get("matched_scenarios") or [])
            )
            for scenario_id in scenario_ids
        }
    return {
        "candidates": selected,
        "funnel": funnel,
        "scenarios": [
            {"id": scenario["id"], "label": scenario["label"]}
            for scenario in (scenarios or [])
            if scenario.get("id")
        ],
    }


REGION_GROUPS: dict[str, tuple[str, ...]] = {
    "长三角": ("上海", "江苏", "浙江", "安徽"),
    "珠三角": ("广东",),
    "大湾区": ("广东", "香港", "澳门"),
    "京津冀": ("北京", "天津", "河北"),
    "成渝": ("四川", "重庆"),
    "东北": ("辽宁", "吉林", "黑龙江"),
    "长江中游": ("湖北", "湖南", "江西"),
    "华东": ("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"),
    "华南": ("广东", "广西", "海南"),
    "华北": ("北京", "天津", "河北", "山西", "内蒙古"),
    "华中": ("湖北", "湖南", "河南", "江西"),
    "西北": ("陕西", "甘肃", "青海", "宁夏", "新疆"),
    "西南": ("四川", "重庆", "云南", "贵州", "西藏"),
}


# 三态：明确冲突的候选直接出局；信息缺失只降级为 possible，永远不出局。
CANDIDATE_STATE_COMPATIBLE = "compatible"


CANDIDATE_STATE_POSSIBLE = "possible"


CANDIDATE_STATE_CONFLICT = "conflict"


# 存在 critical 风险记录时的系统级降权（与买家条件无关，不影响三态）。


# 规则一：要求 × 意愿。买家侧写"要求强度"，标的侧写"能力/意愿"，两侧枚举不同名
# 不同值，靠这张矩阵配对。新增一个同形态维度 = 在 CAPABILITY_DIMENSIONS 加一行。
REQUIREMENT_CAPABILITY_MATRIX: dict[tuple[str, str], str] = {
    ("required", "yes"): "match",
    ("required", "likely"): "unknown",
    ("required", "no"): "conflict",
    ("required", "unknown"): "unknown",
    ("preferred", "yes"): "match",
    ("preferred", "likely"): "match",
    ("preferred", "no"): "mismatch",
    ("preferred", "unknown"): "unknown",
}


CAPABILITY_DIMENSIONS: tuple[tuple[str, str, float, str], ...] = (
    # (买家要求字段, 标的能力字段, 权重, 维度名)
    ("requires_relocation", "accepts_relocation", 8.0, "迁址"),
    ("requires_return_investment", "accepts_return_investment", 6.0, "返投"),
    ("requires_team_retention", "management_retention_possible", 6.0, "团队留任"),
)


def _strip_region_suffix(value: Any) -> str:
    text_value = str(value or "").strip()
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市"):
        if text_value.endswith(suffix):
            return text_value[: -len(suffix)]
    return text_value


def _region_scope_matches(region_scope: str, province: Any, city: Any) -> bool:
    for part in (province, city):
        part_text = str(part or "").strip()
        if not part_text:
            continue
        if part_text in region_scope or _strip_region_suffix(part_text) in region_scope:
            return True
    province_short = _strip_region_suffix(province)
    if not province_short:
        return False
    for group_name, provinces in REGION_GROUPS.items():
        if group_name in region_scope and province_short in provinces:
            return True
    return False


def _region_constraint_matches(
    constraint: dict[str, Any],
    province: Any,
    city: Any,
    district: Any,
) -> bool:
    """Match one normalized buyer region against one target location."""
    actual = {
        "province": _strip_region_suffix(province),
        "city": _strip_region_suffix(city),
        "district": _strip_region_suffix(district),
    }
    for key in ("province", "city", "district"):
        expected = _strip_region_suffix(constraint.get(key))
        if expected and expected != actual[key]:
            return False
    return bool(_strip_region_suffix(constraint.get("province")))


def _intent_industry_list(intent: dict[str, Any]) -> list[str]:
    values = intent.get("industries_json")
    if isinstance(values, list):
        return [str(item).strip() for item in values if item is not None and str(item).strip()]
    return []


def _target_industry_values(target: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return all canonical L1/L2 values with a pre-migration fallback."""
    l1_values: set[str] = set()
    l2_values: set[str] = set()
    for pair in target.get("industry_pairs_json") or []:
        if not isinstance(pair, dict):
            continue
        l1 = str(pair.get("l1") or "").strip()
        l2 = str(pair.get("l2") or "").strip()
        if l1:
            l1_values.add(l1)
        if l2:
            l2_values.add(l2)
    if not l1_values and target.get("industry_l1"):
        l1_values.add(str(target["industry_l1"]).strip())
    if not l2_values and target.get("industry_l2"):
        l2_values.add(str(target["industry_l2"]).strip())
    return l1_values, l2_values


_SEMANTIC_QUERY_STOP_TERMS = frozenset({
    "推荐", "标的", "买家", "公司", "企业", "相关", "关键词", "关键字", "业务", "行业", "项目",
})
_SEMANTIC_KEYWORD_BOOST = 12.0


def _semantic_query_terms(lines: list[str]) -> tuple[str, ...]:
    """Extract conservative literal recall terms from a chat query.

    The recommendation parser deliberately keeps free-text requests as a
    semantic preference for deep evaluation.  That happened too late for a
    niche word only recorded in a target's ``其他`` supplement: the target
    could never enter the deep-eval candidate set.  We use only a transparent
    literal boost here, not an untraceable LLM filter.  For Chinese text,
    useful business words are often joined without spaces, so two-to-four
    character n-grams provide a recall bridge (e.g. “殡葬墓地” -> “殡葬”).
    """
    terms: set[str] = set()
    for line in lines:
        for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_+.-]{1,}", str(line or "")):
            normalized = token.strip().lower()
            if normalized and normalized not in _SEMANTIC_QUERY_STOP_TERMS:
                terms.add(normalized)
            if re.fullmatch(r"[\u4e00-\u9fff]{3,}", token):
                for width in range(2, min(4, len(token)) + 1):
                    for start in range(0, len(token) - width + 1):
                        ngram = token[start : start + width]
                        if ngram not in _SEMANTIC_QUERY_STOP_TERMS:
                            terms.add(ngram)
    return tuple(sorted(terms, key=lambda item: (-len(item), item)))


def _apply_semantic_keyword_match(
    candidate: dict[str, Any],
    *,
    terms: tuple[str, ...],
    searchable_text: str,
) -> None:
    """Add an explainable keyword recall bonus without bypassing hard rules."""
    if not terms or not searchable_text:
        return
    haystack = searchable_text.lower()
    matches = [term for term in terms if term in haystack]
    if not matches:
        return
    # Prefer the longest terms in the user-facing explanation; the candidate
    # still retains the full term list for diagnostic use.
    display_matches = matches[:3]
    candidate["semantic_keyword_matches"] = matches
    candidate["score"] = float(candidate["score"]) + _SEMANTIC_KEYWORD_BOOST
    candidate["recommendation_level"] = _recommendation_level(float(candidate["score"]))
    candidate["match_summary"] = _summary_text(
        [f"关键词命中：{'、'.join(display_matches)}", str(candidate.get("match_summary") or "")],
        fallback="关键词匹配",
    )
    evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
    score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
    candidate["evidence_json"] = {
        **evidence_json,
        "semantic_keyword_matches": matches,
        "score": {
            **score_json,
            "semantic_keyword_boost": _SEMANTIC_KEYWORD_BOOST,
            "final_score": candidate["score"],
        },
    }


def _excluded_industry_hit(target: dict[str, Any], intent: dict[str, Any]) -> str | None:
    """Match exclusions at the granularity the buyer wrote them.

    ``excluded_terms_resolved`` is precomputed per request against the industry
    dictionary (see ``classify_terms``): L1 terms compare against the target's
    industry_l1 and L2 terms against industry_l2, both exactly. Terms the
    dictionary does not know are deliberately left to deep evaluation: an
    unmapped free-text phrase must not become a hard exclusion by substring.
    """
    values = intent.get("excluded_industries_json")
    if not isinstance(values, list) or not values:
        return None
    resolved = intent.get("excluded_terms_resolved")
    if not isinstance(resolved, dict):
        resolved = {"l1": [], "l2": [], "unresolved": [str(value).strip() for value in values if value]}

    industry_l1_values, industry_l2_values = _target_industry_values(target)
    for term in resolved.get("l1") or []:
        if term and term in industry_l1_values:
            return term
    for term in resolved.get("l2") or []:
        if term and term in industry_l2_values:
            return term

    return None


def _score_target_against_intent(
    target: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[float, list[str], list[str], dict[str, Any]]:
    """Optimistic three-state scoring.

    Every dimension the buyer actually asked for adds weight to the denominator.
    Targets earn full weight on match; **unknown target-side data also earns full
    weight** (optimistic, recall-first) but is recorded in ``unknown_dimensions``
    so callers can rank fully-known candidates ahead of blank ones and drive
    research tasks. A known mismatch on a gate dimension becomes a conflict,
    which removes the candidate from the pool entirely; soft dimensions only
    cost score.
    """
    evidence: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []
    unknown_dimensions: list[str] = []
    earned = 0.0
    possible = 0.0
    known_count = 0

    def add_dimension(
        weight: float,
        state: str,
        *,
        dimension: str,
        field: str | None = None,
        match_text: str | None = None,
        gap_text: str | None = None,
        gate: bool | None = None,
        earned_override: float | None = None,
    ) -> None:
        nonlocal earned, possible, known_count
        if field:
            effect = condition_effect(intent, field)
            if effect is None:
                # 不是条件，只是描述。它的内容随「其他」进深评，不进规则打分。
                return
            gate = effect == "required" if gate is None else bool(gate and effect == "required")
        else:
            gate = bool(gate)
        possible += weight
        if state == "match":
            known_count += 1
            earned += weight if earned_override is None else earned_override
            if match_text:
                evidence.append(match_text)
        elif state == "mismatch":
            known_count += 1
            if gap_text:
                gaps.append(gap_text)
            if gate and gap_text:
                conflicts.append(gap_text)
        else:
            # 乐观分：未知按“假定满足”计满分，缺口只记录不扣分。
            earned += weight
            unknown_dimensions.append(dimension)
            if gap_text:
                gaps.append(gap_text)

    # 行业（多值，任一命中；主赛道全分，其余 85%）
    intent_industries = _intent_industry_list(intent)
    target_l1_values, target_l2_values = _target_industry_values(target)
    if intent_industries:
        if not target_l1_values:
            add_dimension(30, "unknown", dimension="行业", field="industries_json", gap_text="标的行业待归类")
        elif target_l1_values & set(intent_industries):
            matched_l1 = sorted(target_l1_values & set(intent_industries))
            is_primary_track = intent_industries[0] in matched_l1
            add_dimension(
                30,
                "match",
                dimension="行业",
                field="industries_json",
                match_text=f"行业命中：{'、'.join(matched_l1)}" + ("（主赛道）" if is_primary_track else ""),
                earned_override=30.0 if is_primary_track else 25.5,
            )
        else:
            add_dimension(30, "mismatch", dimension="行业", field="industries_json", gap_text="行业不在买家关注赛道")
    elif intent.get("industry_primary"):
        # 旧数据兜底：字符串相等，不命中只降分不出局
        if intent.get("industry_primary") in target_l1_values:
            add_dimension(30, "match", dimension="行业", field="industries_json", match_text=f"一级行业匹配：{intent['industry_primary']}")
        else:
            add_dimension(30, "mismatch", dimension="行业", field="industries_json", gap_text="一级行业不完全匹配")

    # 行业 L2（聚焦方向）：买家列的是关注赛道，通常不是穷举白名单，因此不 gate；
    # 真正的硬规则走排除项（见 _excluded_industry_hit）。
    intent_l2 = [
        str(item).strip()
        for item in (intent.get("industry_l2_json") or [])
        if item is not None and str(item).strip()
    ]
    if intent_l2:
        if not target_l2_values:
            add_dimension(15, "unknown", dimension="细分赛道", field="industry_l2_json", gap_text="标的细分赛道待归类")
        elif target_l2_values & set(intent_l2):
            add_dimension(15, "match", dimension="细分赛道", field="industry_l2_json", match_text=f"细分赛道命中：{'、'.join(sorted(target_l2_values & set(intent_l2)))}")
        else:
            add_dimension(15, "mismatch", dimension="细分赛道", field="industry_l2_json", gap_text="细分赛道不在买家关注方向")

    # 结构化地区优先；旧地域摘要只为历史数据兜底。地区条件内部允许
    # required / preferred / excluded 混合存在，因此不能把整个字段粗暴地
    # 归为一种作用。二级地区未命中默认只降分，只有省级 required 明确
    # 不命中或命中 excluded 才可能成为冲突。
    region_constraints = [
        item for item in (intent.get("region_constraints_json") or []) if isinstance(item, dict)
    ]
    region_scope = str(intent.get("region_scope_summary") or "").strip()
    if region_constraints and condition_effect(intent, "region_constraints_json") is not None:
        province = target.get("location_province")
        city = target.get("location_city")
        district = target.get("location_district")
        if not province and not city and not district:
            add_dimension(12, "unknown", dimension="区域", gap_text="标的区域缺失")
        else:
            excluded = [item for item in region_constraints if item.get("effect") == "excluded"]
            required = [item for item in region_constraints if item.get("effect") == "required"]
            preferred = [item for item in region_constraints if item.get("effect") == "preferred"]
            excluded_hit = any(_region_constraint_matches(item, province, city, district) for item in excluded)
            required_hit = any(_region_constraint_matches(item, province, city, district) for item in required)
            preferred_hit = any(_region_constraint_matches(item, province, city, district) for item in preferred)
            target_region = "".join(str(item) for item in [province, city, district] if item)
            if excluded_hit:
                add_dimension(12, "mismatch", dimension="区域", gap_text="标的地区命中排除范围", gate=True)
            elif required and not required_hit:
                # 二级行业/地区的精细边界留给软排；省级 required 才硬冲突。
                province_required = any(not item.get("city") and not item.get("district") for item in required)
                add_dimension(12, "mismatch", dimension="区域", gap_text="区域不符合买家必须范围", gate=province_required)
            elif required_hit or preferred_hit:
                add_dimension(12, "match", dimension="区域", match_text=f"区域匹配：{target_region}")
            else:
                add_dimension(12, "mismatch", dimension="区域", gap_text="区域未命中买家优先范围")
    elif region_scope:
        province = target.get("location_province")
        city = target.get("location_city")
        if not province and not city:
            add_dimension(12, "unknown", dimension="区域", gap_text="标的区域缺失")
        elif _region_scope_matches(region_scope, province, city):
            target_region = "".join(str(item) for item in [province, city] if item)
            add_dimension(12, "match", dimension="区域", match_text=f"区域匹配：{target_region}")
        else:
            add_dimension(12, "mismatch", dimension="区域", gap_text="区域不符合买家范围，需人工复核")

    # 财务门槛逐项生效。真正的 OR 必须由显式方案表达；含糊的复合描述
    # 留在深评，不能由规则层自行推断成“营收或利润任一达标”。
    min_profit = _optional_decimal(intent.get("min_net_profit_yuan"))
    target_profit = _optional_decimal(target.get("current_net_profit_yuan"))
    min_revenue = _optional_decimal(intent.get("min_revenue_yuan"))
    target_revenue = _optional_decimal(target.get("current_revenue_yuan"))
    profit_ok = target_profit is not None and min_profit is not None and target_profit >= min_profit
    revenue_ok = target_revenue is not None and min_revenue is not None and target_revenue >= min_revenue
    if min_profit is not None:
        if target_profit is None:
            add_dimension(16, "unknown", dimension="净利润", field="min_net_profit_yuan", gap_text="标的净利润缺失")
        elif profit_ok:
            add_dimension(16, "match", dimension="净利润", field="min_net_profit_yuan", match_text="净利润达到门槛")
        else:
            add_dimension(16, "mismatch", dimension="净利润", field="min_net_profit_yuan", gap_text="净利润低于买家门槛")
    if min_revenue is not None:
        if target_revenue is None:
            add_dimension(12, "unknown", dimension="营收", field="min_revenue_yuan", gap_text="标的营收缺失")
        elif revenue_ok:
            add_dimension(12, "match", dimension="营收", field="min_revenue_yuan", match_text="营收达到门槛")
        else:
            add_dimension(12, "mismatch", dimension="营收", field="min_revenue_yuan", gap_text="营收低于买家门槛")

    # 整体价值轴（C-a）：买家的估值区间比标的“100% 股权价值”。
    # 上市看市值、非上市看估值；两者同口径可互相兜底。
    # 报价（asking_price）属于交易对价轴（C-b），口径不同，绝不参与此处比较
    # ——混用会把“预算 10 亿买 25% 股权”的买家与 40 亿估值的标的判成硬冲突。
    min_valuation = _optional_decimal(intent.get("min_valuation_yuan"))
    max_valuation = _optional_decimal(intent.get("max_valuation_yuan"))
    if min_valuation is not None or max_valuation is not None:
        is_listed = str(target.get("listed_status") or "").strip() == "listed"
        primary_value = _optional_decimal(
            target.get("market_cap_yuan") if is_listed else target.get("valuation_yuan")
        )
        enterprise_value = primary_value or (
            _optional_decimal(target.get("valuation_yuan"))
            or _optional_decimal(target.get("market_cap_yuan"))
        )
        valuation_field = "max_valuation_yuan" if max_valuation is not None else "min_valuation_yuan"
        if enterprise_value is None:
            add_dimension(14, "unknown", dimension="整体估值", field=valuation_field, gap_text="标的整体估值缺失")
        elif max_valuation is not None and enterprise_value > max_valuation:
            add_dimension(14, "mismatch", dimension="整体估值", field="max_valuation_yuan", gap_text="整体估值超出买家上限")
        elif min_valuation is not None and enterprise_value < min_valuation:
            add_dimension(14, "mismatch", dimension="整体估值", field="min_valuation_yuan", gap_text="整体估值低于买家偏好区间")
        else:
            add_dimension(14, "match", dimension="整体估值", field=valuation_field, match_text="整体估值处于买家要求范围")

    # PE 上限
    max_pe = _optional_decimal(intent.get("max_pe"))
    if max_pe is not None:
        target_pe = _optional_decimal(target.get("pe_ratio"))
        if target_pe is None:
            add_dimension(10, "unknown", dimension="PE", field="max_pe", gap_text="标的 PE 缺失")
        elif target_pe <= max_pe:
            add_dimension(10, "match", dimension="PE", field="max_pe", match_text="PE 未超过上限")
        else:
            add_dimension(10, "mismatch", dimension="PE", field="max_pe", gap_text="PE 超过买家上限")

    # 市值区间（上市标的体量偏好，不沉底）
    min_market_cap = _optional_decimal(intent.get("min_market_cap_yuan"))
    max_market_cap = _optional_decimal(intent.get("max_market_cap_yuan"))
    if min_market_cap is not None or max_market_cap is not None:
        target_market_cap = _optional_decimal(target.get("market_cap_yuan")) or _optional_decimal(
            target.get("valuation_yuan")
        )
        market_cap_field = "max_market_cap_yuan" if max_market_cap is not None else "min_market_cap_yuan"
        if target_market_cap is None:
            add_dimension(6, "unknown", dimension="市值", field=market_cap_field, gap_text="标的市值缺失")
        elif min_market_cap is not None and target_market_cap < min_market_cap:
            add_dimension(6, "mismatch", dimension="市值", field="min_market_cap_yuan", gap_text="市值低于买家下限")
        elif max_market_cap is not None and target_market_cap > max_market_cap:
            add_dimension(6, "mismatch", dimension="市值", field="max_market_cap_yuan", gap_text="市值超过买家上限")
        else:
            add_dimension(6, "match", dimension="市值", field=market_cap_field, match_text="市值处于买家要求范围")

    # 利润总额（与净利润是两个口径，买家分别提；软性，避免与净利润叠加沉底）
    min_total_profit = _optional_decimal(intent.get("min_total_profit_yuan"))
    if min_total_profit is not None:
        target_total_profit = _optional_decimal(target.get("current_total_profit_yuan"))
        if target_total_profit is None:
            add_dimension(6, "unknown", dimension="利润总额", field="min_total_profit_yuan", gap_text="标的利润总额缺失")
        elif target_total_profit >= min_total_profit:
            add_dimension(6, "match", dimension="利润总额", field="min_total_profit_yuan", match_text="利润总额达到门槛")
        else:
            add_dimension(6, "mismatch", dimension="利润总额", field="min_total_profit_yuan", gap_text="利润总额低于买家门槛")

    # 净利率 / PS：标的侧不单独存，由营收与利润、市值派生（C4）
    min_net_margin = _optional_decimal(intent.get("min_net_margin"))
    if min_net_margin is not None:
        if target_revenue and target_revenue > 0 and target_profit is not None:
            target_margin = target_profit / target_revenue * 100
            if target_margin >= min_net_margin:
                add_dimension(6, "match", dimension="净利率", field="min_net_margin", match_text="净利率达到门槛")
            else:
                add_dimension(6, "mismatch", dimension="净利率", field="min_net_margin", gap_text="净利率低于买家门槛")
        else:
            add_dimension(6, "unknown", dimension="净利率", field="min_net_margin", gap_text="标的净利率无法计算（缺营收或利润）")

    max_ps = _optional_decimal(intent.get("max_ps"))
    if max_ps is not None:
        ps_base = _optional_decimal(target.get("market_cap_yuan")) or _optional_decimal(
            target.get("valuation_yuan")
        )
        if ps_base is not None and target_revenue and target_revenue > 0:
            if ps_base / target_revenue <= max_ps:
                add_dimension(6, "match", dimension="PS", field="max_ps", match_text="PS 未超过上限")
            else:
                add_dimension(6, "mismatch", dimension="PS", field="max_ps", gap_text="PS 超过买家上限")
        else:
            add_dimension(6, "unknown", dimension="PS", field="max_ps", gap_text="标的 PS 无法计算（缺估值或营收）")

    # 股比/控股/并表：取买家提出的最强要求；标的明确说“不行”才算硬不符。
    # 买家自己接受少数股权时不再沉底——这是先参股后控股的常见路径。
    requires_control = _yes_like(intent.get("requires_control"))
    requires_consolidation = _yes_like(intent.get("requires_consolidation"))
    desired_min_ratio = _optional_decimal(intent.get("desired_equity_ratio_min"))
    desired_max_ratio = _optional_decimal(intent.get("desired_equity_ratio_max"))
    buyer_accepts_minority = _yes_like(intent.get("accepts_minority_investment"))
    if requires_control or requires_consolidation:
        requirement_label = "控股" if requires_control else "并表"
        requirement_field = "requires_control" if requires_control else "requires_consolidation"
        capability = target.get("can_control") if requires_control else target.get("can_consolidate")
        if _yes_like(capability):
            add_dimension(12, "match", dimension=requirement_label, field=requirement_field, match_text=f"满足{requirement_label}要求")
        elif str(capability or "").lower() == "no":
            gap_text = f"标的明确不可{requirement_label}"
            if buyer_accepts_minority:
                gap_text += "（买家接受少数股权，未沉底）"
            add_dimension(
                12,
                "mismatch",
                dimension=requirement_label,
                field=requirement_field,
                gap_text=gap_text,
                gate=not buyer_accepts_minority,
            )
        else:
            add_dimension(12, "unknown", dimension=requirement_label, field=requirement_field, gap_text=f"{requirement_label}能力待确认")
    elif desired_min_ratio is not None:
        # 买家明确写了比例区间时才启用；只说“要控制”走上面的枚举分支。
        transfer_max = _optional_decimal(target.get("transfer_ratio_max"))
        if transfer_max is None:
            add_dimension(12, "unknown", dimension="可转让股比", field="desired_equity_ratio_min", gap_text="标的可转让股比未知")
        elif transfer_max >= desired_min_ratio:
            add_dimension(12, "match", dimension="可转让股比", field="desired_equity_ratio_min", match_text="可转让股比满足买家要求")
        else:
            add_dimension(12, "mismatch", dimension="可转让股比", field="desired_equity_ratio_min", gap_text="可转让股比低于买家要求")

    # 股比上限：买家封顶（如北大健康 ≤29.9%）而标的最少要卖 51% 时是真冲突。
    if desired_max_ratio is not None:
        transfer_min = _optional_decimal(target.get("transfer_ratio_min"))
        if transfer_min is None:
            add_dimension(6, "unknown", dimension="最低转让股比", field="desired_equity_ratio_max", gap_text="标的最低转让股比未知")
        elif transfer_min <= desired_max_ratio:
            add_dimension(6, "match", dimension="最低转让股比", field="desired_equity_ratio_max", match_text="标的可接受买家的股比上限")
        else:
            add_dimension(
                6, "mismatch", dimension="最低转让股比", field="desired_equity_ratio_max", gap_text="标的最低转让股比高于买家股比上限"
            )

    # 规则一：要求 × 意愿（迁址 / 返投 / 团队留任）
    for buyer_field, target_field, weight, label in CAPABILITY_DIMENSIONS:
        strength = str(intent.get(buyer_field) or "unknown").strip().lower()
        if strength not in {"required", "preferred"}:
            continue
        capability = str(target.get(target_field) or "unknown").strip().lower()
        if capability not in {"yes", "likely", "no"}:
            capability = "unknown"
        outcome = REQUIREMENT_CAPABILITY_MATRIX.get((strength, capability), "unknown")
        if outcome == "match":
            add_dimension(weight, "match", dimension=label, field=buyer_field, match_text=f"满足{label}要求")
        elif outcome == "conflict":
            add_dimension(weight, "mismatch", dimension=label, field=buyer_field, gap_text=f"标的明确不接受{label}")
        elif outcome == "mismatch":
            add_dimension(weight, "mismatch", dimension=label, field=buyer_field, gap_text=f"标的不接受{label}（买家为偏好项）")
        else:
            add_dimension(weight, "unknown", dimension=label, field=buyer_field, gap_text=f"{label}意愿待确认")

    # 经营状态要求（现金流 / 盈利状态）：复用标的侧闭集，偏好性不沉底
    for buyer_field, target_field, weight, label in (
        ("acceptable_cash_flow_status_json", "cash_flow_status", 10.0, "现金流状态"),
        ("acceptable_profitability_status_json", "profitability_status", 8.0, "盈利状态"),
    ):
        acceptable = [
            str(item).strip()
            for item in (intent.get(buyer_field) or [])
            if item is not None and str(item).strip()
        ]
        if not acceptable:
            continue
        target_status = str(target.get(target_field) or "").strip()
        if not target_status or target_status == "unknown":
            add_dimension(weight, "unknown", dimension=label, field=buyer_field, gap_text=f"标的{label}缺失")
        elif target_status in acceptable:
            add_dimension(weight, "match", dimension=label, field=buyer_field, match_text=f"{label}符合买家要求")
        else:
            add_dimension(weight, "mismatch", dimension=label, field=buyer_field, gap_text=f"{label}不符合买家要求")

    # 上市地（境内/境外）：买家写"只投境内"是明确排除，沉底
    required_market_region = str(intent.get("listing_market_region") or "").strip()
    if required_market_region and required_market_region != "unknown":
        target_market_region = str(target.get("listing_market_region") or "").strip()
        if not target_market_region or target_market_region == "unknown":
            add_dimension(6, "unknown", dimension="上市地", field="listing_market_region", gap_text="标的上市地未知")
        elif target_market_region == required_market_region:
            add_dimension(6, "match", dimension="上市地", field="listing_market_region", match_text="上市地符合买家要求")
        else:
            add_dimension(6, "mismatch", dimension="上市地", field="listing_market_region", gap_text="上市地不符合买家要求")

    # 上市状态：公共层字段是偏好；方案层字段用于区分“上市方案 OR
    # 非上市方案”，因此是该方案的门槛。
    acceptable_listed_statuses = {
        str(value).strip()
        for value in (intent.get("acceptable_listed_status_json") or [])
        if str(value or "").strip() in {"listed", "unlisted", "pre_ipo"}
    }
    preferred_listed_status = intent.get("preferred_listed_status")
    if not acceptable_listed_statuses and preferred_listed_status in {"listed", "unlisted", "pre_ipo", "preparing_listing"}:
        acceptable_listed_statuses = {
            "pre_ipo" if preferred_listed_status == "preparing_listing" else str(preferred_listed_status)
        }
    if acceptable_listed_statuses:
        target_listed_status = target.get("listed_status")
        if target_listed_status in acceptable_listed_statuses:
            add_dimension(8, "match", dimension="上市状态", field="acceptable_listed_status_json", match_text="上市状态符合偏好")
        elif target_listed_status and target_listed_status != "unknown":
            add_dimension(
                8,
                "mismatch",
                dimension="上市状态",
                field="acceptable_listed_status_json",
                gap_text="上市状态不符合要求",
            )
        else:
            add_dimension(8, "unknown", dimension="上市状态", field="acceptable_listed_status_json", gap_text="标的上市状态缺失")

    # 负债率上限（弱信号）
    max_debt_ratio = _optional_decimal(intent.get("max_debt_ratio"))
    if max_debt_ratio is not None:
        target_debt_ratio = _optional_decimal(target.get("current_debt_ratio"))
        if target_debt_ratio is None:
            add_dimension(4, "unknown", dimension="负债率", field="max_debt_ratio", gap_text="标的负债率缺失")
        elif target_debt_ratio <= max_debt_ratio:
            add_dimension(4, "match", dimension="负债率", field="max_debt_ratio", match_text="负债率未超过买家上限")
        else:
            add_dimension(4, "mismatch", dimension="负债率", field="max_debt_ratio", gap_text="负债率超过买家上限")

    if possible > 0:
        score = 100.0 * earned / possible
    else:
        # 买家没有任何结构化要求：给中性分，排序交给语义层
        score = 40.0

    # 加分项（不参与归一化）：二级行业一致、现金流状态
    if intent.get("industry_secondary") and intent.get("industry_secondary") in target_l2_values:
        score += 4
        evidence.append(f"二级行业一致：{intent['industry_secondary']}")
    cash_flow_status = str(target.get("cash_flow_status") or "")
    if cash_flow_status == "stable_positive":
        score += 3
        evidence.append("现金流稳定为正")
    elif cash_flow_status == "positive":
        score += 1.5
        evidence.append("现金流为正")

    # 风险提示：买家有风险容忍要求且标的存在风险记录时提示人工核对（不改分）
    if intent.get("major_risk_tolerance_summary") and target.get("risk_summary"):
        gaps.append("买家有风险容忍要求且标的存在风险记录，需人工核对")

    excluded_hit = _excluded_industry_hit(target, intent)
    if excluded_hit:
        excluded_text = f"命中排除项：{excluded_hit}"
        conflicts.insert(0, excluded_text)
        gaps.insert(0, excluded_text)

    if conflicts:
        state = CANDIDATE_STATE_CONFLICT
    elif unknown_dimensions:
        state = CANDIDATE_STATE_POSSIBLE
    else:
        state = CANDIDATE_STATE_COMPATIBLE

    meta = {
        "state": state,
        "conflicts": conflicts,
        "known_count": known_count,
        "unknown_dimensions": unknown_dimensions,
        "excluded_hit": excluded_hit,
        "score_engine": "rule_v3",
    }
    return min(round(score, 2), 100.0), evidence, gaps, meta


def _get_buyer_intent_anchor(db: Session, buyer_intent_id: UUID | None) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              bi.id, bi.buyer_party_id, bp.buyer_name,
              bi.intent_name, bi.industry_primary, bi.industry_secondary,
              bi.industries_json, bi.industry_l2_json,
              bi.excluded_industries_json, bi.industry_focus_tags_json,
               bi.region_scope_summary, bi.region_constraints_json,
               bi.min_revenue_yuan, bi.min_net_profit_yuan,
              bi.min_total_profit_yuan, bi.max_pe,
              bi.max_ps, bi.min_net_margin, bi.min_gross_margin,
              bi.min_valuation_yuan, bi.max_valuation_yuan,
              bi.min_market_cap_yuan, bi.max_market_cap_yuan,
              bi.budget_min_yuan, bi.budget_max_yuan,
              bi.max_debt_ratio, bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment,
              bi.desired_equity_ratio_min, bi.desired_equity_ratio_max,
               bi.preferred_listed_status, bi.acceptable_listed_status_json,
               bi.condition_effects_json, bi.listing_market_region,
              bi.acceptable_cash_flow_status_json, bi.acceptable_profitability_status_json,
              bi.requires_relocation, bi.relocation_target_regions_json,
              bi.requires_return_investment, bi.return_investment_multiple,
              bi.requires_team_retention, bi.earnout_requirement,
              bi.major_risk_tolerance_summary
            from buyer_intent bi
            left join buyer_party bp on bp.id = bi.buyer_party_id
            where bi.id = :buyer_intent_id
              and bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return dict(row)


def _get_seller_target_anchor(db: Session, seller_target_id: UUID | None) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, industry_l1, industry_l2, industry_pairs_json,
              location_province, location_city, location_district,
              current_revenue_yuan, current_net_profit_yuan, current_total_profit_yuan,
              pe_ratio, valuation_yuan, asking_price_yuan, market_cap_yuan, current_debt_ratio,
              cash_flow_status, profitability_status,
              can_control, can_consolidate, transfer_ratio_max, transfer_ratio_min,
              accepts_relocation, accepts_return_investment, management_retention_possible,
              listed_status, listing_market_region,
              risk_summary, gap_summary, business_summary
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
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller target not found.")
    return dict(row)


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


def insert_agent_aborted_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    created_by: UUID = DEFAULT_ADMIN_USER_ID,
) -> None:
    """Mark a turn stopped, written the moment the user asks rather than when
    the worker notices — otherwise a closed tab would leave no record at all."""
    _insert_recommendation_message(
        db,
        session_id=session_id,
        role="tool",
        content_type="json",
        content={"message_type": "agent_aborted", "turn_id": turn_id},
        metadata_json={"message_type": "agent_aborted", "turn_id": turn_id},
        created_by=created_by,
    )


def insert_agent_answer_message(
    db: Session,
    *,
    session_id: UUID,
    turn_id: str,
    markdown: str,
    model_name: str | None,
    generation_mode: str,
) -> UUID:
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
                {"message_type": "agent_answer", "turn_id": turn_id, "markdown": markdown}
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


AGENT_HISTORY_MAX_TURNS = 6
# 兜底而已，正常 6 轮远到不了。超了按整轮丢，不截断。
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


def _enqueue_recommendation_rerank_job(
    db: Session,
    *,
    session_id: UUID,
    mode: str,
    anchor: dict[str, Any],
    candidates: list[dict[str, Any]],
    idempotency_suffix: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    extra_query_lines: list[str] | None = None,
) -> UUID:
    deep_eval_candidates = candidates[:DEEP_EVAL_CANDIDATE_LIMIT]
    query = _build_rerank_query(mode=mode, anchor=anchor)
    if extra_query_lines:
        # Session semantic preferences and the latest user message steer deep eval.
        query = "\n".join([query, "用户会话补充要求：", *extra_query_lines]).strip()
    payload = _json_loads(
        _json_dumps(
            {
                "session_id": session_id,
                "mode": mode,
                "query": query,
                "anchor": anchor,
                "candidates": deep_eval_candidates,
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
              :team_id, :workspace_id, 'recommendation_deep_eval', 110, 'llm',
              'recommendation_session', :session_id, :idempotency_key, :payload_json,
              2, :created_by, :metadata_json
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
            "idempotency_key": (
                f"recommendation_deep_eval:{session_id}:{idempotency_suffix}"
                if idempotency_suffix
                else f"recommendation_deep_eval:{session_id}"
            ),
            "payload_json": payload,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": metadata_json or {"source": "recommendation_candidate_api"},
        },
    ).mappings().one()
    return row["id"]


def _build_rerank_query(*, mode: str, anchor: dict[str, Any]) -> str:
    if mode == "buyer_to_target":
        parts = [
            anchor.get("intent_name"),
            # 原来这里取的是 preference_summary / negative_summary。那两列下线后，
            # 定性内容住进各模块的「其他」，会随搜索文档一起进上下文；rerank 的
            # 查询串改用需求摘要，它同样是整条需求的一句话概括。
            anchor.get("intent_summary"),
            anchor.get("industry_primary"),
            anchor.get("industry_secondary"),
            anchor.get("region_scope_summary"),
        ]
    else:
        parts = [
            anchor.get("target_name"),
            anchor.get("industry_l1"),
            anchor.get("industry_l2"),
            anchor.get("location_province"),
            anchor.get("location_city"),
            anchor.get("location_district"),
            anchor.get("business_summary"),
            anchor.get("risk_summary"),
        ]
    return "\n".join(str(part) for part in parts if part)


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
