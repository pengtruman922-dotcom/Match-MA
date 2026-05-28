from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(tags=["extracted-actions"])


class ExtractedActionCreate(BaseModel):
    action_type: str
    target_entity_type: str | None = None
    target_entity_id: UUID | None = None
    proposed_changes_json: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_text: str | None = None
    confidence: Decimal | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ExtractedActionReviewUpdate(BaseModel):
    review_status: str


class ExtractedActionOut(BaseModel):
    id: UUID
    business_update_id: UUID
    action_type: str
    target_entity_type: str | None
    target_entity_id: UUID | None
    proposed_changes_json: dict[str, Any]
    raw_evidence_text: str | None
    confidence: Decimal | None
    review_status: str
    reviewed_by: UUID | None
    reviewed_at: str | None
    applied_at: str | None
    metadata_json: dict[str, Any]
    created_at: str


@router.post(
    "/business-updates/{business_update_id}/extracted-actions",
    response_model=ExtractedActionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_extracted_action(
    business_update_id: UUID,
    payload: ExtractedActionCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_business_update_exists(db, business_update_id)

    statement = text(
        """
        insert into extracted_action (
          team_id, workspace_id, business_update_id,
          action_type, target_entity_type, target_entity_id,
          proposed_changes_json, raw_evidence_text, confidence, metadata_json
        )
        values (
          :team_id, :workspace_id, :business_update_id,
          :action_type, :target_entity_type, :target_entity_id,
          :proposed_changes_json, :raw_evidence_text, :confidence, :metadata_json
        )
        returning
          id, business_update_id, action_type, target_entity_type, target_entity_id,
          proposed_changes_json, raw_evidence_text, confidence, review_status,
          reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
          metadata_json, created_at::text as created_at
        """
    ).bindparams(
        bindparam("proposed_changes_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
    )

    row = db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
            "action_type": payload.action_type,
            "target_entity_type": payload.target_entity_type,
            "target_entity_id": payload.target_entity_id,
            "proposed_changes_json": payload.proposed_changes_json,
            "raw_evidence_text": payload.raw_evidence_text,
            "confidence": payload.confidence,
            "metadata_json": payload.metadata_json,
        },
    ).mappings().one()

    db.execute(
        text(
            """
            update business_update
            set processing_status = 'parsed'
            where id = :business_update_id
              and processing_status in ('pending', 'processing')
            """
        ),
        {"business_update_id": business_update_id},
    )

    db.commit()
    return dict(row)


@router.get("/extracted-actions", response_model=list[ExtractedActionOut])
def list_extracted_actions(
    db: Session = Depends(get_db),
    business_update_id: UUID | None = None,
    review_status: str | None = None,
    target_entity_type: str | None = None,
    target_entity_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if business_update_id:
        where.append("business_update_id = :business_update_id")
        params["business_update_id"] = business_update_id
    if review_status:
        where.append("review_status = :review_status")
        params["review_status"] = review_status
    if target_entity_type:
        where.append("target_entity_type = :target_entity_type")
        params["target_entity_type"] = target_entity_type
    if target_entity_id:
        where.append("target_entity_id = :target_entity_id")
        params["target_entity_id"] = target_entity_id

    rows = db.execute(
        text(
            f"""
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where {' and '.join(where)}
            order by created_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/extracted-actions/{extracted_action_id}", response_model=ExtractedActionOut)
def get_extracted_action(extracted_action_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_extracted_action_or_404(db, extracted_action_id)


@router.patch("/extracted-actions/{extracted_action_id}", response_model=ExtractedActionOut)
def update_extracted_action_review(
    extracted_action_id: UUID,
    payload: ExtractedActionReviewUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_extracted_action_or_404(db, extracted_action_id)

    row = db.execute(
        text(
            """
            update extracted_action
            set review_status = :review_status,
                reviewed_by = :reviewed_by,
                reviewed_at = now()
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            returning
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "review_status": payload.review_status,
            "reviewed_by": DEFAULT_ADMIN_USER_ID,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


def _ensure_business_update_exists(db: Session, business_update_id: UUID) -> None:
    exists = db.execute(
        text(
            """
            select exists(
              select 1
              from business_update
              where id = :business_update_id
                and team_id = :team_id
                and workspace_id = :workspace_id
            )
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one()
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")


def _get_extracted_action_or_404(db: Session, extracted_action_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extracted action not found.")

    return dict(row)

