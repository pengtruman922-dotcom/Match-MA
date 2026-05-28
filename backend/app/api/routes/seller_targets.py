from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.utils import diff_payload, write_action_log
from backend.app.db import get_db

router = APIRouter(prefix="/seller-targets", tags=["seller-targets"])


class SellerTargetCreate(BaseModel):
    target_name: str = Field(min_length=1, max_length=300)
    target_type: str = "company"
    owner_user_id: UUID | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
    listed_status: str = "unknown"
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    valuation_yuan: Decimal | None = None
    asking_price_yuan: Decimal | None = None
    pe_ratio: Decimal | None = None
    is_for_sale: str = "unknown"
    can_control: str = "unknown"
    can_consolidate: str = "unknown"
    business_summary: str | None = None
    transaction_summary: str | None = None
    risk_summary: str | None = None


class SellerTargetOut(BaseModel):
    id: UUID
    target_name: str
    target_type: str
    recommendation_status: str
    information_status: str
    industry_primary: str | None
    industry_secondary: str | None
    headquarter_province: str | None
    headquarter_city: str | None
    listed_status: str
    current_revenue_yuan: Decimal | None
    current_net_profit_yuan: Decimal | None
    valuation_yuan: Decimal | None
    asking_price_yuan: Decimal | None
    pe_ratio: Decimal | None
    is_for_sale: str
    can_control: str
    can_consolidate: str
    business_summary: str | None
    transaction_summary: str | None
    risk_summary: str | None
    created_at: str
    updated_at: str


class SellerTargetUpdate(BaseModel):
    target_name: str | None = Field(default=None, min_length=1, max_length=300)
    industry_primary: str | None = None
    industry_secondary: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
    listed_status: str | None = None
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    valuation_yuan: Decimal | None = None
    asking_price_yuan: Decimal | None = None
    pe_ratio: Decimal | None = None
    is_for_sale: str | None = None
    can_control: str | None = None
    can_consolidate: str | None = None
    recommendation_status: str | None = None
    information_status: str | None = None
    business_summary: str | None = None
    transaction_summary: str | None = None
    risk_summary: str | None = None


@router.post("", response_model=SellerTargetOut, status_code=status.HTTP_201_CREATED)
def create_seller_target(payload: SellerTargetCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            insert into seller_target (
              team_id, workspace_id, target_name, target_type, owner_user_id,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :target_name, :target_type, :owner_user_id,
              :industry_primary, :industry_secondary, :headquarter_province, :headquarter_city,
              :listed_status, :current_revenue_yuan, :current_net_profit_yuan,
              :valuation_yuan, :asking_price_yuan, :pe_ratio,
              :is_for_sale, :can_control, :can_consolidate,
              :business_summary, :transaction_summary, :risk_summary,
              :created_by, :updated_by
            )
            returning
              id, target_name, target_type, recommendation_status, information_status,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        _seller_target_params(payload),
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=list[SellerTargetOut])
def list_seller_targets(
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
        where.append("(target_name ilike :q or business_summary ilike :q)")
        params["q"] = f"%{q}%"

    rows = db.execute(
        text(
            f"""
            select
              id, target_name, target_type, recommendation_status, information_status,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_at::text as created_at, updated_at::text as updated_at
            from seller_target
            where {' and '.join(where)}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{seller_target_id}", response_model=SellerTargetOut)
def get_seller_target(seller_target_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_seller_target_or_404(db, seller_target_id)


@router.patch("/{seller_target_id}", response_model=SellerTargetOut)
def update_seller_target(
    seller_target_id: UUID,
    payload: SellerTargetUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_seller_target_or_404(db, seller_target_id)
    changes = payload.model_dump(exclude_unset=True)

    if "target_name" in changes and changes["target_name"] is not None:
        changes["target_name"] = changes["target_name"].strip()

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
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning
              id, target_name, target_type, recommendation_status, information_status,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        {
            **changes,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    for field_path, (old_value, new_value) in diff.items():
        write_action_log(
            db,
            entity_type="seller_target",
            entity_id=seller_target_id,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
        )

    db.commit()
    return dict(row)


@router.delete("/{seller_target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_seller_target(seller_target_id: UUID, db: Session = Depends(get_db)) -> None:
    _get_seller_target_or_404(db, seller_target_id)
    db.execute(
        text(
            """
            update seller_target
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    write_action_log(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        field_path="deleted_at",
        old_value=None,
        new_value="now()",
    )
    db.commit()
    return None


def _get_seller_target_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, target_type, recommendation_status, information_status,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, asking_price_yuan, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_at::text as created_at, updated_at::text as updated_at
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


def _seller_target_params(payload: SellerTargetCreate) -> dict[str, Any]:
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "target_name": payload.target_name.strip(),
        "target_type": payload.target_type,
        "owner_user_id": payload.owner_user_id or DEFAULT_ADMIN_USER_ID,
        "industry_primary": payload.industry_primary,
        "industry_secondary": payload.industry_secondary,
        "headquarter_province": payload.headquarter_province,
        "headquarter_city": payload.headquarter_city,
        "listed_status": payload.listed_status,
        "current_revenue_yuan": payload.current_revenue_yuan,
        "current_net_profit_yuan": payload.current_net_profit_yuan,
        "valuation_yuan": payload.valuation_yuan,
        "asking_price_yuan": payload.asking_price_yuan,
        "pe_ratio": payload.pe_ratio,
        "is_for_sale": payload.is_for_sale,
        "can_control": payload.can_control,
        "can_consolidate": payload.can_consolidate,
        "business_summary": payload.business_summary,
        "transaction_summary": payload.transaction_summary,
        "risk_summary": payload.risk_summary,
        "created_by": DEFAULT_ADMIN_USER_ID,
        "updated_by": DEFAULT_ADMIN_USER_ID,
    }
