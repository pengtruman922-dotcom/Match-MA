from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import AuthContext, CurrentUser, require_admin
from backend.app.api.routes.utils import (
    append_owner_scope,
    append_visible_scope,
    assign_owner_bulk,
    diff_payload,
    ensure_entity_visible,
    ensure_entity_writable,
    ensure_active_user,
    owner_scope_required,
    owner_filter_condition,
    owner_filter_options,
    owner_scope_sql,
    write_action_log,
    write_action_logs_for_diff,
)
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/buyer-parties", tags=["buyer-parties"])


class BuyerPartyCreate(BaseModel):
    buyer_name: str = Field(min_length=1, max_length=300)
    owner_user_id: UUID | None = None
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
    notes: str | None = None


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
    notes: str | None = None
    owner_user_id: UUID | None = None


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
    notes: str | None = None
    status: str
    owner_user_id: UUID | None = None
    owner_name: str | None = None
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
    owners: list[BuyerPartyFilterOptionOut] = []


class BuyerPartySuggestionOut(BaseModel):
    id: UUID
    search_field: Literal["buyer_name", "legal_name", "main_business", "profile_summary"]
    match_type: Literal["buyer", "legal", "business", "profile"]
    match_label: str
    match_text: str
    buyer_name: str
    legal_name: str | None
    snippet: str | None


class BuyerPartyDedupMatchOut(BaseModel):
    id: UUID
    buyer_name: str
    legal_name: str | None = None
    owner_name: str | None = None
    match_type: Literal["buyer_name", "legal_name", "alias"]
    status: str


class BuyerPartyDedupCheckOut(BaseModel):
    exists: bool
    query: str
    matches: list[BuyerPartyDedupMatchOut]


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
          capital_strength_summary, profile_summary, notes, status,
          owner_user_id,
          (select au.name from app_user au where au.id = buyer_party.owner_user_id) as owner_name,
          created_at::text as created_at, updated_at::text as updated_at
"""


BUYER_PARTY_SEARCH_COLUMNS = {
    "buyer_name": "buyer_name",
    "legal_name": "legal_name",
    "main_business": "main_business",
    "profile_summary": "profile_summary",
}


@router.post("", response_model=BuyerPartyOut, status_code=status.HTTP_201_CREATED)
def create_buyer_party(
    payload: BuyerPartyCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = text(
        f"""
        insert into buyer_party (
          team_id, workspace_id, buyer_name, legal_name, aliases_json,
          buyer_type, group_name, listed_status, region_province, region_city,
          main_business, capital_strength_summary, profile_summary, notes,
          owner_user_id, created_by, updated_by
        )
        values (
          :team_id, :workspace_id, :buyer_name, :legal_name, :aliases_json,
          :buyer_type, :group_name, :listed_status, :region_province, :region_city,
          :main_business, :capital_strength_summary, :profile_summary, :notes,
          :owner_user_id, :created_by, :updated_by
        )
        returning
{BUYER_PARTY_OUT_COLUMNS}
        """
    ).bindparams(bindparam("aliases_json", type_=JSONB))
    row = db.execute(statement, _buyer_party_params(payload, current_user)).mappings().one()
    db.commit()
    return dict(row)


@router.get("", response_model=BuyerPartyListOut)
def list_buyer_parties(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    search_field: Literal["buyer_name", "legal_name", "main_business", "profile_summary"] | None = Query(default=None),
    buyer_type: str | None = Query(default=None, max_length=80),
    region: str | None = Query(default=None, max_length=200),
    listed_status: str | None = Query(default=None, max_length=80),
    status: Literal["active", "archived", "merged"] | None = Query(default=None),
    owner: str | None = Query(default=None, max_length=50),
) -> dict[str, Any]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    append_owner_scope(where, params, current_user, entity_type="buyer_party", alias="buyer_party")

    owner_condition = owner_filter_condition(owner)
    if owner_condition:
        condition_sql, owner_param = owner_condition
        where.append(condition_sql)
        if owner_param is not None:
            params["owner_user_id"] = owner_param

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
def buyer_party_filter_options(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    scope_clause = ""
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        scope_clause = f"and {owner_scope_sql('buyer_party', 'buyer_party')}"
    buyer_types = _filter_options(
        db,
        f"""
        select buyer_type as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
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
        f"""
        select
          concat_ws(' ', nullif(region_province, ''), nullif(region_city, '')) as value,
          count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
          and concat_ws(' ', nullif(region_province, ''), nullif(region_city, '')) <> ''
        group by value
        order by count desc, value asc
        limit 80
        """,
        params,
    )
    listed_statuses = _filter_options(
        db,
        f"""
        select listed_status as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by listed_status
        order by count desc, listed_status asc
        """,
        params,
        labels={"listed": "已上市", "unlisted": "未上市", "pre_ipo": "拟上市", "unknown": "未知"},
    )
    statuses = _filter_options(
        db,
        f"""
        select status as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by status
        order by count desc, status asc
        """,
        params,
        labels={"active": "活跃", "archived": "已归档", "merged": "已合并"},
    )
    owners = [] if owner_scope_required(current_user) else owner_filter_options(db, "buyer_party", params)
    return {
        "buyer_types": buyer_types,
        "regions": regions,
        "listed_statuses": listed_statuses,
        "statuses": statuses,
        "owners": owners,
    }


