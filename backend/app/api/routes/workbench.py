from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import (
    business_update_visible_sql,
    extracted_action_visible_sql,
    owner_scope_required,
    relation_visible_sql,
)
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.api.routes.background_jobs import _failure_summary, _queue_summary

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
    weekly_new_target_count: int = 0
    weekly_new_buyer_intent_count: int = 0
    weekly_updated_target_count: int = 0
    weekly_business_update_count: int = 0


class WorkbenchTaskBoardOut(BaseModel):
    groups: list[WorkbenchActionGroupOut]
    auto_applied_recent: list[dict[str, Any]]
    exception_items: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    quick_actions: list[dict[str, Any]]
    overview: dict[str, Any]
    queue_summary: dict[str, Any]
    failure_summary: dict[str, Any]


class WorkbenchOut(BaseModel):
    groups: list[WorkbenchActionGroupOut]
    recent_updates: list[dict[str, Any]]
    recent_relations: list[dict[str, Any]]
    overview: WorkbenchOverviewOut


GROUP_LABELS = {
    "seller_update_review": "标的更新待复核",
    "buyer_intent_review": "买家/意向更新待复核",
    "relation_progress_review": "关系进展待复核",
    "parse_exception": "解析异常",
}

FIELD_LABELS = {
    "business_summary": "业务简介",
    "industry_primary": "一级行业",
    "industry_secondary": "二级行业",
    "headquarter_province": "总部省份",
    "headquarter_city": "总部城市",
    "listed_status": "上市状态",
    "current_revenue_yuan": "营业收入",
    "current_net_profit_yuan": "净利润",
    "valuation_yuan": "估值",
    "risk_summary": "风险摘要",
    "intent_summary": "意向摘要",
    "raw_requirement_text": "原始需求",
    "region_scope_summary": "地域要求",
    "market_cap_range_summary": "市值范围",
    "preferred_listed_status": "上市要求",
    "listing_board_requirement_summary": "板块要求",
    "financing_stage_requirement_summary": "融资阶段",
    "premium_tolerance_summary": "溢价要求",
    "debt_ratio_requirement_summary": "负债率要求",
    "major_risk_tolerance_summary": "风险容忍度",
    "buyer_industry_advantage_summary": "产业优势",
    "preference_summary": "其他偏好",
}


