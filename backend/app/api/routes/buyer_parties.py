from datetime import date
from decimal import Decimal
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
from backend.app.registry.indicators import (
    buyer_party_fact_columns,
    indicator_by_column,
    indicators_for,
    writable_enum_values,
)
from backend.app.services.buyer_party_name import (
    BuyerPartyNameChangeRequiresReview,
    plan_buyer_party_rename,
)

router = APIRouter(prefix="/buyer-parties", tags=["buyer-parties"])

# 枚举取值只在指标注册表声明一次，路由和前端都从它派生。手写第二份闭集
# 必然漂，而漂了不报错——写入被 DB check 打回时人已经离开这个页面了。
_BUYER_PARTY_ENUMS = writable_enum_values("buyer_party")

# not null default 'unknown' 的两列。unknown 不是 null：任何判断「这个字段
# 有没有值」的地方两者必须等价处理，所以写入侧把 null 收敛成 unknown。
_BUYER_PARTY_NOT_NULL_ENUMS = ("ownership_type", "listed_status")

_BUYER_PARTY_YUAN_COLUMNS = tuple(
    ind.column for ind in indicators_for("buyer_party") if ind.kind == "yuan"
)


class BuyerPartyCreate(BaseModel):
    buyer_name: str = Field(min_length=1, max_length=300)
    owner_user_id: UUID | None = None
    aliases_json: list[str] = Field(default_factory=list)
    # 基本信息
    location_province: str | None = None
    location_city: str | None = None
    location_district: str | None = None
    ownership_type: str = "unknown"
    listed_status: str = "unknown"
    stock_code: str | None = Field(default=None, max_length=40)
    listing_exchange: str | None = None
    contact_name: str | None = None
    contact_info_json: dict[str, Any] = Field(default_factory=dict)
    # 我方对接人。text 不是外键：对接人可能没有系统账号。
    our_contact_name: str | None = Field(default=None, max_length=120)
    # 业务信息
    business_tags_json: list[str] = Field(default_factory=list)
    business_summary: str | None = None
    # 财务信息
    market_cap_yuan: Decimal | None = None
    market_cap_as_of: date | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    current_revenue_yuan: Decimal | None = None
    current_operating_cash_flow_yuan: Decimal | None = None
    financial_period_label: str | None = Field(default=None, max_length=80)
    # 其他
    supplementary_summary: str | None = None
    notes: str | None = None


class BuyerPartyUpdate(BaseModel):
    buyer_name: str | None = Field(default=None, min_length=1, max_length=300)
    aliases_json: list[str] | None = None
    location_province: str | None = None
    location_city: str | None = None
    location_district: str | None = None
    ownership_type: str | None = None
    listed_status: str | None = None
    stock_code: str | None = Field(default=None, max_length=40)
    listing_exchange: str | None = None
    contact_name: str | None = None
    contact_info_json: dict[str, Any] | None = None
    our_contact_name: str | None = Field(default=None, max_length=120)
    business_tags_json: list[str] | None = None
    business_summary: str | None = None
    market_cap_yuan: Decimal | None = None
    market_cap_as_of: date | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    current_revenue_yuan: Decimal | None = None
    current_operating_cash_flow_yuan: Decimal | None = None
    financial_period_label: str | None = Field(default=None, max_length=80)
    supplementary_summary: str | None = None
    notes: str | None = None
    owner_user_id: UUID | None = None
    # 改名的来源与复核。默认 manual：PATCH 的调用方是详情页上的人。
    # 非人工来源改名必须显式确认，见 services/buyer_party_name.py。
    # 这两个字段不是业务事实，不落库、不进更新记录。
    name_change_source: Literal["manual", "parse", "research"] = "manual"
    name_change_confirmed: bool = False


class BuyerPartyOut(BaseModel):
    id: UUID
    buyer_name: str
    aliases_json: list[Any]
    location_province: str | None
    location_city: str | None
    location_district: str | None
    ownership_type: str
    listed_status: str
    stock_code: str | None
    listing_exchange: str | None
    contact_name: str | None
    contact_info_json: dict[str, Any]
    our_contact_name: str | None
    business_tags_json: list[str]
    business_summary: str | None
    market_cap_yuan: Decimal | None
    # **类型是 date 不是 str**：它是本表唯一一个真正的 date 列（valuation_date
    # 在 DDL 里是 text，存的是「2025年一季度」这种中文标签）。声明成 str 时，
    # 只要有一条填了这个日期，响应校验就整页失败——标的侧 0818 真炸过一次。
    # 保留 date 而不 ::text：自动刷新要靠它判断「这个市值过没过 7 天」。
    market_cap_as_of: date | None
    valuation_yuan: Decimal | None
    valuation_date: str | None
    current_revenue_yuan: Decimal | None
    current_operating_cash_flow_yuan: Decimal | None
    financial_period_label: str | None
    supplementary_summary: str | None
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
    # industries 组 0824 退役：生产上恒为空（39 条主体 0% 填了行业），
    # 顶上的是企业性质与业务标签——买家自己是什么、买家自己做什么。
    ownership_types: list[BuyerPartyFilterOptionOut]
    business_tags: list[BuyerPartyFilterOptionOut]
    regions: list[BuyerPartyFilterOptionOut]
    statuses: list[BuyerPartyFilterOptionOut]
    owners: list[BuyerPartyFilterOptionOut] = []