@router.get("/dedup-check", response_model=BuyerPartyDedupCheckOut)
def buyer_party_dedup_check(
    current_user: CurrentUser,
    q: str = Query(min_length=1, max_length=100),
    limit: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"exists": False, "query": "", "matches": []}

    escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    limit_sql = "limit :limit" if limit is not None else ""
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "q": query,
        "name_pattern": f"%{escaped_query}%",
    }
    if limit is not None:
        params["limit"] = limit

    rows = db.execute(
        text(
            rf"""
            with candidate as (
              select
                bp.id,
                bp.buyer_name,
                bp.legal_name,
                coalesce(au.name, '未指派') as owner_name,
                bp.status,
                case
                  when lower(bp.buyer_name) = lower(:q) then 'buyer_name'
                  when lower(coalesce(bp.legal_name, '')) = lower(:q) then 'legal_name'
                  when exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where lower(alias_name) = lower(:q)
                  ) then 'alias'
                  when bp.buyer_name ilike :name_pattern escape '\' then 'buyer_name'
                  when coalesce(bp.legal_name, '') ilike :name_pattern escape '\' then 'legal_name'
                  else 'alias'
                end as match_type,
                case
                  when lower(bp.buyer_name) = lower(:q) then 1
                  when lower(coalesce(bp.legal_name, '')) = lower(:q) then 2
                  when exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where lower(alias_name) = lower(:q)
                  ) then 3
                  when bp.buyer_name ilike :name_pattern escape '\' then 4
                  when coalesce(bp.legal_name, '') ilike :name_pattern escape '\' then 5
                  else 6
                end as priority,
                bp.updated_at
              from buyer_party bp
              left join app_user au on au.id = bp.owner_user_id
              where bp.team_id = :team_id
                and bp.workspace_id = :workspace_id
                and bp.deleted_at is null
                and (
                  bp.buyer_name ilike :name_pattern escape '\'
                  or coalesce(bp.legal_name, '') ilike :name_pattern escape '\'
                  or exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where alias_name ilike :name_pattern escape '\'
                  )
                )
            )
            select id, buyer_name, legal_name, owner_name, match_type, status
            from candidate
            order by priority asc, updated_at desc, buyer_name asc
            {limit_sql}
            """
        ),
        params,
    ).mappings().all()
    matches = [dict(row) for row in rows]
    return {"exists": bool(matches), "query": query, "matches": matches}


@router.get("/suggestions", response_model=list[BuyerPartySuggestionOut])
def buyer_party_suggestions(
    current_user: CurrentUser,
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = q.strip()
    if not query:
        return []

    params = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "q": f"%{query}%",
    }
    scope_clause = ""
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        scope_clause = f"and {owner_scope_sql('buyer_party', 'buyer_party')}"

    rows = db.execute(
        text(
            f"""
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
                {scope_clause}
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
                {scope_clause}
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
                {scope_clause}
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
                {scope_clause}
                and profile_summary ilike :q
            )
            select distinct on (id)
              id, buyer_name, legal_name, main_business, profile_summary,
              search_field, match_type, match_text
            from matches
            order by id, priority, updated_at desc
            """
        ),
        params,
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


class BuyerPartyBatchAssignOwnerRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)
    owner_user_id: UUID | None = None


class BuyerPartyBatchAssignOwnerOut(BaseModel):
    status: str
    updated_count: int
    updated_ids: list[UUID]


