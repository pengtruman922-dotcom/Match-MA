from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import diff_payload, write_action_log, write_action_logs_for_diff
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/buyer-parties", tags=["buyer-parties"])


class BuyerPartyCreate(BaseModel):
    buyer_name: str = Field(min_length=1, max_length=300)
    legal_name: str | None = None
    aliases_json: list[str] = Field(default_factory=list)
    buyer_type: str | None = None
    group_name: str | None = None
    listed_status: str = "unknown"
    region_province: str | None = None
    region_city: str | None = None
    main_business: str | None = None
    capital_strength_summary: str | None = None
    profile_summary: str | None = None


class BuyerPartyUpdate(BaseModel):
    buyer_name: str | None = Field(default=None, min_length=1, max_length=300)
    legal_name: str | None = None
    aliases_json: list[str] | None = None
    buyer_type: str | None = None
    group_name: str | None = None
    listed_status: str | None = None
    region_province: str | None = None
    region_city: str | None = None
    main_business: str | None = None
    capital_strength_summary: str | None = None
    profile_summary: str | None = None


class BuyerPartyOut(BaseModel):
    id: UUID
    buyer_name: str
    legal_name: str | None
    aliases_json: list[Any]
    buyer_type: str | None
    group_name: str | None
    listed_status: str
    region_province: str | None
    region_city: str | None
    main_business: str | None
    capital_strength_summary: str | None
    profile_summary: str | None
    status: str
    created_at: str
    updated_at: str


@router.post("", response_model=BuyerPartyOut, status_code=status.HTTP_201_CREATED)
def create_buyer_party(payload: BuyerPartyCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    statement = text(
        """
        insert into buyer_party (
          team_id, workspace_id, buyer_name, legal_name, aliases_json,
          buyer_type, group_name, listed_status, region_province, region_city,
          main_business, capital_strength_summary, profile_summary,
          owner_user_id, created_by, updated_by
        )
        values (
          :team_id, :workspace_id, :buyer_name, :legal_name, :aliases_json,
          :buyer_type, :group_name, :listed_status, :region_province, :region_city,
          :main_business, :capital_strength_summary, :profile_summary,
          :owner_user_id, :created_by, :updated_by
        )
        returning
          id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
          listed_status, region_province, region_city, main_business,
          capital_strength_summary, profile_summary, status,
          created_at::text as created_at, updated_at::text as updated_at
        """
    ).bindparams(bindparam("aliases_json", type_=JSONB))
    row = db.execute(statement, _buyer_party_params(payload)).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=list[BuyerPartyOut])
def list_buyer_parties(
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
        where.append("(buyer_name ilike :q or legal_name ilike :q or main_business ilike :q)")
        params["q"] = f"%{q}%"

    rows = db.execute(
        text(
            f"""
            select
              id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
              listed_status, region_province, region_city, main_business,
              capital_strength_summary, profile_summary, status,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_party
            where {' and '.join(where)}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.get("/{buyer_party_id}", response_model=BuyerPartyOut)
def get_buyer_party(buyer_party_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_buyer_party_or_404(db, buyer_party_id)


@router.get("/{buyer_party_id}/intents")
def list_buyer_party_intents(
    buyer_party_id: UUID,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    _get_buyer_party_or_404(db, buyer_party_id)
    rows = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary, industry_secondary,
              region_scope_summary, min_revenue_yuan, min_net_profit_yuan, max_pe,
              max_valuation_yuan, min_market_cap_yuan, max_market_cap_yuan,
              market_cap_range_summary, requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status,
              listing_board_requirement_summary, financing_stage_requirement_summary,
              transaction_type, transaction_types_json, premium_tolerance_summary,
              max_premium_rate, max_debt_ratio, debt_ratio_requirement_summary,
              major_risk_tolerance_summary, buyer_industry_advantage_summary,
              negative_summary, preference_summary, unknown_summary,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_intent
            where buyer_party_id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "limit": limit,
            "offset": offset,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


@router.patch("/{buyer_party_id}", response_model=BuyerPartyOut)
def update_buyer_party(
    buyer_party_id: UUID,
    payload: BuyerPartyUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_buyer_party_or_404(db, buyer_party_id)
    changes = payload.model_dump(exclude_unset=True)

    if "buyer_name" in changes and changes["buyer_name"] is not None:
        changes["buyer_name"] = changes["buyer_name"].strip()

    if not changes:
        return original

    diff = diff_payload(original, changes)
    if not diff:
        return original

    set_clauses = [f"{field} = :{field}" for field in changes]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    statement = text(
        f"""
        update buyer_party
        set {', '.join(set_clauses)}
        where id = :buyer_party_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        returning
          id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
          listed_status, region_province, region_city, main_business,
          capital_strength_summary, profile_summary, status,
          created_at::text as created_at, updated_at::text as updated_at
        """
    )
    if "aliases_json" in changes:
        statement = statement.bindparams(bindparam("aliases_json", type_=JSONB))

    row = db.execute(
        statement,
        {
            **changes,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    write_action_logs_for_diff(
        db,
        entity_type="buyer_party",
        entity_id=buyer_party_id,
        diff=diff,
    )
    db.commit()
    return dict(row)


@router.delete("/{buyer_party_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_party(buyer_party_id: UUID, db: Session = Depends(get_db)) -> None:
    _get_buyer_party_or_404(db, buyer_party_id)
    db.execute(
        text(
            """
            update buyer_party
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    write_action_log(
        db,
        entity_type="buyer_party",
        entity_id=buyer_party_id,
        field_path="deleted_at",
        old_value=None,
        new_value="now()",
    )
    db.commit()
    return None


def _buyer_party_params(payload: BuyerPartyCreate) -> dict[str, Any]:
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "buyer_name": payload.buyer_name.strip(),
        "legal_name": payload.legal_name,
        "aliases_json": payload.aliases_json,
        "buyer_type": payload.buyer_type,
        "group_name": payload.group_name,
        "listed_status": payload.listed_status,
        "region_province": payload.region_province,
        "region_city": payload.region_city,
        "main_business": payload.main_business,
        "capital_strength_summary": payload.capital_strength_summary,
        "profile_summary": payload.profile_summary,
        "owner_user_id": DEFAULT_ADMIN_USER_ID,
        "created_by": DEFAULT_ADMIN_USER_ID,
        "updated_by": DEFAULT_ADMIN_USER_ID,
    }


def _get_buyer_party_or_404(db: Session, buyer_party_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
              listed_status, region_province, region_city, main_business,
              capital_strength_summary, profile_summary, status,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_party
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer party not found.")

    return dict(row)