class BuyerPartySuggestionOut(BaseModel):
    id: UUID
    search_field: Literal["buyer_name", "alias", "contact_name"]
    match_type: Literal["buyer", "alias", "contact"]
    match_label: str
    match_text: str
    buyer_name: str
    snippet: str | None


class BuyerPartyDedupMatchOut(BaseModel):
    id: UUID
    buyer_name: str
    owner_name: str | None = None
    match_type: Literal["buyer_name", "alias"]
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


# 事实列来自注册表（唯一真源），系统列在这里补齐。以前这份投影是手写的，
# 加一列漏改一处的表现是「字段存进去了但某个页面看不见」，最难查。
_BUYER_PARTY_SYSTEM_COLUMNS = ("id", "aliases_json", "notes", "status", "owner_user_id")

BUYER_PARTY_OUT_COLUMNS = "\n".join(
    [
        *(f"          {column}," for column in _BUYER_PARTY_SYSTEM_COLUMNS),
        *(f"          {column}," for column in buyer_party_fact_columns()),
        "          (select au.name from app_user au where au.id = buyer_party.owner_user_id) as owner_name,",
        "          created_at::text as created_at, updated_at::text as updated_at",
    ]
)


BUYER_PARTY_SEARCH_COLUMNS = {
    "buyer_name": "buyer_name",
    "alias": "aliases_json::text",
    "contact_name": "contact_name",
}

# jsonb 列必须绑成 JSONB，否则会被当字符串写进去。清单从注册表派生：
# 新增一个 jsonb 事实列时不用再想起来补这里。
BUYER_PARTY_JSON_COLUMNS = frozenset(
    {"aliases_json"} | {ind.column for ind in indicators_for("buyer_party") if ind.kind == "json"}
)

# 列表筛选与 filter-options 共用同一个地区表达式。两处写法漂开的表现是
# 「下拉里有这个选项，选了却筛不出东西」。区一级不进筛选：粒度太细、
# 下拉装不下，但详情页仍然三级都显示。
_REGION_EXPRESSION = "concat_ws(' ', nullif(location_province, ''), nullif(location_city, ''))"

_BUYER_PARTY_INSERT_COLUMNS = (
    "team_id",
    "workspace_id",
    "aliases_json",
    "notes",
    *buyer_party_fact_columns(),
    "owner_user_id",
    "created_by",
    "updated_by",
)


