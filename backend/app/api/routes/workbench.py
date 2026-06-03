from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.api.routes.background_jobs import _queue_summary

router = APIRouter(prefix="/workbench", tags=["workbench"])


class WorkbenchActionGroupOut(BaseModel):
    key: str
    label: str
    count: int
    items: list[dict[str, Any]]


class WorkbenchOverviewOut(BaseModel):
    pending_review_count: int
    recent_update_count: int
    failed_job_count: int
    running_job_count: int
    active_relation_count: int


class WorkbenchTaskBoardOut(BaseModel):
    groups: list[WorkbenchActionGroupOut]
    auto_applied_recent: list[dict[str, Any]]
    exception_items: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    quick_actions: list[dict[str, Any]]
    overview: dict[str, Any]
    queue_summary: dict[str, Any]


class WorkbenchOut(BaseModel):
    groups: list[WorkbenchActionGroupOut]
    recent_updates: list[dict[str, Any]]
    recent_relations: list[dict[str, Any]]
    overview: WorkbenchOverviewOut


GROUP_LABELS = {
    "seller_update_review": "标的更新待复核",
    "buyer_intent_review": "买家意向更新待复核",
    "relation_progress_review": "关系进展待复核",
    "parse_exception": "解析异常",
}


@router.get("", response_model=WorkbenchOut)
def get_workbench(db: Session = Depends(get_db)) -> dict[str, Any]:
    pending_actions = _pending_actions(db)
    groups = _group_actions(pending_actions)
    recent_updates = _recent_updates(db)
    recent_relations = _recent_relations(db)
    overview = _overview(db, pending_review_count=sum(group["count"] for group in groups))
    return {
        "groups": groups,
        "recent_updates": recent_updates,
        "recent_relations": recent_relations,
        "overview": overview,
    }


@router.get("/task-board", response_model=WorkbenchTaskBoardOut)
def get_workbench_task_board(db: Session = Depends(get_db)) -> dict[str, Any]:
    pending_actions = _pending_actions(db, limit=120)
    groups = _group_actions(pending_actions, item_limit=8)
    auto_applied_recent = _auto_applied_recent(db)
    exception_items = _exception_items(db)
    recent_activity = _recent_activity(db)
    overview = _task_board_overview(
        db,
        pending_review_count=sum(group["count"] for group in groups),
        auto_applied_count=len(auto_applied_recent),
        exception_count=len(exception_items),
    )
    queue_summary = _queue_summary(db, include_empty=True, lookback_hours=24)
    return {
        "groups": groups,
        "auto_applied_recent": auto_applied_recent,
        "exception_items": exception_items,
        "recent_activity": recent_activity,
        "quick_actions": _quick_actions(overview),
        "overview": overview,
        "queue_summary": queue_summary,
    }


def _pending_actions(db: Session, *, limit: int = 80) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              a.id, a.business_update_id, a.action_type, a.target_entity_type, a.target_entity_id,
              a.proposed_changes_json, a.raw_evidence_text, a.evidence_id, a.confidence, a.review_status,
              a.reviewed_by, a.reviewed_at::text as reviewed_at, a.applied_at::text as applied_at,
              a.metadata_json, a.created_at::text as created_at,
              bu.raw_text as business_update_raw_text,
              st.target_name as seller_target_name,
              bi.intent_name as buyer_intent_name
            from extracted_action a
            join business_update bu on bu.id = a.business_update_id
            left join seller_target st
              on st.id = a.target_entity_id and a.target_entity_type = 'seller_target'
            left join buyer_intent bi
              on bi.id = a.target_entity_id and a.target_entity_type = 'buyer_intent'
            where a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.review_status = 'pending_review'
            order by a.created_at desc
            limit :limit
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit},
    ).mappings().all()
    return [_with_task_fields(dict(row)) for row in rows]


