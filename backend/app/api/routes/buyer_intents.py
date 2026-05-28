from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.utils import diff_payload, write_action_log, write_action_logs_for_diff
from backend.app.db import get_db

router = APIRouter(prefix="/buyer-intents", tags=["buyer-intents"])


class BuyerIntentCreate(BaseModel):
    intent_name: str = Field(min_length=1, max_length=300)
    buyer_party_id: UUID | None = None
    owner_user_id: UUID | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    region_scope_summary: str | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    requires_control: str = "unknown"
    requires_consolidation: str = "unknown"
    accepts_minority_investment: str = "unknown"
    preferred_listed_status: str | None = "unknown"
    transaction_type: str | None = None
    negative_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None


class BuyerIntentOut(BaseModel):
    id: UUID
    buyer_party_id: UUID | None
    intent_name: str
    status: str
    contact_name: str | None
    raw_requirement_text: str | None
    intent_summary: str | None
    industry_primary: str | None
    industry_secondary: str | None
    region_scope_summary: str | None
    min_revenue_yuan: Decimal | None
    min_net_profit_yuan: Decimal | None
    max_pe: Decimal | None
    max_valuation_yuan: Decimal | None
    requires_control: str
    requires_consolidation: str
    accepts_minority_investment: str
    preferred_listed_status: str | None
    transaction_type: str | None
    negative_summary: str | None
    preference_summary: str | None
    unknown_summary: str | None
    created_at: str
    updated_at: str


class BuyerIntentUpdate(BaseModel):
    intent_name: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = None
    pause_reason: str | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    region_scope_summary: str | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    requires_control: str | None = None
    requires_consolidation: str | None = None
    accepts_minority_investment: str | None = None
    preferred_listed_status: str | None = None
    transaction_type: str | None = None
    negative_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None


@router.post("", response_model=BuyerIntentOut, status_code=status.HTTP_201_CREATED)
def create_buyer_intent(payload: BuyerIntentCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            insert into buyer_intent (
              team_id, workspace_id, buyer_party_id, owner_user_id,
              intent_name, contact_name, raw_requirement_text, intent_summary,
              industry_primary, industry_secondary, region_scope_summary,
              min_revenue_yuan, min_net_profit_yuan, max_pe, max_valuation_yuan,
              requires_control, requires_consolidation, accepts_minority_investment,
              preferred_listed_status, transaction_type,
              negative_summary, preference_summary, unknown_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :buyer_party_id, :owner_user_id,
              :intent_name, :contact_name, :raw_requirement_text, :intent_summary,
              :industry_primary, :industry_secondary, :region_scope_summary,
              :min_revenue_yuan, :min_net_profit_yuan, :max_pe, :max_valuation_yuan,
              :requires_control, :requires_consolidation, :accepts_minority_investment,
              :preferred_listed_status, :transaction_type,
              :negative_summary, :preference_summary, :unknown_summary,
              :created_by, :updated_by
            )
            returning
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary, industry_secondary,
              region_scope_summary, min_revenue_yuan, min_net_profit_yuan, max_pe,
              max_valuation_yuan, requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status, transaction_type,
              negative_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        _buyer_intent_params(payload),
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=list[BuyerIntentOut])
def list_buyer_intents(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if q:
        where.append("(intent_name ilike :q or raw_requirement_text ilike :q)")
        params["q"] = f"%{q}%"

    rows = db.execute(
        text(
            f"""
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary, industry_secondary,
              region_scope_summary, min_revenue_yuan, min_net_profit_yuan, max_pe,
              max_valuation_yuan, requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status, transaction_type,
              negative_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_intent
            where {' and '.join(where)}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{buyer_intent_id}", response_model=BuyerIntentOut)
def get_buyer_intent(buyer_intent_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_buyer_intent_or_404(db, buyer_intent_id)


@router.patch("/{buyer_intent_id}", response_model=BuyerIntentOut)
def update_buyer_intent(
    buyer_intent_id: UUID,
    payload: BuyerIntentUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_buyer_intent_or_404(db, buyer_intent_id)
    changes = payload.model_dump(exclude_unset=True)

    if "intent_name" in changes and changes["intent_name"] is not None:
        changes["intent_name"] = changes["intent_name"].strip()

    if not changes:
        return original

    diff = diff_payload(original, changes)
    if not diff:
        return original

    set_clauses = [f"{field} = :{field}" for field in changes]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    row = db.execute(
        text(
            f"""
            update buyer_intent
            set {', '.join(set_clauses)}
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary, industry_secondary,
              region_scope_summary, min_revenue_yuan, min_net_profit_yuan, max_pe,
              max_valuation_yuan, requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status, transaction_type,
              negative_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        {
            **changes,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    write_action_logs_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        diff=diff,
    )

    db.commit()
    return dict(row)


@router.delete("/{buyer_intent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_intent(buyer_intent_id: UUID, db: Session = Depends(get_db)) -> None:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    db.execute(
        text(
            """
            update buyer_intent
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    write_action_log(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        field_path="deleted_at",
        old_value=None,
        new_value="now()",
    )
    db.commit()
    return None


def _get_buyer_intent_or_404(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary, industry_secondary,
              region_scope_summary, min_revenue_yuan, min_net_profit_yuan, max_pe,
              max_valuation_yuan, requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status, transaction_type,
              negative_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
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

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")

    return dict(row)


def _buyer_intent_params(payload: BuyerIntentCreate) -> dict[str, Any]:
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "buyer_party_id": payload.buyer_party_id,
        "owner_user_id": payload.owner_user_id or DEFAULT_ADMIN_USER_ID,
        "intent_name": payload.intent_name.strip(),
        "contact_name": payload.contact_name,
        "raw_requirement_text": payload.raw_requirement_text,
        "intent_summary": payload.intent_summary,
        "industry_primary": payload.industry_primary,
        "industry_secondary": payload.industry_secondary,
        "region_scope_summary": payload.region_scope_summary,
        "min_revenue_yuan": payload.min_revenue_yuan,
        "min_net_profit_yuan": payload.min_net_profit_yuan,
        "max_pe": payload.max_pe,
        "max_valuation_yuan": payload.max_valuation_yuan,
        "requires_control": payload.requires_control,
        "requires_consolidation": payload.requires_consolidation,
        "accepts_minority_investment": payload.accepts_minority_investment,
        "preferred_listed_status": payload.preferred_listed_status,
        "transaction_type": payload.transaction_type,
        "negative_summary": payload.negative_summary,
        "preference_summary": payload.preference_summary,
        "unknown_summary": payload.unknown_summary,
        "created_by": DEFAULT_ADMIN_USER_ID,
        "updated_by": DEFAULT_ADMIN_USER_ID,
    }
