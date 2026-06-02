from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

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


def _pending_actions(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              a.id, a.business_update_id, a.action_type, a.target_entity_type, a.target_entity_id,
              a.proposed_changes_json, a.raw_evidence_text, a.confidence, a.review_status,
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
            limit 80
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


def _group_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        key = _categorize_action(action)
        grouped.setdefault(key, []).append(action)

    groups: list[dict[str, Any]] = []
    for key in ["seller_update_review", "buyer_intent_review", "relation_progress_review", "parse_exception"]:
        items = grouped.get(key, [])
        if items:
            groups.append({"key": key, "label": GROUP_LABELS[key], "count": len(items), "items": items[:5]})
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