@router.post("", response_model=BuyerPartyOut, status_code=status.HTTP_201_CREATED)
def create_buyer_party(
    payload: BuyerPartyCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    statement = text(
        f"""
        insert into buyer_party (
          {', '.join(_BUYER_PARTY_INSERT_COLUMNS)}
        )
        values (
          {', '.join(f':{column}' for column in _BUYER_PARTY_INSERT_COLUMNS)}
        )
        returning
{BUYER_PARTY_OUT_COLUMNS}
        """
    ).bindparams(
        *(
            bindparam(column, type_=JSONB)
            for column in _BUYER_PARTY_INSERT_COLUMNS
            if column in BUYER_PARTY_JSON_COLUMNS
        )
    )
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
    search_field: Literal["buyer_name", "alias", "contact_name"] | None = Query(default=None),
    ownership_type: str | None = Query(default=None, max_length=40),
    business_tag: str | None = Query(default=None, max_length=200),
    region: str | None = Query(default=None, max_length=200),
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
                "buyer_name ilike :q or aliases_json::text ilike :q "
                "or contact_name ilike :q or contact_info_json::text ilike :q "
                "or business_tags_json::text ilike :q or business_summary ilike :q "
                "or notes ilike :q"
                ")"
            )
        params["q"] = f"%{q}%"
    if ownership_type:
        where.append("ownership_type = :ownership_type")
        params["ownership_type"] = ownership_type
    if business_tag:
        where.append("business_tags_json ? :business_tag")
        params["business_tag"] = business_tag
    if region:
        where.append(_REGION_EXPRESSION + " = :region")
        params["region"] = region
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
    # 中文名跟着注册表走：注册表改一处，下拉跟着变。
    ownership_types = _filter_options(
        db,
        f"""
        select ownership_type as value, count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by ownership_type
        order by count desc, ownership_type asc
        """,
        params,
        labels=_enum_labels("ownership_type"),
    )
    business_tags = _filter_options(
        db,
        f"""
        select tag.value as value, count(*) as count
        from buyer_party
        cross join lateral jsonb_array_elements_text(
          case when jsonb_typeof(business_tags_json) = 'array' then business_tags_json else '[]'::jsonb end
        ) as tag(value)
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
          and nullif(tag.value, '') is not null
        group by tag.value
        order by count desc, tag.value asc
        limit 80
        """,
        params,
    )
    regions = _filter_options(
        db,
        f"""
        select
          {_REGION_EXPRESSION} as value,
          count(*) as count
        from buyer_party
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
          and {_REGION_EXPRESSION} <> ''
        group by value
        order by count desc, value asc
        limit 80
        """,
        params,
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
        "ownership_types": ownership_types,
        "business_tags": business_tags,
        "regions": regions,
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
                coalesce(au.name, '未指派') as owner_name,
                bp.status,
                case
                  when lower(bp.buyer_name) = lower(:q) then 'buyer_name'
                  when exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where lower(alias_name) = lower(:q)
                  ) then 'alias'
                  when bp.buyer_name ilike :name_pattern escape '\' then 'buyer_name'
                  else 'alias'
                end as match_type,
                case
                  when lower(bp.buyer_name) = lower(:q) then 1
                  when exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where lower(alias_name) = lower(:q)
                  ) then 2
                  when bp.buyer_name ilike :name_pattern escape '\' then 3
                  else 4
                end as priority,
                bp.updated_at
              from buyer_party bp
              left join app_user au on au.id = bp.owner_user_id
              where bp.team_id = :team_id
                and bp.workspace_id = :workspace_id
                and bp.deleted_at is null
                and (
                  bp.buyer_name ilike :name_pattern escape '\'
                  or exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(bp.aliases_json, '[]'::jsonb)) alias_name
                    where alias_name ilike :name_pattern escape '\'
                  )
                )
            )
            select id, buyer_name, owner_name, match_type, status
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
                id, buyer_name, contact_name, updated_at,
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
                id, buyer_name, contact_name, updated_at,
                'alias'::text as search_field,
                'alias'::text as match_type,
                alias_name as match_text,
                2 as priority
              from buyer_party
              cross join lateral jsonb_array_elements_text(
                case when jsonb_typeof(aliases_json) = 'array' then aliases_json else '[]'::jsonb end
              ) as alias(alias_name)
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and alias_name ilike :q
              union all
              select
                id, buyer_name, contact_name, updated_at,
                'contact_name'::text as search_field,
                'contact'::text as match_type,
                contact_name as match_text,
                3 as priority
              from buyer_party
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and contact_name ilike :q
            )
            select distinct on (id)
              id, buyer_name, contact_name,
              search_field, match_type, match_text
            from matches
            order by id, priority, updated_at desc
            """
        ),
        params,
    ).mappings().all()
    sorted_rows = sorted(
        rows,
        key=lambda row: ({"buyer": 1, "alias": 2, "contact": 3}[row["match_type"]], row["buyer_name"]),
    )
    labels = {"buyer": "买家名称", "alias": "别名", "contact": "联系人"}
    return [
        {
            "id": row["id"],
            "search_field": row["search_field"],
            "match_type": row["match_type"],
            "match_label": labels[row["match_type"]],
            "match_text": row["match_text"],
            "buyer_name": row["buyer_name"],
            "snippet": _truncate_text(row["contact_name"], 80),
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
              bi.id, bi.buyer_party_id, bi.intent_name, bi.intent_grade, bi.status, bi.contact_name,
              bi.raw_requirement_text, bi.intent_summary, bi.industry_primary, bi.industry_secondary,
              bi.region_scope_summary, bi.min_revenue_yuan, bi.min_net_profit_yuan, bi.max_pe,
              bi.max_valuation_yuan, bi.min_market_cap_yuan, bi.max_market_cap_yuan,
              bi.market_cap_range_summary, bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment, bi.preferred_listed_status,
              bi.listing_board_requirement_summary, bi.financing_stage_requirement_summary,
              bi.transaction_type, bi.transaction_types_json, bi.premium_tolerance_summary,
              bi.max_premium_rate, bi.max_debt_ratio, bi.debt_ratio_requirement_summary,
              bi.major_risk_tolerance_summary, bi.unacceptable_risk_flags_json,
              bi.buyer_industry_advantage_summary,
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
    # 改名的来源与复核不是业务事实，不落库也不进更新记录。
    name_change_source = changes.pop("name_change_source", "manual")
    name_change_confirmed = changes.pop("name_change_confirmed", False)

    if "owner_user_id" in changes:
        require_admin(current_user)
        if changes["owner_user_id"] is not None:
            ensure_active_user(db, changes["owner_user_id"])

    if "aliases_json" in changes:
        changes["aliases_json"] = _normalize_aliases(changes["aliases_json"] or [])
    if "buyer_name" in changes and changes["buyer_name"] is not None:
        # 同一次 PATCH 里清空别名时以本次的值为准，不能 `or` 回旧值 ——
        # 空列表是假值，`or` 会把刚清掉的别名整份带回来。
        base_aliases = _normalize_aliases(
            [str(alias) for alias in (original["aliases_json"] or [])]
        )
        current_aliases = changes["aliases_json"] if "aliases_json" in changes else base_aliases
        try:
            renamed, aliases = plan_buyer_party_rename(
                current_name=str(original["buyer_name"]),
                current_aliases=list(current_aliases),
                new_name=str(changes["buyer_name"]),
                source=name_change_source,
                confirmed=name_change_confirmed,
            )
        except BuyerPartyNameChangeRequiresReview as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        changes["buyer_name"] = renamed
        # 旧名进别名，否则顾问下次搜自己录的「北控」就搜不到了 ——
        # dedup-check 与 suggestions 都查别名，append 进去即保住搜索路径。
        if aliases != list(current_aliases):
            changes["aliases_json"] = aliases
    _normalize_buyer_party_facts(changes)

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
    for json_field in BUYER_PARTY_JSON_COLUMNS & changes.keys():
        statement = statement.bindparams(bindparam(json_field, type_=JSONB))

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


def _enum_labels(column: str) -> dict[str, str]:
    """闭集的中文名，来自指标注册表。改注册表一处，下拉跟着变。"""
    return dict(indicator_by_column("buyer_party", column).enum_options or ())


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
    facts = payload.model_dump(include=set(buyer_party_fact_columns()))
    _normalize_buyer_party_facts(facts)
    return {
        **facts,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "aliases_json": _normalize_aliases(payload.aliases_json),
        "notes": payload.notes,
        "owner_user_id": owner_user_id,
        "created_by": current_user.user_id,
        "updated_by": current_user.user_id,
    }


def _normalize_buyer_party_facts(fields: dict[str, Any]) -> None:
    """就地归一化业务事实字段，创建与更新共用同一份规则。

    枚举取值来自指标注册表，**不要在这里手写字面量** —— 手写的第二份闭集
    与注册表漂开时不报错，只会在写入的最后一刻被 DB check 打回。
    """
    if "buyer_name" in fields and fields["buyer_name"] is not None:
        fields["buyer_name"] = str(fields["buyer_name"]).strip()
    if "business_tags_json" in fields:
        fields["business_tags_json"] = _normalize_tags(fields["business_tags_json"] or [])
    for column in _BUYER_PARTY_YUAN_COLUMNS:
        # 对齐 numeric(20,2)：不对齐时 Decimal('3.26E+9') 与库里读出的
        # Decimal('3260000000.00') 字符串不同，diff 会把「没改」记成改过 ——
        # 市值这一格一次保存四列，每次都会给更新记录塞两条假变更。
        if fields.get(column) is not None:
            fields[column] = Decimal(fields[column]).quantize(Decimal("0.01"))
    for column in _BUYER_PARTY_NOT_NULL_ENUMS:
        # unknown 不是 null：这两列是 not null default 'unknown'，前端清空
        # 一个下拉时发的是 null，收敛成 unknown 而不是让 DB 报错。
        if column in fields and fields[column] is None:
            fields[column] = "unknown"
    for column, allowed in _BUYER_PARTY_ENUMS.items():
        value = fields.get(column)
        if column in fields and value is not None and value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported {column}: {value}",
            )


def _normalize_aliases(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if isinstance(value, str) and value.strip()))


def _normalize_tags(values: list[Any]) -> list[str]:
    """业务标签是自由文本，不过行业字典。

    行业字典只有 16 个一级行业，接不住买家的细分主业（实测标签细到
    「钙钛矿组件材料」）—— 强行归一等于把信息丢掉。数量上限由解析侧控制，
    这里只做去空白、去重、去空。
    """
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if value is not None and str(value).strip()
        )
    )


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