def _group_actions(actions: list[dict[str, Any]], *, item_limit: int = 5) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        key = _categorize_action(action)
        grouped.setdefault(key, []).append(action)

    groups: list[dict[str, Any]] = []
    for key in ["seller_update_review", "buyer_intent_review", "relation_progress_review", "parse_exception"]:
        items = grouped.get(key, [])
        if items:
            groups.append({"key": key, "label": GROUP_LABELS[key], "count": len(items), "items": items[:item_limit]})
    return groups


def _categorize_action(action: dict[str, Any]) -> str:
    action_type = action["action_type"]
    target_type = action.get("target_entity_type")
    if action_type in {"seller_fact_update", "seller_event"} or target_type == "seller_target":
        return "seller_update_review"
    if action_type == "buyer_intent_update" or target_type == "buyer_intent":
        return "buyer_intent_review"
    if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
        return "relation_progress_review"
    return "parse_exception"


def _with_task_fields(action: dict[str, Any]) -> dict[str, Any]:
    entity_name = action.get("seller_target_name") or action.get("buyer_intent_name")
    if not entity_name:
        entity_name = action.get("target_entity_type") or "未绑定对象"
    evidence = action.get("raw_evidence_text") or action.get("business_update_raw_text") or ""
    action["task_title"] = _task_title(action, entity_name)
    action["task_subtitle"] = _truncate_text(evidence, 90)
    action["task_group_key"] = _categorize_action(action)
    action["task_group_label"] = GROUP_LABELS.get(action["task_group_key"], "待复核")
    action["task_priority"] = _task_priority(action)
    action["debug_ref"] = {
        "entity_type": "business_update",
        "entity_id": str(action["business_update_id"]),
    }
    action["review_route"] = f"/updates/{action['business_update_id']}"
    return action


def _task_title(action: dict[str, Any], entity_name: str) -> str:
    action_type = action.get("action_type")
    if action_type == "seller_fact_update":
        return f"复核标的更新：{entity_name}"
    if action_type == "buyer_intent_update":
        return f"复核买家意向：{entity_name}"
    if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
        return "复核关系进展"
    if action_type == "seller_event":
        return f"复核标的事件：{entity_name}"
    return f"复核解析结果：{entity_name}"


def _task_priority(action: dict[str, Any]) -> str:
    confidence = action.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence_value = None
    if action.get("action_type") == "unresolved_item" or confidence_value is None:
        return "high"
    if confidence_value < 0.6:
        return "high"
    if confidence_value < 0.8:
        return "medium"
    return "normal"