@router.post("/batch-assign-owner", response_model=BuyerPartyBatchAssignOwnerOut)
def batch_assign_buyer_party_owner(
    payload: BuyerPartyBatchAssignOwnerRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    if payload.owner_user_id is not None:
        ensure_active_user(db, payload.owner_user_id)
    updated_ids = assign_owner_bulk(
        db,
        table="buyer_party",
        entity_type="buyer_party",
        entity_ids=list(dict.fromkeys(payload.ids)),
        new_owner_user_id=payload.owner_user_id,
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return {"status": "ok", "updated_count": len(updated_ids), "updated_ids": updated_ids}


@router.post("/bulk-delete", response_model=BuyerPartyBulkDeleteOut)
def bulk_delete_buyer_parties(
    payload: BuyerPartyBulkDeleteRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    party_ids = list(dict.fromkeys(payload.ids))
    deleted_ids = _soft_delete_buyer_parties(
        db,
        party_ids,
        actor_user_id=current_user.user_id,
        owner_user_id=None if current_user.is_admin else current_user.user_id,
    )
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
def get_buyer_party(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    party = _get_buyer_party_or_404(db, buyer_party_id)
    ensure_entity_visible(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    return party


@router.get("/{buyer_party_id}/intents")
def list_buyer_party_intents(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    _get_buyer_party_or_404(db, buyer_party_id)
    ensure_entity_visible(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    where = [
        "bi.buyer_party_id = :buyer_party_id",
        "bi.team_id = :team_id",
        "bi.workspace_id = :workspace_id",
        "bi.deleted_at is null",
    ]
    params: dict[str, Any] = {
        "buyer_party_id": buyer_party_id,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }
    append_visible_scope(where, params, current_user, entity_type="buyer_intent", alias="bi")
    rows = db.execute(
        text(
            f"""
            select
              bi.id, bi.buyer_party_id, bi.intent_name, bi.status, bi.contact_name,
              bi.raw_requirement_text, bi.intent_summary, bi.industry_primary, bi.industry_secondary,
              bi.region_scope_summary, bi.min_revenue_yuan, bi.min_net_profit_yuan, bi.max_pe,
              bi.max_valuation_yuan, bi.min_market_cap_yuan, bi.max_market_cap_yuan,
              bi.market_cap_range_summary, bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment, bi.preferred_listed_status,
              bi.listing_board_requirement_summary, bi.financing_stage_requirement_summary,
              bi.transaction_type, bi.transaction_types_json, bi.premium_tolerance_summary,
              bi.max_premium_rate, bi.max_debt_ratio, bi.debt_ratio_requirement_summary,
              bi.major_risk_tolerance_summary, bi.buyer_industry_advantage_summary,
              bi.owner_user_id,
              (select au.name from app_user au where au.id = bi.owner_user_id) as owner_name,
              bi.created_at::text as created_at, bi.updated_at::text as updated_at
            from buyer_intent bi
            where {' and '.join(where)}
            order by bi.updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return [dict(row) for row in rows]


@router.patch("/{buyer_party_id}", response_model=BuyerPartyOut)
def update_buyer_party(
    buyer_party_id: UUID,
    payload: BuyerPartyUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_buyer_party_or_404(db, buyer_party_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    changes = payload.model_dump(exclude_unset=True)

    if "owner_user_id" in changes:
        require_admin(current_user)
        if changes["owner_user_id"] is not None:
            ensure_active_user(db, changes["owner_user_id"])

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
            "updated_by": current_user.user_id,
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
        applied_by=current_user.user_id,
    )
    db.commit()
    return dict(row)


@router.delete("/{buyer_party_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_party(
    buyer_party_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    _get_buyer_party_or_404(db, buyer_party_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=buyer_party_id)
    _soft_delete_buyer_parties(db, [buyer_party_id], actor_user_id=current_user.user_id)
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


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized:
        return None
    return normalized if len(normalized) <= max_length else normalized[: max_length - 1].rstrip() + "…"


def _soft_delete_buyer_parties(
    db: Session,
    buyer_party_ids: list[UUID],
    *,
    actor_user_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> list[UUID]:
    if not buyer_party_ids:
        return []
    actor = actor_user_id or DEFAULT_ADMIN_USER_ID

    owner_scope_clause = "and owner_user_id = :owner_user_id" if owner_user_id is not None else ""
    params = {
        "deleted_by": actor,
        "updated_by": actor,
        "buyer_party_ids": buyer_party_ids,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if owner_user_id is not None:
        params["owner_user_id"] = owner_user_id

    rows = db.execute(
        text(
            f"""
            update buyer_party
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id in :buyer_party_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              {owner_scope_clause}
            returning id
            """
        ).bindparams(bindparam("buyer_party_ids", expanding=True)),
        params,
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
            applied_by=actor,
        )
    return deleted_ids


def _buyer_party_params(payload: BuyerPartyCreate, current_user: AuthContext) -> dict[str, Any]:
    # 创建人默认成为负责人；只有管理员可以在创建时指定他人。
    owner_user_id = payload.owner_user_id if current_user.is_admin and payload.owner_user_id else current_user.user_id
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
        "notes": payload.notes,
        "owner_user_id": owner_user_id,
        "created_by": current_user.user_id,
        "updated_by": current_user.user_id,
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
