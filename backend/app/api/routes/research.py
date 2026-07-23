"""Trigger seller research and review evidence-backed proposals."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import ensure_entity_visible, ensure_entity_writable
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.jobs.handlers.common import _get_default_node_config
from backend.app.jobs.handlers.research import RESEARCH_NODE_NAME
from backend.app.services.profile_sections import PROFILE_SECTION_LABELS
from backend.app.services.research_apply import ResearchApplyError, apply_research_proposal
from backend.app.services.search_service import get_default_search_provider

router = APIRouter(prefix="/research", tags=["research"])


class SellerResearchBatchRequest(BaseModel):
    seller_target_ids: list[UUID] = Field(min_length=1, max_length=50)


class ResearchJobOut(BaseModel):
    job_id: UUID
    seller_target_id: UUID
    status: str
    queue_name: str
    reused_existing: bool = False


class ResearchBatchOut(BaseModel):
    jobs: list[ResearchJobOut]
    queued_count: int
    reused_count: int


class ResearchProposalOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    job_id: UUID | None
    proposal_kind: str
    section_code: str | None
    section_label: str | None = None
    field_path: str | None
    proposed_value_json: dict[str, Any]
    current_value_json: dict[str, Any]
    conflict_kind: str
    period_label: str | None
    as_of_date: str | None
    source_type: str | None
    source_url: str | None
    source_title: str | None
    source_excerpt: str | None
    anchor_matches_json: list[dict[str, Any]]
    review_status: str
    reviewed_at: str | None
    created_at: str


@router.post("/seller-targets/{seller_target_id}", response_model=ResearchJobOut, status_code=status.HTTP_201_CREATED)
def create_seller_research_job(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_research_ready(db)
    ensure_entity_writable(
        db,
        current_user,
        entity_type="seller_target",
        entity_id=seller_target_id,
    )
    row, reused = _enqueue_seller_research_job(
        db,
        seller_target_id=seller_target_id,
        user_id=current_user.user_id,
    )
    db.commit()
    return _research_job_output(row, seller_target_id=seller_target_id, reused=reused)


@router.post("/seller-targets", response_model=ResearchBatchOut, status_code=status.HTTP_201_CREATED)
def create_seller_research_jobs(
    payload: SellerResearchBatchRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_research_ready(db)
    target_ids = list(dict.fromkeys(payload.seller_target_ids))
    jobs: list[dict[str, Any]] = []
    reused_count = 0
    for target_id in target_ids:
        ensure_entity_writable(
            db,
            current_user,
            entity_type="seller_target",
            entity_id=target_id,
        )
        row, reused = _enqueue_seller_research_job(
            db,
            seller_target_id=target_id,
            user_id=current_user.user_id,
        )
        jobs.append(_research_job_output(row, seller_target_id=target_id, reused=reused))
        reused_count += int(reused)
    db.commit()
    return {
        "jobs": jobs,
        "queued_count": len(jobs) - reused_count,
        "reused_count": reused_count,
    }


@router.get("/seller-targets/{seller_target_id}/status")
def get_seller_research_status(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_entity_visible(
        db,
        current_user,
        entity_type="seller_target",
        entity_id=seller_target_id,
    )
    target = db.execute(
        text(
            """
            select last_research_at::text as last_research_at,
                   research_last_outcome
            from seller_target
            where id = :target_id and team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    latest_job = db.execute(
        text(
            """
            select id, status, result_json, error_code, error_message,
                   created_at::text as created_at, finished_at::text as finished_at
            from background_job
            where team_id = :team_id and workspace_id = :workspace_id
              and job_type = 'seller_target_research'
              and entity_type = 'seller_target' and entity_id = :target_id
            order by created_at desc limit 1
            """
        ),
        {
            "target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return {
        "seller_target_id": str(seller_target_id),
        **dict(target or {}),
        "latest_job": dict(latest_job) if latest_job else None,
    }


@router.get("/proposals", response_model=list[ResearchProposalOut])
def list_research_proposals(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    entity_type: Literal["seller_target"] = "seller_target",
    entity_id: UUID = Query(...),
    review_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[dict[str, Any]]:
    ensure_entity_visible(db, current_user, entity_type=entity_type, entity_id=entity_id)
    where = [
        "team_id = :team_id",
        "workspace_id = :workspace_id",
        "entity_type = :entity_type",
        "entity_id = :entity_id",
        "deleted_at is null",
    ]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "limit": limit,
    }
    if review_status:
        where.append("review_status = :review_status")
        params["review_status"] = review_status
    rows = db.execute(
        text(
            f"""
            select {_proposal_select_columns()}
            from research_proposal
            where {' and '.join(where)}
            order by created_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return [_proposal_output(row) for row in rows]


@router.post("/proposals/{proposal_id}/accept", response_model=ResearchProposalOut)
def accept_research_proposal(
    proposal_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal = _get_research_proposal(db, proposal_id)
    ensure_entity_writable(
        db,
        current_user,
        entity_type=str(proposal["entity_type"]),
        entity_id=proposal["entity_id"],
    )
    if proposal["review_status"] != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending research proposals can be accepted.",
        )
    try:
        apply_research_proposal(db, proposal, user_id=current_user.user_id)
    except ResearchApplyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    _set_proposal_review_status(
        db,
        proposal_id,
        review_status="accepted",
        user_id=current_user.user_id,
    )
    db.commit()
    return _proposal_output(_get_research_proposal(db, proposal_id))


@router.post("/proposals/{proposal_id}/reject", response_model=ResearchProposalOut)
def reject_research_proposal(
    proposal_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    proposal = _get_research_proposal(db, proposal_id)
    ensure_entity_writable(
        db,
        current_user,
        entity_type=str(proposal["entity_type"]),
        entity_id=proposal["entity_id"],
    )
    if proposal["review_status"] != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending research proposals can be rejected.",
        )
    _set_proposal_review_status(
        db,
        proposal_id,
        review_status="rejected",
        user_id=current_user.user_id,
    )
    db.commit()
    return _proposal_output(_get_research_proposal(db, proposal_id))


def _ensure_research_ready(db: Session) -> None:
    if get_default_search_provider(db) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="尚未配置搜索供应商，请先在设置页配置 Tavily 搜索。",
        )
    try:
        _get_default_node_config(db, RESEARCH_NODE_NAME)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="尚未配置 seller_target_researcher 调研节点及 Prompt。",
        ) from exc


def _enqueue_seller_research_job(
    db: Session,
    *,
    seller_target_id: UUID,
    user_id: UUID,
) -> tuple[dict[str, Any], bool]:
    existing = db.execute(
        text(
            """
            select id, status, queue_name
            from background_job
            where team_id = :team_id and workspace_id = :workspace_id
              and job_type = 'seller_target_research'
              and entity_type = 'seller_target' and entity_id = :target_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc limit 1
            """
        ),
        {
            "target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if existing:
        return dict(existing), True
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            ) values (
              :team_id, :workspace_id, 'seller_target_research', 45, 'llm',
              'seller_target', :target_id, :idempotency_key, :payload_json,
              1, :created_by, :metadata_json
            ) returning id, status, queue_name
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "target_id": seller_target_id,
            "idempotency_key": f"seller_target_research:{seller_target_id}:{uuid4()}",
            "payload_json": {"seller_target_id": str(seller_target_id)},
            "created_by": user_id,
            "metadata_json": {"source": "seller_target_research_api"},
        },
    ).mappings().one()
    return dict(row), False


def _research_job_output(
    row: dict[str, Any],
    *,
    seller_target_id: UUID,
    reused: bool,
) -> dict[str, Any]:
    return {
        "job_id": row["id"],
        "seller_target_id": seller_target_id,
        "status": row["status"],
        "queue_name": row["queue_name"],
        "reused_existing": reused,
    }


def _set_proposal_review_status(
    db: Session,
    proposal_id: UUID,
    *,
    review_status: str,
    user_id: UUID,
) -> None:
    db.execute(
        text(
            """
            update research_proposal
            set review_status = :review_status, reviewed_by = :user_id,
                reviewed_at = now(), updated_at = now()
            where id = :proposal_id and team_id = :team_id and workspace_id = :workspace_id
            """
        ),
        {
            "proposal_id": proposal_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "review_status": review_status,
            "user_id": user_id,
        },
    )


def _get_research_proposal(db: Session, proposal_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select {_proposal_select_columns()}
            from research_proposal
            where id = :proposal_id and team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "proposal_id": proposal_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="调研建议不存在。")
    return dict(row)


def _proposal_select_columns() -> str:
    return """
      id, entity_type, entity_id, job_id, proposal_kind, section_code, field_path,
      proposed_value_json, current_value_json, conflict_kind, period_label,
      as_of_date::text as as_of_date, source_type, source_url, source_title,
      source_excerpt, anchor_matches_json, review_status,
      reviewed_at::text as reviewed_at, created_at::text as created_at
    """


def _proposal_output(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["section_label"] = PROFILE_SECTION_LABELS.get(str(result.get("section_code") or ""))
    result["anchor_matches_json"] = list(result.get("anchor_matches_json") or [])
    result["proposed_value_json"] = dict(result.get("proposed_value_json") or {})
    result["current_value_json"] = dict(result.get("current_value_json") or {})
    return result