def _auto_applied_recent(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              a.id, a.business_update_id, a.action_type, a.target_entity_type, a.target_entity_id,
              a.proposed_changes_json, a.raw_evidence_text, a.evidence_id, a.confidence, a.review_status,
              a.applied_at::text as applied_at, a.created_at::text as created_at,
              bu.raw_text as business_update_raw_text,
              st.target_name as seller_target_name,
              bi.intent_name as buyer_intent_name
            from extracted_action a
            join business_update bu on bu.id = a.business_update_id
            left join seller_target st
              on st.id = a.target_entity_id and a.target_entity_type = 'seller_target'
            left join buyer_intent bi
              on bi.id = a.target_entity_id and a.target_entity_type = 'buyer_intent'
            where a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.review_status = 'auto_accepted'
              and a.applied_at is not null
            order by a.applied_at desc
            limit 10
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [_with_task_fields(dict(row)) for row in rows]


def _exception_items(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, job_type, status, queue_name, entity_type, entity_id,
              error_code, error_message, attempt_count, max_attempts,
              created_at::text as created_at, updated_at::text as updated_at,
              metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and status = 'failed'
            order by updated_at desc
            limit 10
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [
        {
            **dict(row),
            "task_title": f"任务失败：{row['job_type']}",
            "task_subtitle": _truncate_text(row["error_message"], 90),
            "task_priority": "high",
            "debug_ref": {"entity_type": "background_job", "entity_id": str(row["id"])},
        }
        for row in rows
    ]


def _recent_activity(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select *
            from (
              select
                'business_update' as activity_type,
                id as entity_id,
                processing_status as status,
                left(coalesce(raw_text, ''), 140) as title,
                created_at as happened_at
              from business_update
              where team_id = :team_id and workspace_id = :workspace_id
              union all
              select
                'relation_event' as activity_type,
                id as entity_id,
                event_type as status,
                coalesce(title, content, '') as title,
                event_time as happened_at
              from relation_event
              where team_id = :team_id and workspace_id = :workspace_id
              union all
              select
                'background_job' as activity_type,
                id as entity_id,
                status,
                job_type as title,
                updated_at as happened_at
              from background_job
              where team_id = :team_id and workspace_id = :workspace_id
            ) activity
            order by happened_at desc
            limit 20
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [
        {
            **dict(row),
            "entity_id": str(row["entity_id"]),
            "happened_at": row["happened_at"].isoformat() if row["happened_at"] else None,
        }
        for row in rows
    ]


def _task_board_overview(
    db: Session,
    *,
    pending_review_count: int,
    auto_applied_count: int,
    exception_count: int,
) -> dict[str, Any]:
    overview = _overview(db, pending_review_count=pending_review_count)
    return {
        **overview,
        "auto_applied_review_count": auto_applied_count,
        "exception_count": exception_count,
        "mode": "auto_apply_then_review",
    }


def _quick_actions(overview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": "create_business_update",
            "label": "录入更新",
            "route": None,
            "action": "open_business_update_drawer",
            "badge_count": None,
        },
        {
            "key": "review_pending",
            "label": "复核待处理",
            "route": "/updates",
            "action": "open_review_queue",
            "badge_count": overview.get("pending_review_count"),
        },
        {
            "key": "inspect_debug",
            "label": "查看异常",
            "route": "/debug",
            "action": "open_debug_center",
            "badge_count": overview.get("exception_count"),
        },
    ]


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 1] + "…"


def _recent_updates(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json, bound_buyer_intent_ids_json,
              bound_recommendation_session_id, created_by,
              created_at::text as created_at, metadata_json
            from business_update
            where team_id = :team_id
              and workspace_id = :workspace_id
            order by created_at desc
            limit 8
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _recent_relations(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              r.id, r.status, r.status_reason, r.last_event_at::text as last_event_at,
              r.last_event_summary, r.buyer_intent_id, r.buyer_party_id, r.seller_target_id,
              bi.intent_name as buyer_intent_name, bp.buyer_name, st.target_name as seller_target_name
            from buyer_seller_relation r
            join buyer_intent bi on bi.id = r.buyer_intent_id
            join seller_target st on st.id = r.seller_target_id
            left join buyer_party bp on bp.id = r.buyer_party_id
            where r.team_id = :team_id
              and r.workspace_id = :workspace_id
              and r.deleted_at is null
            order by coalesce(r.last_event_at, r.updated_at, r.created_at) desc
            limit 8
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _overview(db: Session, *, pending_review_count: int) -> dict[str, int]:
    row = db.execute(
        text(
            """
            select
              (select count(*) from business_update
               where team_id = :team_id and workspace_id = :workspace_id
                 and created_at >= now() - interval '7 days') as recent_update_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'failed') as failed_job_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status in ('queued', 'running', 'retry_waiting')) as running_job_count,
              (select count(*) from buyer_seller_relation
               where team_id = :team_id and workspace_id = :workspace_id
                 and deleted_at is null) as active_relation_count
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one()
    return {
        "pending_review_count": pending_review_count,
        "recent_update_count": int(row["recent_update_count"]),
        "failed_job_count": int(row["failed_job_count"]),
        "running_job_count": int(row["running_job_count"]),
        "active_relation_count": int(row["active_relation_count"]),
    }