@router.get("", response_model=WorkbenchOut)
def get_workbench(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    pending_actions = _pending_actions(db, current_user, limit=80)
    groups = _group_actions(pending_actions)
    recent_updates = _recent_updates(db, current_user)
    recent_relations = _recent_relations(db, current_user)
    overview = _overview(db, current_user, pending_review_count=sum(group["count"] for group in groups))
    return {
        "groups": groups,
        "recent_updates": recent_updates,
        "recent_relations": recent_relations,
        "overview": overview,
    }


@router.get("/task-board", response_model=WorkbenchTaskBoardOut)
def get_workbench_task_board(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    pending_actions = _pending_actions(db, current_user, limit=120)
    groups = _group_actions(pending_actions, item_limit=8)
    auto_applied_recent = _auto_applied_recent(db, current_user)
    exception_items = _exception_items(db, current_user)
    recent_activity = _recent_activity(db, current_user)
    overview = _task_board_overview(
        db,
        current_user,
        pending_review_count=sum(group["count"] for group in groups),
        auto_applied_count=len(auto_applied_recent),
        exception_count=len(exception_items),
    )
    queue_summary = (
        _queue_summary(db, include_empty=True, lookback_hours=24)
        if current_user.is_admin
        else _empty_queue_summary(db)
    )
    failure_summary = (
        _failure_summary(db, lookback_hours=168, limit=10)
        if current_user.is_admin
        else _empty_failure_summary(db)
    )
    return {
        "groups": groups,
        "auto_applied_recent": auto_applied_recent,
        "exception_items": exception_items,
        "recent_activity": recent_activity,
        "quick_actions": _quick_actions(overview),
        "overview": overview,
        "queue_summary": queue_summary,
        "failure_summary": failure_summary,
    }


def _pending_actions(db: Session, current_user: CurrentUser, *, limit: int = 80) -> list[dict[str, Any]]:
    scope_clause = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "limit": limit}
    if owner_scope_required(current_user):
        scope_clause = f"and {extracted_action_visible_sql('a')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
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
              {scope_clause}
            order by a.created_at desc
            limit :limit
            """
        ),
        params,
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
    proposed_fields = _proposed_field_labels(action.get("proposed_changes_json"))
    action["task_title"] = _task_title(action, entity_name)
    action["task_subtitle"] = _task_subtitle(action, proposed_fields)
    action["target_display_name"] = entity_name
    action["proposed_field_labels"] = proposed_fields
    action["proposed_field_count"] = len(proposed_fields)
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
        return f"复核买家/意向更新：{entity_name}"
    if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
        return "复核关系进展"
    if action_type == "seller_event":
        return f"复核标的事件：{entity_name}"
    return f"复核解析结果：{entity_name}"


def _task_subtitle(action: dict[str, Any], proposed_fields: list[str]) -> str | None:
    evidence = action.get("raw_evidence_text") or action.get("business_update_raw_text") or ""
    if proposed_fields:
        visible = "、".join(proposed_fields[:4])
        suffix = "等" if len(proposed_fields) > 4 else ""
        return f"识别到 {len(proposed_fields)} 项更新：{visible}{suffix}"
    return _truncate_text(evidence, 90)


def _proposed_field_labels(proposed_changes: Any) -> list[str]:
    if not isinstance(proposed_changes, dict):
        return []
    labels: list[str] = []
    for field in proposed_changes:
        labels.append(FIELD_LABELS.get(str(field), str(field)))
    return labels


def _task_priority(action: dict[str, Any]) -> str:
    if action.get("action_type") == "unresolved_item":
        return "high"
    if _categorize_action(action) == "parse_exception":
        return "high"
    return "normal"


def _auto_applied_recent(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    scope_clause = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if owner_scope_required(current_user):
        scope_clause = f"and {extracted_action_visible_sql('a')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
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
              {scope_clause}
            order by a.applied_at desc
            limit 10
            """
        ),
        params,
    ).mappings().all()
    return [_with_task_fields(dict(row)) for row in rows]


