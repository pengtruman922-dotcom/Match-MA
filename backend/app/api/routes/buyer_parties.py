from typing import Any, Literal
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


class BuyerPartyListOut(BaseModel):
    items: list[BuyerPartyOut]
    total: int
    limit: int
    offset: int


class BuyerPartyFilterOptionOut(BaseModel):
    value: str
    label: str
    count: int


class BuyerPartyFilterOptionsOut(BaseModel):
    buyer_types: list[BuyerPartyFilterOptionOut]
    regions: list[BuyerPartyFilterOptionOut]
    listed_statuses: list[BuyerPartyFilterOptionOut]
    statuses: list[BuyerPartyFilterOptionOut]


class BuyerPartySuggestionOut(BaseModel):
    id: UUID
    search_field: Literal["buyer_name", "legal_name", "main_business", "profile_summary"]
    match_type: Literal["buyer", "legal", "business", "profile"]
    match_label: str
    match_text: str
    buyer_name: str
    legal_name: str | None
    snippet: str | None


class BuyerPartyBulkDeleteRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class BuyerPartyBulkDeleteOut(BaseModel):
    status: str
    deleted_count: int
    deleted_ids: list[UUID]
    skipped_ids: list[UUID]


BUYER_PARTY_OUT_COLUMNS = """
          id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
          listed_status, region_province, region_city, main_business,
          capital_strength_summary, profile_summary, status,
          created_at::text as created_at, updated_at::text as updated_at
"""


BUYER_PARTY_SEARCH_COLUMNS = {
    "buyer_name": "buyer_name",
    "legal_name": "legal_name",
    "main_business": "main_business",
    "profile_summary": "profile_summary",
}


@router.post("", response_model=BuyerPartyOut, status_code=status.HTTP_201_CREATED)
def create_buyer_party(payload: BuyerPartyCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    statement = text(
        f"""
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
{BUYER_PARTY_OUT_COLUMNS}
        """
    ).bindparams(bindparam("aliases_json", type_=JSONB))
    row = db.execute(statement, _buyer_party_params(payload)).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=BuyerPartyListOut)
