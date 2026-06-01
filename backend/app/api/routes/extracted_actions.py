from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.utils import diff_payload, write_action_logs_for_diff
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


class ApplyActionOut(BaseModel):
    status: str
    extracted_action_id: UUID
    business_update_id: UUID
    entity_type: str
    entity_id: UUID
    applied_fields: list[str]


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


@router.post("/extracted-actions/{extracted_action_id}/apply", response_model=ApplyActionOut)
def apply_extracted_action(extracted_action_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    action = _get_extracted_action_or_404(db, extracted_action_id)
    result = apply_seller_fact_update_action(db, action, require_accepted=True)
    db.commit()
    return result


def apply_seller_fact_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
) -> dict[str, Any]:
    if action["action_type"] != "seller_fact_update" or action["target_entity_type"] != "seller_target":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only seller_fact_update actions targeting seller_target are supported now.",
        )
    if action["target_entity_id"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_entity_id is required.")
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = _allowed_seller_target_changes(action["proposed_changes_json"])
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported changes to apply.")

    seller_target_id = action["target_entity_id"]
    original = _get_seller_target_snapshot_or_404(db, seller_target_id)
    diff = diff_payload(original, changes)
    if not diff:
        _mark_action_applied(db, action["id"], review_status="auto_accepted")
        _refresh_business_update_status(db, action["business_update_id"])
        return {
            "status": "noop",
            "extracted_action_id": action["id"],
            "business_update_id": action["business_update_id"],
            "entity_type": "seller_target",
            "entity_id": seller_target_id,
            "applied_fields": [],
        }

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    db.execute(
        text(
            f"""
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            **{field: changes[field] for field in diff},
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        diff=diff,
        source_type="extracted_action",
        business_update_id=action["business_update_id"],
        extracted_action_id=action["id"],
    )
    _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "seller_target",
        "entity_id": seller_target_id,
        "applied_fields": list(diff.keys()),
    }


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


def _get_seller_target_snapshot_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              target_name, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, listed_status,
              current_revenue_yuan, current_net_profit_yuan, valuation_yuan,
              asking_price_yuan, pe_ratio, is_for_sale, can_control, can_consolidate,
              recommendation_status, information_status,
              business_summary, transaction_summary, risk_summary
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


def _allowed_seller_target_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "target_name",
        "industry_primary",
        "industry_secondary",
        "headquarter_province",
        "headquarter_city",
        "listed_status",
        "current_revenue_yuan",
        "current_net_profit_yuan",
        "valuation_yuan",
        "asking_price_yuan",
        "pe_ratio",
        "is_for_sale",
        "can_control",
        "can_consolidate",
        "recommendation_status",
        "information_status",
        "business_summary",
        "transaction_summary",
        "risk_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _mark_action_applied(
    db: Session,
    extracted_action_id: UUID,
    *,
    review_status: str | None = None,
) -> None:
    review_status_clause = ""
    if review_status:
        review_status_clause = ", review_status = :review_status, reviewed_by = :reviewed_by, reviewed_at = now()"
    db.execute(
        text(
            f"""
            update extracted_action
            set applied_at = now(){review_status_clause}
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "review_status": review_status,
            "reviewed_by": DEFAULT_ADMIN_USER_ID,
        },
    )


def _refresh_business_update_status(db: Session, business_update_id: UUID) -> None:
    pending_count = db.execute(
        text(
            """
            select count(*)
            from extracted_action
            where business_update_id = :business_update_id
              and applied_at is null
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {"business_update_id": business_update_id},
    ).scalar_one()
    new_status = "applied" if int(pending_count) == 0 else "partially_applied"
    db.execute(
        text(
            """
            update business_update
            set processing_status = :processing_status
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "processing_status": new_status,
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