def _exception_items(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    if not current_user.is_admin:
        return []
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
              and coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true'
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


def _recent_activity(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    bu_scope_clause = ""
    relation_scope_clause = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if owner_scope_required(current_user):
        bu_scope_clause = f"and {business_update_visible_sql('bu')}"
        relation_scope_clause = f"and {relation_visible_sql('r')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
            with action_summary as (
              select
                a.business_update_id,
                count(*)::int as action_count,
                count(*) filter (where a.review_status = 'pending_review')::int as pending_count,
                string_agg(distinct coalesce(a.target_entity_type, ''), ',') as target_types,
                max(st.target_name) as seller_target_name,
                max(bi.intent_name) as buyer_intent_name,
                max(bp.buyer_name) as buyer_name
              from extracted_action a
              left join seller_target st
                on st.id = a.target_entity_id and a.target_entity_type = 'seller_target'
              left join buyer_intent bi
                on bi.id = a.target_entity_id and a.target_entity_type = 'buyer_intent'
              left join buyer_party bp
                on bp.id = bi.buyer_party_id
              where a.team_id = :team_id and a.workspace_id = :workspace_id
              group by a.business_update_id
            ),
            business_update_activity as (
              select
                'business_update' as activity_type,
                bu.id as entity_id,
                bu.processing_status as status,
                case
                  when bu.processing_status = 'failed' then '解析异常'
                  when coalesce(summary.target_types, '') like '%seller_target%'
                    or jsonb_array_length(bu.bound_seller_target_ids_json) > 0 then '标的更新'
                  when coalesce(summary.target_types, '') like '%buyer_intent%'
                    or jsonb_array_length(bu.bound_buyer_party_ids_json) > 0
                    or jsonb_array_length(bu.bound_buyer_intent_ids_json) > 0 then '买家更新'
                  else '业务更新'
                end as activity_label,
                coalesce(summary.seller_target_name, summary.buyer_intent_name, summary.buyer_name, '未绑定对象') as object_name,
                case
                  when coalesce(summary.pending_count, 0) > 0 then '待复核 ' || summary.pending_count::text || ' 项'
                  when coalesce(summary.action_count, 0) > 0 then '已解析 ' || summary.action_count::text || ' 项更新'
                  when bu.processing_status = 'pending' then '处理中'
                  when bu.processing_status = 'processing' then '处理中'
                  when bu.processing_status = 'failed' then '需要查看异常'
                  else '已记录'
                end as summary,
                bu.created_at as happened_at,
                '/updates/' || bu.id::text as route
              from business_update bu
              left join action_summary summary on summary.business_update_id = bu.id
              where bu.team_id = :team_id and bu.workspace_id = :workspace_id
                {bu_scope_clause}
            ),
            relation_activity as (
              select
                'relation_event' as activity_type,
                event.id as entity_id,
                event.event_type as status,
                '推荐进展' as activity_label,
                nullif(concat_ws(' → ', coalesce(bp.buyer_name, bi.intent_name), st.target_name), '') as object_name,
                coalesce(event.title, event.content, event.next_step, event.event_type) as summary,
                event.event_time as happened_at,
                '/targets/' || event.seller_target_id::text as route
              from relation_event event
              join buyer_seller_relation r on r.id = event.relation_id
              join seller_target st on st.id = event.seller_target_id
              join buyer_intent bi on bi.id = event.buyer_intent_id
              left join buyer_party bp on bp.id = event.buyer_party_id
              where event.team_id = :team_id and event.workspace_id = :workspace_id
                {relation_scope_clause}
            )
            select *
            from (
              select * from business_update_activity
              union all
              select * from relation_activity
            ) activity
            order by happened_at desc
            limit 20
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            **dict(row),
            "entity_id": str(row["entity_id"]),
            "happened_at": row["happened_at"].isoformat() if row["happened_at"] else None,
            "title": _activity_title(dict(row)),
            "subtitle": _truncate_text(row.get("summary"), 120),
        }
        for row in rows
    ]


def _activity_title(row: dict[str, Any]) -> str:
    label = row.get("activity_label") or "动态"
    object_name = row.get("object_name") or "未绑定对象"
    return f"{label}：{object_name}"


def _task_board_overview(
    db: Session,
    current_user: CurrentUser,
    *,
    pending_review_count: int,
    auto_applied_count: int,
    exception_count: int,
) -> dict[str, Any]:
    overview = _overview(db, current_user, pending_review_count=pending_review_count)
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