def list_buyer_parties(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    search_field: Literal["buyer_name", "legal_name", "main_business", "profile_summary"] | None = Query(default=None),
    buyer_type: str | None = Query(default=None, max_length=80),
    region: str | None = Query(default=None, max_length=200),
    listed_status: str | None = Query(default=None, max_length=80),
    status: Literal["active", "archived", "merged"] | None = Query(default=None),
) -> dict[str, Any]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    if q:
        if search_field:
            where.append(f"{BUYER_PARTY_SEARCH_COLUMNS[search_field]} ilike :q")
        else:
            where.append(
                "("
                "buyer_name ilike :q or legal_name ilike :q or aliases_json::text ilike :q "
                "or main_business ilike :q or profile_summary ilike :q"
                ")"
            )
        params["q"] = f"%{q}%"
    if buyer_type:
        where.append("buyer_type = :buyer_type")
        params["buyer_type"] = buyer_type
    if region:
        where.append("concat_ws(' ', nullif(region_province, ''), nullif(region_city, '')) = :region")
        params["region"] = region
    if listed_status:
        where.append("listed_status = :listed_status")
        params["listed_status"] = listed_status
    if status:
        where.append("status = :status")
        params["status"] = status

    where_sql = " and ".join(where)
    total = db.execute(
        text(
            f"""
            select count(*)
            from buyer_party
            where {where_sql}
            """
        ),
        params,
    ).scalar_one()

    rows = db.execute(
        text(
            f"""
            select
{BUYER_PARTY_OUT_COLUMNS}
            from buyer_party
            where {where_sql}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options", response_model=BuyerPartyFilterOptionsOut)
def buyer_party_filter_options(db: Session = Depends(get_db)) -> dict[str, Any]:
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    buyer_types = _filter_options(
        db,
        """
        select buyer_type as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          and nullif(buyer_type, '') is not null
        group by buyer_type
        order by count desc, buyer_type asc
        """,
        params,
        labels={
            "industrial_buyer": "产业买家",
            "listed_company": "上市公司",
            "state_owned_platform": "国资平台",
            "pe_fund": "PE基金",
            "financial_investor": "财务投资人",
            "government_platform": "政府平台",
            "other": "其他",
        },
    )
    regions = _filter_options(
        db,
        """
        select
          concat_ws(' ', nullif(region_province, ''), nullif(region_city, '')) as value,
          count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          and concat_ws(' ', nullif(region_province, ''), nullif(region_city, '')) <> ''
        group by value
        order by count desc, value asc
        limit 80
        """,
        params,
    )
    listed_statuses = _filter_options(
        db,
        """
        select listed_status as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        group by listed_status
        order by count desc, listed_status asc
        """,
        params,
        labels={"listed": "已上市", "unlisted": "未上市", "pre_ipo": "拟上市", "unknown": "未知"},
    )
    statuses = _filter_options(
        db,
        """
        select status as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        group by status
        order by count desc, status asc
        """,
        params,
        labels={"active": "活跃", "archived": "已归档", "merged": "已合并"},
    )
    return {
        "buyer_types": buyer_types,
        "regions": regions,
        "listed_statuses": listed_statuses,
        "statuses": statuses,
    }


@router.get("/suggestions", response_model=list[BuyerPartySuggestionOut])
def buyer_party_suggestions(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = q.strip()
    if not query:
        return []

    rows = db.execute(
        text(
            """
            with matches as (
              select
                id, buyer_name, legal_name, main_business, profile_summary, updated_at,
                'buyer_name'::text as search_field,
                'buyer'::text as match_type,
                buyer_name as match_text,
                1 as priority
              from buyer_party
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                and buyer_name ilike :q
              union all
              select
                id, buyer_name, legal_name, main_business, profile_summary, updated_at,
                'legal_name'::text as search_field,
                'legal'::text as match_type,
                legal_name as match_text,
                2 as priority
              from buyer_party
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                and legal_name ilike :q
              union all
              select
                id, buyer_name, legal_name, main_business, profile_summary, updated_at,
                'main_business'::text as search_field,
                'business'::text as match_type,
                main_business as match_text,
                3 as priority
              from buyer_party
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                and main_business ilike :q
              union all
              select
                id, buyer_name, legal_name, main_business, profile_summary, updated_at,
                'profile_summary'::text as search_field,
                'profile'::text as match_type,
                profile_summary as match_text,
                4 as priority
              from buyer_party
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                and profile_summary ilike :q
            )
            select distinct on (id)
              id, buyer_name, legal_name, main_business, profile_summary,
              search_field, match_type, match_text
            from matches
            order by id, priority, updated_at desc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "q": f"%{query}%",
        },
    ).mappings().all()
    sorted_rows = sorted(
        rows,
        key=lambda row: ({"buyer": 1, "legal": 2, "business": 3, "profile": 4}[row["match_type"]], row["buyer_name"]),
    )
    labels = {"buyer": "买家", "legal": "法律主体", "business": "主营业务", "profile": "画像"}
    return [
        {
            "id": row["id"],
            "search_field": row["search_field"],
            "match_type": row["match_type"],
            "match_label": labels[row["match_type"]],
            "match_text": row["match_text"],
            "buyer_name": row["buyer_name"],
            "legal_name": row["legal_name"],
            "snippet": _truncate_text(row["profile_summary"] or row["main_business"], 80),
        }
        for row in sorted_rows[:limit]
        if row["match_text"]
    ]


@router.post("/bulk-delete", response_model=BuyerPartyBulkDeleteOut)
def bulk_delete_buyer_parties(
    payload: BuyerPartyBulkDeleteRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    party_ids = list(dict.fromkeys(payload.ids))
    deleted_ids = _soft_delete_buyer_parties(db, party_ids)
    deleted_id_set = set(deleted_ids)
    skipped_ids = [party_id for party_id in party_ids if party_id not in deleted_id_set]
    db.commit()
    return {
        "status": "ok",
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped_ids": skipped_ids,
    }


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
{BUYER_PARTY_OUT_COLUMNS}
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
    _soft_delete_buyer_parties(db, [buyer_party_id])
    db.commit()
    return None


def _filter_options(
    db: Session,
    query: str,
    params: dict[str, Any],
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = db.execute(text(query), params).mappings().all()
    label_map = labels or {}
    return [
        {"value": row["value"], "label": label_map.get(row["value"], row["value"]), "count": int(row["count"])}
        for row in rows
        if row["value"]
    ]


def _soft_delete_buyer_parties(db: Session, buyer_party_ids: list[UUID]) -> list[UUID]:
    if not buyer_party_ids:
        return []

    rows = db.execute(
        text(
            """
            update buyer_party
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id in :buyer_party_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning id
            """
        ).bindparams(bindparam("buyer_party_ids", expanding=True)),
        {
            "deleted_by": DEFAULT_ADMIN_USER_ID,
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "buyer_party_ids": buyer_party_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    deleted_ids = [row["id"] for row in rows]
    for deleted_id in deleted_ids:
        write_action_log(
            db,
            entity_type="buyer_party",
            entity_id=deleted_id,
            field_path="deleted_at",
            old_value=None,
            new_value="now()",
        )
    return deleted_ids


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
            f"""
            select
{BUYER_PARTY_OUT_COLUMNS}
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