def _recent_updates(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    scope_clause = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if owner_scope_required(current_user):
        scope_clause = f"and {business_update_visible_sql('bu')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
            select
              bu.id, bu.raw_text, bu.input_type, bu.processing_status,
              bu.bound_seller_target_ids_json, bu.bound_buyer_party_ids_json, bu.bound_buyer_intent_ids_json,
              bu.bound_recommendation_session_id, bu.created_by,
              bu.created_at::text as created_at, bu.metadata_json
            from business_update bu
            where bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
              {scope_clause}
            order by bu.created_at desc
            limit 8
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _recent_relations(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    scope_clause = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if owner_scope_required(current_user):
        scope_clause = f"and {relation_visible_sql('r')}"
        params["scope_user_id"] = current_user.user_id
    rows = db.execute(
        text(
            f"""
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
              {scope_clause}
            order by coalesce(r.last_event_at, r.updated_at, r.created_at) desc
            limit 8
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


def _overview(db: Session, current_user: CurrentUser, *, pending_review_count: int) -> dict[str, int]:
    target_scope = ""
    intent_scope = ""
    business_update_scope = ""
    update_log_scope = ""
    relation_scope = ""
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if owner_scope_required(current_user):
        target_scope = "and seller_target.owner_user_id = :scope_user_id"
        intent_scope = "and buyer_intent.owner_user_id = :scope_user_id"
        business_update_scope = f"and {business_update_visible_sql('business_update')}"
        update_log_scope = """
                 and exists (
                   select 1
                   from seller_target st
                   where st.id = action_application_log.entity_id
                     and st.owner_user_id = :scope_user_id
                     and st.deleted_at is null
                 )
        """
        relation_scope = f"and {relation_visible_sql('buyer_seller_relation')}"
        params["scope_user_id"] = current_user.user_id
    row = db.execute(
        text(
            f"""
            with week_boundary as (
              select (date_trunc('week', now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai') as week_start
            )
            select
              (select count(*) from business_update
               where team_id = :team_id and workspace_id = :workspace_id
                 and created_at >= now() - interval '7 days'
                 {business_update_scope}) as recent_update_count,
              (select count(*) from seller_target, week_boundary
               where team_id = :team_id and workspace_id = :workspace_id
                 and deleted_at is null
                 and created_at >= week_boundary.week_start
                 {target_scope}) as weekly_new_target_count,
              (select count(*) from buyer_intent, week_boundary
               where team_id = :team_id and workspace_id = :workspace_id
                 and deleted_at is null
                 and created_at >= week_boundary.week_start
                 {intent_scope}) as weekly_new_buyer_intent_count,
              (select count(distinct entity_id) from action_application_log, week_boundary
               where team_id = :team_id and workspace_id = :workspace_id
                 and entity_type = 'seller_target'
                 and applied_at >= week_boundary.week_start
                 {update_log_scope}) as weekly_updated_target_count,
              (select count(*) from business_update, week_boundary
               where team_id = :team_id and workspace_id = :workspace_id
                 and created_at >= week_boundary.week_start
                 {business_update_scope}) as weekly_business_update_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status = 'failed'
                 and coalesce(metadata_json ->> 'failure_ignored', 'false') <> 'true') as failed_job_count,
              (select count(*) from background_job
               where team_id = :team_id and workspace_id = :workspace_id
                 and status in ('queued', 'running', 'retry_waiting')) as running_job_count,
              (select count(*) from buyer_seller_relation
               where team_id = :team_id and workspace_id = :workspace_id
                 and deleted_at is null
                 {relation_scope}) as active_relation_count
            """
        ),
        params,
    ).mappings().one()
    return {
        "pending_review_count": pending_review_count,
        "recent_update_count": int(row["recent_update_count"]),
        "failed_job_count": int(row["failed_job_count"]) if current_user.is_admin else 0,
        "running_job_count": int(row["running_job_count"]) if current_user.is_admin else 0,
        "active_relation_count": int(row["active_relation_count"]),
        "weekly_new_target_count": int(row["weekly_new_target_count"]),
        "weekly_new_buyer_intent_count": int(row["weekly_new_buyer_intent_count"]),
        "weekly_updated_target_count": int(row["weekly_updated_target_count"]),
        "weekly_business_update_count": int(row["weekly_business_update_count"]),
    }


def _empty_queue_summary(db: Session) -> dict[str, Any]:
    generated_at = db.execute(text("select now()::text")).scalar_one()
    return {
        "generated_at": generated_at,
        "totals": {
            "queue_count": 0,
            "active_queue_count": 0,
            "failed_queue_count": 0,
            "active_job_count": 0,
            "failed_job_count": 0,
            "ignored_failed_job_count": 0,
            "queued_job_count": 0,
            "running_job_count": 0,
            "retry_waiting_job_count": 0,
        },
        "queues": [],
        "debug_ref": {},
    }


def _empty_failure_summary(db: Session) -> dict[str, Any]:
    generated_at = db.execute(text("select now()::text")).scalar_one()
    return {
        "generated_at": generated_at,
        "lookback_hours": 168,
        "include_ignored": False,
        "include_archived": False,
        "include_test_data": False,
        "totals": {
            "failed_job_count": 0,
            "failed_queue_count": 0,
            "failed_job_type_count": 0,
            "recent_failure_count": 0,
        },
        "by_queue": [],
        "by_job_type": [],
        "recent_failures": [],
        "debug_ref": {},
    }
