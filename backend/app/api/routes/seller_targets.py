from decimal import Decimal
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import AuthContext, CurrentUser, require_admin
from backend.app.api.routes.attachments import _attachment_parse_readiness
from backend.app.api.routes.utils import (
    append_owner_scope,
    assign_owner_bulk,
    diff_payload,
    ensure_entity_visible,
    ensure_entity_writable,
    ensure_active_user,
    owner_scope_required,
    owner_filter_condition,
    owner_filter_options,
    write_action_log,
    write_action_logs_for_diff,
)
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db
from backend.app.registry.indicators import seller_target_fact_columns, writable_columns
from backend.app.services.field_writer import FieldWriteError, WriteProvenance, write_seller_target_fields
from backend.app.services.industry_taxonomy import normalize_industry_pairs
from backend.app.services.attachment_storage import (
    AttachmentNotFoundError,
    AttachmentStorageError,
    AttachmentTooLargeError,
    read_attachment_bytes,
)
from backend.app.services.image_inputs import is_supported_multimodal_image
from backend.app.services.region_dictionary import (
    normalize_city,
    normalize_district,
    normalize_province,
)
from backend.app.services.search_docs import create_search_doc_rebuild_job
from backend.app.services.seller_target_status import (
    AIProcessingBusyError,
    acquire_ai_processing,
    ai_processing_detail,
    ai_processing_state,
)

router = APIRouter(prefix="/seller-targets", tags=["seller-targets"])


class SellerTargetCreate(BaseModel):
    target_name: str = Field(min_length=1, max_length=300)
    target_type: str = "company"
    target_subject_name: str | None = Field(default=None, max_length=300)
    owner_user_id: UUID | None = None
    lifecycle_status: Literal["active", "sold", "off_market"] = "active"
    information_status: Literal[
        "normal",
        "insufficient",
        "parsing",
    ] = "insufficient"
    industry_l1: str | None = None
    industry_l2: str | None = None
    industry_pairs_json: list[dict[str, str]] = Field(default_factory=list)
    location_province: str | None = None
    location_city: str | None = None
    location_district: str | None = None
    listed_status: str = "unknown"
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    asking_price_yuan: Decimal | None = None
    asking_price_date: str | None = Field(default=None, max_length=80)
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
    target_subject_name: str | None
    lifecycle_status: str
    information_status: str
    ai_processing_state: str
    ai_processing_detail: str
    pending_research_conflict_count: int = 0
    research_job_type: str | None = None
    research_job_status: str | None = None
    industry_l1: str | None = None
    industry_l2: str | None = None
    industry_pairs_json: list[dict[str, str]] = Field(default_factory=list)
    main_products_text: str | None = None
    location_province: str | None
    location_city: str | None
    location_district: str | None
    listed_status: str
    stock_code: str | None = None
    listing_market_region: str | None = None
    market_cap_yuan: Decimal | None
    current_revenue_yuan: Decimal | None
    current_net_profit_yuan: Decimal | None
    current_total_profit_yuan: Decimal | None
    current_assets_yuan: Decimal | None
    current_debt_ratio: Decimal | None
    current_operating_cash_flow_yuan: Decimal | None
    financial_period_label: str | None
    profitability_status: str | None
    cash_flow_status: str | None
    valuation_yuan: Decimal | None
    valuation_date: str | None
    asking_price_yuan: Decimal | None
    asking_price_date: str | None
    pe_ratio: Decimal | None
    pe_source_type: str | None
    premium_rate: Decimal | None
    is_for_sale: str
    can_control: str
    can_consolidate: str
    accepts_minority_investment: str
    transfer_ratio_min: Decimal | None
    transfer_ratio_max: Decimal | None
    transfer_ratio_text: str | None
    accepts_relocation: str
    accepts_return_investment: str
    management_retention_possible: str
    acceptable_transaction_structures_json: list[str] = Field(default_factory=list)
    business_summary: str | None
    transaction_summary: str | None
    # [] 未核查 / ["none"] 已核查无风险 / 其余已核查有风险，三种状态一个字段表达。
    major_risk_flags_json: list[str] = Field(default_factory=list)
    risk_summary: str | None
    gap_summary: str | None
    owner_user_id: UUID | None = None
    owner_name: str | None = None
    # 调研节流靠界面二次确认，不靠服务端静默跳过，所以列表也要带上最近调研时间。
    last_research_at: str | None = None
    last_parse_at: str | None = None
    research_last_outcome: str | None = None
    created_at: str
    updated_at: str


class SellerTargetListOut(BaseModel):
    items: list[SellerTargetOut]
    total: int
    limit: int
    offset: int


class SellerTargetUpdate(BaseModel):
    target_name: str | None = Field(default=None, min_length=1, max_length=300)
    target_type: str | None = None
    target_subject_name: str | None = Field(default=None, max_length=300)
    industry_l1: str | None = None
    industry_l2: str | None = None
    industry_pairs_json: list[dict[str, str]] | None = None
    main_products_text: str | None = Field(default=None, max_length=400)
    location_province: str | None = None
    location_city: str | None = None
    location_district: str | None = None
    listed_status: str | None = None
    stock_code: str | None = Field(default=None, max_length=40)
    market_cap_yuan: Decimal | None = None
    current_revenue_yuan: Decimal | None = None
    current_net_profit_yuan: Decimal | None = None
    current_total_profit_yuan: Decimal | None = None
    current_assets_yuan: Decimal | None = None
    current_debt_ratio: Decimal | None = None
    current_operating_cash_flow_yuan: Decimal | None = None
    financial_period_label: str | None = None
    profitability_status: str | None = None
    cash_flow_status: str | None = None
    valuation_yuan: Decimal | None = None
    valuation_date: str | None = Field(default=None, max_length=80)
    asking_price_yuan: Decimal | None = None
    asking_price_date: str | None = Field(default=None, max_length=80)
    pe_ratio: Decimal | None = None
    pe_source_type: str | None = None
    premium_rate: Decimal | None = None
    is_for_sale: str | None = None
    can_control: str | None = None
    can_consolidate: str | None = None
    accepts_minority_investment: str | None = None
    transfer_ratio_min: Decimal | None = None
    transfer_ratio_max: Decimal | None = None
    transfer_ratio_text: str | None = None
    accepts_relocation: str | None = None
    accepts_return_investment: str | None = None
    management_retention_possible: str | None = None
    acceptable_transaction_structures_json: list[str] | None = None
    lifecycle_status: Literal["active", "sold", "off_market"] | None = None
    business_summary: str | None = None
    transaction_summary: str | None = None
    major_risk_flags_json: list[str] | None = None
    risk_summary: str | None = None
    owner_user_id: UUID | None = None


class SellerTargetParseRequest(BaseModel):
    raw_target_text: str | None = Field(default=None, min_length=1)
    force: bool = False


class SellerTargetFieldsUpdate(BaseModel):
    """Manual changes to information-page facts only.

    The field set and its type/enum validation live in the indicator registry,
    not in a second API whitelist.
    """

    changes: dict[str, Any] = Field(min_length=1, max_length=100)


class SellerTargetParseJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    seller_target_id: UUID


class SellerTargetParseStatusOut(BaseModel):
    seller_target: dict[str, Any]
    latest_job: dict[str, Any] | None
    latest_trace: dict[str, Any] | None
    recent_update_logs: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class SellerTargetFilterOptionOut(BaseModel):
    value: str
    label: str
    count: int


class SellerTargetCountedOptionOut(BaseModel):
    """A cascader level. ``count`` annotates a dictionary entry, it does not
    define it — the frontend renders the full taxonomy/area dictionary and uses
    these counts to show how many targets sit behind each choice."""

    value: str
    count: int
    children: list["SellerTargetCountedOptionOut"] = []


class SellerTargetFilterOptionsOut(BaseModel):
    industries: list[SellerTargetCountedOptionOut]
    regions: list[SellerTargetCountedOptionOut]
    statuses: list[SellerTargetFilterOptionOut]
    owners: list[SellerTargetFilterOptionOut] = []


class SellerTargetDedupCheckOut(BaseModel):
    query: str
    matches: list[str]


class SellerTargetSuggestionOut(BaseModel):
    id: UUID
    search_field: Literal["target_name", "target_subject_name", "business_summary"]
    match_type: Literal["target", "subject", "summary"]
    match_label: str
    match_text: str
    target_name: str
    target_subject_name: str | None
    snippet: str | None


class SellerTargetBulkDeleteRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class SellerTargetBulkDeleteOut(BaseModel):
    status: str
    deleted_count: int
    deleted_ids: list[UUID]
    skipped_ids: list[UUID]


class SellerTargetAttachmentItemOut(BaseModel):
    id: UUID
    file_name: str
    file_type: str | None
    mime_type: str | None
    file_size: int | None
    uploaded_by: UUID | None
    uploaded_by_name: str | None
    uploaded_at: str
    link_type: str | None
    linked_at: str | None
    parse_status: str
    display_status: str
    parse_readiness: dict[str, Any]
    latest_job: dict[str, Any] | None
    latest_parsed_document: dict[str, Any] | None
    latest_evidence: dict[str, Any] | None
    evidence_count: int
    related_business_updates: list[dict[str, Any]]
    download_route: str
    delete_route: str
    debug_ref: dict[str, str]


class SellerTargetAttachmentListOut(BaseModel):
    seller_target_id: UUID
    items: list[SellerTargetAttachmentItemOut]


# 事实列来自指标注册表（唯一事实源），系统列在这里补。以前整份清单是手写的，
# 与另外三处手写投影各自漂移；加一列漏改一处的表现是「字段存进去了但某个页面
# 看不见」。列名不是外部输入，可以安全拼接。
SELLER_TARGET_OUT_COLUMNS = f"""
              id, lifecycle_status,
              {", ".join(seller_target_fact_columns())},
              owner_user_id,
              (select au.name from app_user au where au.id = seller_target.owner_user_id) as owner_name,
              last_research_at::text as last_research_at, last_parse_at::text as last_parse_at,
              research_last_outcome,
              (select count(*)
               from research_proposal rp
               where rp.team_id = seller_target.team_id
                 and rp.workspace_id = seller_target.workspace_id
                 and rp.entity_type = 'seller_target'
                 and rp.entity_id = seller_target.id
                 and rp.review_status = 'pending_review'
                 and rp.conflict_kind = 'same_period_conflict'
                 and rp.deleted_at is null) as pending_research_conflict_count,
              created_at::text as created_at, updated_at::text as updated_at
"""

ACTIVE_RESEARCH_JOB_LATERAL_SQL = """
            left join lateral (
              select job.job_type, job.status
              from background_job job
              where job.team_id = seller_target.team_id
                and job.workspace_id = seller_target.workspace_id
                and job.entity_type = 'seller_target'
                and job.entity_id = seller_target.id
                and job.job_type in ('seller_target_research', 'seller_target_research_map')
                and job.status in ('queued', 'running', 'retry_waiting')
              order by job.created_at desc
              limit 1
            ) active_research_job on true
"""

# The列表「状态」列 is the trade lifecycle and nothing else. AI progress lives in
# its own column (services/seller_target_status.py) because mixing the two is
# what let a parsed target read as "未解析" while being excluded from screening.
SELLER_TARGET_DISPLAY_STATUS_SQL = """
              case
                when lifecycle_status = 'sold' then 'sold'
                when lifecycle_status = 'off_market' then 'off_market'
                else 'active'
              end
"""

SELLER_TARGET_DISPLAY_STATUS_LABELS = {
    "active": "在售中",
    "sold": "已售出",
    "off_market": "已停售",
}


def _seller_target_out(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["ai_processing_state"] = ai_processing_state(result)
    result["ai_processing_detail"] = ai_processing_detail(result)
    return result


@router.post("", response_model=SellerTargetOut, status_code=status.HTTP_201_CREATED)
def create_seller_target(
    payload: SellerTargetCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    params = _seller_target_params(payload, current_user)
    pairs = _normalized_create_industry_pairs(db, params)
    params["industry_pairs_json"] = pairs
    if pairs:
        params["industry_l1"] = pairs[0]["l1"]
        params["industry_l2"] = pairs[0].get("l2")
    row = db.execute(
        text(
            f"""
            insert into seller_target (
              team_id, workspace_id, target_name, target_type, target_subject_name, owner_user_id,
              lifecycle_status, information_status,
              industry_l1, industry_l2, industry_pairs_json, location_province, location_city, location_district,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, valuation_date, asking_price_yuan, asking_price_date, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :target_name, :target_type, :target_subject_name, :owner_user_id,
              :lifecycle_status, :information_status,
              :industry_l1, :industry_l2, :industry_pairs_json, :location_province, :location_city, :location_district,
              :listed_status, :current_revenue_yuan, :current_net_profit_yuan,
              :valuation_yuan, :valuation_date, :asking_price_yuan, :asking_price_date, :pe_ratio,
              :is_for_sale, :can_control, :can_consolidate,
              :business_summary, :transaction_summary, :risk_summary,
              :created_by, :updated_by
            )
            returning
{SELLER_TARGET_OUT_COLUMNS}
            """
        ).bindparams(bindparam("industry_pairs_json", type_=JSONB)),
        params,
    ).mappings().one()
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=row["id"],
        source="seller_target_create",
    )
    db.commit()
    return _seller_target_out(row)


def _normalized_create_industry_pairs(db: Session, params: dict[str, Any]) -> list[dict[str, str]]:
    raw_pairs = params["industry_pairs_json"]
    # An industry is optional at creation time.  Only use the retired scalar
    # fields as a compatibility input when the caller actually supplied one;
    # turning an empty pair into ``[{l1: null, l2: null}]`` made a blank
    # industry incorrectly fail dictionary validation with 422.
    if not raw_pairs and (params.get("industry_l1") or params.get("industry_l2")):
        raw_pairs = [{"l1": params.get("industry_l1"), "l2": params.get("industry_l2")}]
    pairs, notes = normalize_industry_pairs(db, raw_pairs)
    if raw_pairs and not pairs:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"行业不在字典中：{notes[0] if notes else '无有效行业'}")
    return pairs


# Industry is searchable because it is a fact about the target, not just a
# filter facet: 搜「食品」 must find a 商贸与消费/食品 target whose summary happens
# to say 预制菜研发生产.
_INDUSTRY_PAIR_SEARCH_SQL = (
    "exists (select 1 from jsonb_array_elements(industry_pairs_json) pair "
    "where pair ->> 'l1' ilike :q or pair ->> 'l2' ilike :q)"
)

SELLER_TARGET_SEARCH_COLUMNS = {
    "target_name": "target_name",
    "target_subject_name": "target_subject_name",
    "business_summary": "business_summary",
    "industry": _INDUSTRY_PAIR_SEARCH_SQL,
}

SellerTargetSearchField = Literal[
    "target_name", "target_subject_name", "business_summary", "industry"
]


def _search_filter(
    where: list[str],
    params: dict[str, Any],
    *,
    q: str | None,
    search_field: str | None,
) -> None:
    if not q:
        return
    if search_field == "industry":
        where.append(_INDUSTRY_PAIR_SEARCH_SQL)
    elif search_field:
        where.append(f"{SELLER_TARGET_SEARCH_COLUMNS[search_field]} ilike :q")
    else:
        where.append(
            "(target_name ilike :q or target_subject_name ilike :q "
            f"or business_summary ilike :q or {_INDUSTRY_PAIR_SEARCH_SQL})"
        )
    params["q"] = f"%{q}%"


def _location_filter(
    where: list[str],
    params: dict[str, Any],
    *,
    province: str | None,
    city: str | None,
    district: str | None,
) -> None:
    """Match at whatever level the user picked, independently per column.

    The retired filter compared a flattened "省 市 区" string for equality, so
    选「广东省」 could only ever match targets whose city and district were both
    blank. Province is normalized on the way in for the same reason it is
    normalized on write: a hand-edited URL saying 广东 must still find 广东省.
    """
    for column, value, normalizer in (
        ("location_province", province, normalize_province),
        ("location_city", city, normalize_city),
        ("location_district", district, normalize_district),
    ):
        normalized = normalizer(value)
        if normalized is None:
            continue
        where.append(f"{column} = :{column}")
        params[column] = normalized


def _industry_filter(
    where: list[str],
    params: dict[str, Any],
    *,
    industry_l1: str | None,
    industry_l2: str | None,
) -> None:
    """Both levels must hit the *same* pair, so 制造与工业/食品 never satisfies
    a 商贸与消费 + 食品 filter through two unrelated pairs."""
    conditions: list[str] = []
    if industry_l1:
        conditions.append("pair ->> 'l1' = :industry_l1")
        params["industry_l1"] = industry_l1
    if industry_l2:
        conditions.append("pair ->> 'l2' = :industry_l2")
        params["industry_l2"] = industry_l2
    if not conditions:
        return
    where.append(
        "exists (select 1 from jsonb_array_elements(industry_pairs_json) pair "
        f"where {' and '.join(conditions)})"
    )


@router.get("", response_model=SellerTargetListOut)
def list_seller_targets(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    search_field: SellerTargetSearchField | None = Query(default=None),
    industry_l1: str | None = Query(default=None, max_length=120),
    industry_l2: str | None = Query(default=None, max_length=120),
    province: str | None = Query(default=None, max_length=60),
    city: str | None = Query(default=None, max_length=60),
    district: str | None = Query(default=None, max_length=60),
    status: Literal["active", "sold", "off_market"] | None = Query(default=None),
    owner: str | None = Query(default=None, max_length=50),
) -> dict[str, Any]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id", "deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    append_owner_scope(where, params, current_user, entity_type="seller_target", alias="seller_target")

    owner_condition = owner_filter_condition(owner)
    if owner_condition:
        condition_sql, owner_param = owner_condition
        where.append(condition_sql)
        if owner_param is not None:
            params["owner_user_id"] = owner_param

    _search_filter(where, params, q=q, search_field=search_field)
    _industry_filter(where, params, industry_l1=industry_l1, industry_l2=industry_l2)
    _location_filter(where, params, province=province, city=city, district=district)
    if status:
        where.append("lifecycle_status = :status")
        params["status"] = status

    where_sql = " and ".join(where)
    total = db.execute(
        text(
            f"""
            select count(*)
            from seller_target
            where {where_sql}
            """
        ),
        params,
    ).scalar_one()

    rows = db.execute(
        text(
            f"""
            select
{SELLER_TARGET_OUT_COLUMNS},
              active_research_job.job_type as research_job_type,
              active_research_job.status as research_job_status
            from seller_target
{ACTIVE_RESEARCH_JOB_LATERAL_SQL}
            where {where_sql}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return {"items": [_seller_target_out(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options", response_model=SellerTargetFilterOptionsOut)
def seller_target_filter_options(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    scope_clause = ""
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        scope_clause = "and owner_user_id = :scope_user_id"
    # Both cascaders render a *dictionary* skeleton (industry taxonomy /
    # @vant/area-data) and use these counts only as annotation, so a value that
    # nobody has used yet is still selectable. That is why these are grouped by
    # level instead of by the flattened leaf string the old filters compared.
    industry_rows = db.execute(
        text(
            f"""
            with target_pairs as (
              select distinct
                seller_target.id as target_id,
                pair ->> 'l1' as l1,
                nullif(pair ->> 'l2', '') as l2
              from seller_target
              cross join lateral jsonb_array_elements(industry_pairs_json) pair
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and coalesce(pair ->> 'l1', '') <> ''
            ), l1_counts as (
              select l1, count(distinct target_id) as l1_count
              from target_pairs
              group by l1
            )
            select
              target_pairs.l1,
              target_pairs.l2,
              count(distinct target_pairs.target_id) as count,
              l1_counts.l1_count
            from target_pairs
            join l1_counts using (l1)
            group by target_pairs.l1, target_pairs.l2, l1_counts.l1_count
            """
        ),
        params,
    ).mappings().all()
    region_rows = db.execute(
        text(
            f"""
            select
              nullif(location_province, '') as province,
              nullif(location_city, '') as city,
              nullif(location_district, '') as district,
              count(*) as count
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              {scope_clause}
              and nullif(location_province, '') is not null
            group by province, city, district
            """
        ),
        params,
    ).mappings().all()
    statuses = _filter_options(
        db,
        f"""
        select ({SELLER_TARGET_DISPLAY_STATUS_SQL}) as value, count(*) as count
        from seller_target
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by value
        order by count desc, value asc
        """,
        params,
        labels=SELLER_TARGET_DISPLAY_STATUS_LABELS,
    )
    owners = [] if owner_scope_required(current_user) else owner_filter_options(db, "seller_target", params)
    return {
        "industries": _industry_option_tree(industry_rows),
        "regions": _region_option_tree(region_rows),
        "statuses": statuses,
        "owners": owners,
    }


@router.get("/dedup-check", response_model=SellerTargetDedupCheckOut)
def seller_target_dedup_check(
    current_user: CurrentUser,
    q: str = Query(min_length=1, max_length=300),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"query": "", "matches": []}

    # This intentionally ignores the caller's broader visibility scope. A
    # consultant and an admin both check only the targets they personally own,
    # because the warning is about duplicates in the current user's own book.
    # Escape LIKE metacharacters so '%' and '_' in a name stay literal.
    escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    names = (
        db.execute(
            text(
                r"""
                select target_name
                from seller_target
                where team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                  and owner_user_id = :owner_user_id
                  and target_name ilike :name_pattern escape '\'
                group by target_name
                order by (target_name ilike :exact_name escape '\') desc,
                         max(updated_at) desc,
                         target_name asc
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "owner_user_id": current_user.user_id,
                "name_pattern": f"%{escaped_query}%",
                "exact_name": escaped_query,
            },
        )
        .scalars()
        .all()
    )
    return {"query": query, "matches": list(names)}


def _industry_option_tree(rows: list[Any]) -> list[dict[str, Any]]:
    """Roll (l1, l2, count) rows up into the two levels the cascader renders.

    An L1 count is the number of targets carrying that L1 in *any* pair, so it
    matches what selecting that L1 alone will return.
    """
    by_l1: dict[str, dict[str, Any]] = {}
    for row in rows:
        level_one = by_l1.setdefault(
            row["l1"],
            {"value": row["l1"], "count": int(row["l1_count"]), "children": {}},
        )
        if row["l2"]:
            child = level_one["children"].setdefault(row["l2"], {"value": row["l2"], "count": 0})
            child["count"] += int(row["count"])
    return [
        {
            "value": item["value"],
            "count": item["count"],
            "children": sorted(
                item["children"].values(), key=lambda child: (-child["count"], child["value"])
            ),
        }
        for item in sorted(by_l1.values(), key=lambda item: (-item["count"], item["value"]))
    ]


def _region_option_tree(rows: list[Any]) -> list[dict[str, Any]]:
    provinces: dict[str, dict[str, Any]] = {}
    for row in rows:
        province = provinces.setdefault(
            row["province"], {"value": row["province"], "count": 0, "children": {}}
        )
        province["count"] += int(row["count"])
        if not row["city"]:
            continue
        city = province["children"].setdefault(
            row["city"], {"value": row["city"], "count": 0, "children": {}}
        )
        city["count"] += int(row["count"])
        if row["district"]:
            district = city["children"].setdefault(
                row["district"], {"value": row["district"], "count": 0}
            )
            district["count"] += int(row["count"])
    return [
        {
            "value": province["value"],
            "count": province["count"],
            "children": [
                {
                    "value": city["value"],
                    "count": city["count"],
                    "children": sorted(
                        city["children"].values(),
                        key=lambda item: (-item["count"], item["value"]),
                    ),
                }
                for city in sorted(
                    province["children"].values(),
                    key=lambda item: (-item["count"], item["value"]),
                )
            ],
        }
        for province in sorted(
            provinces.values(), key=lambda item: (-item["count"], item["value"])
        )
    ]


@router.get("/suggestions", response_model=list[SellerTargetSuggestionOut])
def seller_target_suggestions(
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
        scope_clause = "and owner_user_id = :scope_user_id"
        params["scope_user_id"] = current_user.user_id

    rows = db.execute(
        text(
            f"""
            with matches as (
              select
                id, target_name, target_subject_name, business_summary, updated_at,
                'target_name'::text as search_field,
                'target'::text as match_type,
                target_name as match_text,
                1 as priority
              from seller_target
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and target_name ilike :q
              union all
              select
                id, target_name, target_subject_name, business_summary, updated_at,
                'target_subject_name'::text as search_field,
                'subject'::text as match_type,
                target_subject_name as match_text,
                2 as priority
              from seller_target
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and target_subject_name ilike :q
              union all
              select
                id, target_name, target_subject_name, business_summary, updated_at,
                'business_summary'::text as search_field,
                'summary'::text as match_type,
                business_summary as match_text,
                3 as priority
              from seller_target
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                {scope_clause}
                and business_summary ilike :q
            )
            select distinct on (id)
              id, target_name, target_subject_name, business_summary,
              search_field, match_type, match_text
            from matches
            order by id, priority, updated_at desc
            """
        ),
        params,
    ).mappings().all()
    sorted_rows = sorted(rows, key=lambda row: ({"target": 1, "subject": 2, "summary": 3}[row["match_type"]], row["target_name"]))
    return [
        {
            "id": row["id"],
            "search_field": row["search_field"],
            "match_type": row["match_type"],
            "match_label": {"target": "标的", "subject": "主体", "summary": "摘要"}[row["match_type"]],
            "match_text": row["match_text"],
            "target_name": row["target_name"],
            "target_subject_name": row["target_subject_name"],
            "snippet": _truncate_text(row["business_summary"], 80),
        }
        for row in sorted_rows[:limit]
    ]


@router.post("/bulk-delete", response_model=SellerTargetBulkDeleteOut)
def bulk_delete_seller_targets(
    payload: SellerTargetBulkDeleteRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target_ids = list(dict.fromkeys(payload.ids))
    deleted_ids = _soft_delete_seller_targets(
        db,
        target_ids,
        actor_user_id=current_user.user_id,
        owner_user_id=None if current_user.is_admin else current_user.user_id,
    )
    deleted_id_set = set(deleted_ids)
    skipped_ids = [target_id for target_id in target_ids if target_id not in deleted_id_set]
    db.commit()
    return {
        "status": "ok",
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped_ids": skipped_ids,
    }


class SellerTargetBatchAssignOwnerRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)
    owner_user_id: UUID | None = None


class BatchAssignOwnerOut(BaseModel):
    status: str
    updated_count: int
    updated_ids: list[UUID]


@router.post("/batch-assign-owner", response_model=BatchAssignOwnerOut)
def batch_assign_seller_target_owner(
    payload: SellerTargetBatchAssignOwnerRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    if payload.owner_user_id is not None:
        ensure_active_user(db, payload.owner_user_id)
    updated_ids = assign_owner_bulk(
        db,
        table="seller_target",
        entity_type="seller_target",
        entity_ids=list(dict.fromkeys(payload.ids)),
        new_owner_user_id=payload.owner_user_id,
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return {"status": "ok", "updated_count": len(updated_ids), "updated_ids": updated_ids}


@router.get("/{seller_target_id}/attachments", response_model=SellerTargetAttachmentListOut)
def list_seller_target_attachments(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    rows = _seller_target_attachment_rows(db, seller_target_id)
    related_updates = _attachment_related_business_updates(db, [row["id"] for row in rows])
    return {
        "seller_target_id": seller_target_id,
        "items": [
            _compact_target_attachment(row, related_updates.get(row["id"], []))
            for row in rows
        ],
    }


@router.get("/{seller_target_id}/attachments/{attachment_id}/download")
def download_seller_target_attachment(
    seller_target_id: UUID,
    attachment_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> Response:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    attachment = _get_seller_target_attachment_or_404(db, seller_target_id, attachment_id)
    settings = get_settings()
    try:
        content = read_attachment_bytes(
            attachment,
            storage_dir=settings.attachment_storage_dir,
            max_bytes=settings.attachment_max_upload_bytes,
            s3_endpoint_url=settings.effective_attachment_s3_endpoint_url,
            s3_region=settings.effective_attachment_s3_region,
            s3_bucket=settings.effective_attachment_s3_bucket,
            s3_access_key_id=settings.effective_attachment_s3_access_key_id,
            s3_secret_access_key=settings.effective_attachment_s3_secret_access_key,
            s3_force_path_style=settings.attachment_s3_force_path_style,
        )
    except AttachmentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AttachmentStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment bytes not found.",
        )

    file_name = attachment.get("file_name") or "attachment"
    quoted_file_name = quote(str(file_name))
    return Response(
        content=content,
        media_type=attachment.get("mime_type") or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_file_name}",
            "Content-Length": str(len(content)),
        },
    )


@router.delete(
    "/{seller_target_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_seller_target_attachment(
    seller_target_id: UUID,
    attachment_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    _get_seller_target_attachment_or_404(db, seller_target_id, attachment_id)
    db.execute(
        text(
            """
            update attachment
            set deleted_at = now(), deleted_by = :deleted_by
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "attachment_id": attachment_id,
            "deleted_by": current_user.user_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    db.commit()


@router.get("/{seller_target_id}", response_model=SellerTargetOut)
def get_seller_target(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target = _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    return target


@router.post("/{seller_target_id}/parse", response_model=SellerTargetParseJobOut)
def parse_seller_target(
    seller_target_id: UUID,
    current_user: CurrentUser,
    payload: SellerTargetParseRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target = _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    request = payload or SellerTargetParseRequest()
    raw_target_text = request.raw_target_text or _seller_target_parse_fallback_text(target)
    if not raw_target_text or not raw_target_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="raw_target_text or existing seller target summary is required to parse seller target.",
        )

    if not request.force:
        existing_job = _latest_active_parse_job(db, seller_target_id)
        if existing_job:
            db.commit()
            return {
                "job_id": existing_job["id"],
                "job_type": existing_job["job_type"],
                "status": existing_job["status"],
                "queue_name": existing_job["queue_name"],
                "seller_target_id": existing_job["entity_id"],
            }

    # Mark the target before enqueueing: the list polls information_status to
    # show 「解析中」, and the failure path only flips to parse_failed for rows
    # that were in 'parsing' — without this, a re-parse that fails leaves no
    # trace anywhere the consultant looks.
    try:
        acquire_ai_processing(
            db,
            seller_target_id=seller_target_id,
            desired_status="parsing",
            actor_user_id=current_user.user_id,
        )
    except AIProcessingBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'seller_target_parse', 100, 'llm',
              'seller_target', :seller_target_id, :idempotency_key, :payload_json,
              :created_by, :metadata_json
            )
            returning id, job_type, status, queue_name, entity_id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": seller_target_id,
            "idempotency_key": f"seller_target_parse:{seller_target_id}:{uuid4()}",
            "payload_json": {
                "seller_target_id": str(seller_target_id),
                "raw_target_text": raw_target_text,
            },
            "created_by": current_user.user_id,
            "metadata_json": {"source": "seller_target_parse_api"},
        },
    ).mappings().one()
    db.commit()
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "seller_target_id": row["entity_id"],
    }


@router.get("/{seller_target_id}/parse-status", response_model=SellerTargetParseStatusOut)
def get_seller_target_parse_status(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    target = _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    latest_job = _latest_parse_job(db, seller_target_id)
    latest_trace = _latest_parse_trace(db, seller_target_id)
    return {
        "seller_target": target,
        "latest_job": _compact_parse_job(latest_job) if latest_job else None,
        "latest_trace": _compact_parse_trace(latest_trace) if latest_trace else None,
        "recent_update_logs": _recent_parse_update_logs(db, seller_target_id),
        "debug_ref": _debug_ref("seller_target", seller_target_id),
    }


@router.patch("/{seller_target_id}", response_model=SellerTargetOut)
def update_seller_target(
    seller_target_id: UUID,
    payload: SellerTargetUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    changes = payload.model_dump(exclude_unset=True)
    if "industry_pairs_json" not in changes and ("industry_l1" in changes or "industry_l2" in changes):
        legacy_pair = {"l1": changes.get("industry_l1"), "l2": changes.get("industry_l2")}
        if legacy_pair["l1"] or legacy_pair["l2"]:
            changes["industry_pairs_json"] = [legacy_pair]
    changes.pop("industry_l1", None)
    changes.pop("industry_l2", None)

    fact_changes = {key: value for key, value in changes.items() if key in writable_columns("manual")}
    if fact_changes:
        _write_manual_information_fields(db, seller_target_id, fact_changes, current_user.user_id)
        changes = {key: value for key, value in changes.items() if key not in fact_changes}

    if "owner_user_id" in changes:
        require_admin(current_user)
        if changes["owner_user_id"] is not None:
            ensure_active_user(db, changes["owner_user_id"])

    if "target_name" in changes and changes["target_name"] is not None:
        changes["target_name"] = changes["target_name"].strip()
    for text_field in ("target_subject_name", "valuation_date", "asking_price_date"):
        if text_field in changes and changes[text_field] is not None:
            changes[text_field] = _normalize_optional_text(changes[text_field])

    if not changes:
        db.commit()
        return _get_seller_target_or_404(db, seller_target_id)

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
{SELLER_TARGET_OUT_COLUMNS}
            """
        ),
        {
            **changes,
            "updated_by": current_user.user_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()

    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        diff=diff,
        applied_by=current_user.user_id,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source="seller_target_update",
    )

    db.commit()
    return _seller_target_out(row)


@router.patch("/{seller_target_id}/fields", response_model=SellerTargetOut)
def update_seller_target_information_fields(
    seller_target_id: UUID,
    payload: SellerTargetFieldsUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Edit any information-page field through the single fact writer."""
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    _write_manual_information_fields(db, seller_target_id, payload.changes, current_user.user_id)
    db.commit()
    return _get_seller_target_or_404(db, seller_target_id)


def _write_manual_information_fields(
    db: Session,
    seller_target_id: UUID,
    changes: dict[str, Any],
    actor_user_id: UUID,
) -> None:
    try:
        write_seller_target_fields(
            db,
            seller_target_id,
            changes,
            provenance=WriteProvenance(
                source_type="manual_edit",
                actor_user_id=actor_user_id,
                writer="manual",
                field_source_label="手动编辑",
                review_status="accepted",
            ),
            search_doc_source="seller_target_manual_edit",
        )
    except FieldWriteError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.delete("/{seller_target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_seller_target(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    _soft_delete_seller_targets(db, [seller_target_id], actor_user_id=current_user.user_id)
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


def _soft_delete_seller_targets(
    db: Session,
    seller_target_ids: list[UUID],
    *,
    actor_user_id: UUID | None = None,
    owner_user_id: UUID | None = None,
) -> list[UUID]:
    if not seller_target_ids:
        return []
    actor = actor_user_id or DEFAULT_ADMIN_USER_ID

    owner_scope_clause = "and owner_user_id = :owner_user_id" if owner_user_id is not None else ""
    params = {
        "deleted_by": actor,
        "updated_by": actor,
        "seller_target_ids": seller_target_ids,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if owner_user_id is not None:
        params["owner_user_id"] = owner_user_id

    rows = db.execute(
        text(
            f"""
            update seller_target
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id in :seller_target_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              {owner_scope_clause}
            returning id
            """
        ).bindparams(bindparam("seller_target_ids", expanding=True)),
        params,
    ).mappings().all()
    deleted_ids = [row["id"] for row in rows]
    for deleted_id in deleted_ids:
        write_action_log(
            db,
            entity_type="seller_target",
            entity_id=deleted_id,
            field_path="deleted_at",
            old_value=None,
            new_value="now()",
            applied_by=actor,
        )
    return deleted_ids


def _seller_target_attachment_rows(db: Session, seller_target_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            with target_links as (
              select distinct on (attachment_id)
                id, attachment_id, link_type, created_at
              from attachment_link
              where team_id = :team_id
                and workspace_id = :workspace_id
                and entity_type = 'seller_target'
                and entity_id = :seller_target_id
              order by attachment_id, created_at desc
            )
            select
              :seller_target_id as seller_target_id,
              a.id, a.visibility, a.file_name, a.file_type, a.mime_type, a.file_size,
              a.storage_path, a.uploaded_by, coalesce(u.name, '管理员') as uploaded_by_name,
              a.uploaded_at::text as uploaded_at, a.parse_status, a.metadata_json,
              a.deleted_at::text as deleted_at,
              tl.link_type, tl.created_at::text as linked_at,
              job.id as latest_job_id, job.status as latest_job_status,
              job.queue_name as latest_job_queue, job.error_message as latest_job_error_message,
              pd.id as latest_parsed_document_id, pd.parse_status as latest_parsed_document_status,
              pd.page_count as latest_parsed_document_page_count,
              pd.token_count as latest_parsed_document_token_count,
              pd.error_message as latest_parsed_document_error_message,
              ev.id as latest_evidence_id, ev.text_excerpt as latest_evidence_text_excerpt,
              ev.page_no as latest_evidence_page_no,
              coalesce(evc.evidence_count, 0) as evidence_count
            from target_links tl
            join attachment a on a.id = tl.attachment_id
            left join app_user u on u.id = a.uploaded_by
            left join lateral (
              select id, status, queue_name, error_message
              from background_job
              where team_id = a.team_id
                and workspace_id = a.workspace_id
                and job_type in ('attachment_ocr_parse', 'attachment_ocr_poll')
                and entity_type = 'attachment'
                and entity_id = a.id
              order by created_at desc
              limit 1
            ) job on true
            left join lateral (
              select id, parse_status, page_count, token_count, error_message
              from parsed_document
              where team_id = a.team_id
                and workspace_id = a.workspace_id
                and attachment_id = a.id
              order by created_at desc
              limit 1
            ) pd on true
            left join lateral (
              select id, text_excerpt, page_no
              from evidence_span
              where team_id = a.team_id
                and workspace_id = a.workspace_id
                and attachment_id = a.id
              order by created_at desc
              limit 1
            ) ev on true
            left join lateral (
              select count(*)::int as evidence_count
              from evidence_span
              where team_id = a.team_id
                and workspace_id = a.workspace_id
                and attachment_id = a.id
            ) evc on true
            where a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.deleted_at is null
            order by a.uploaded_at desc
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _attachment_related_business_updates(
    db: Session,
    attachment_ids: list[UUID],
) -> dict[UUID, list[dict[str, Any]]]:
    if not attachment_ids:
        return {}
    rows = db.execute(
        text(
            """
            select
              al.attachment_id, bu.id, bu.processing_status,
              bu.created_at::text as created_at, bu.raw_text
            from attachment_link al
            join business_update bu on bu.id = al.entity_id
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.attachment_id in :attachment_ids
            order by bu.created_at desc
            """
        ).bindparams(bindparam("attachment_ids", expanding=True)),
        {
            "attachment_ids": attachment_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    result: dict[UUID, list[dict[str, Any]]] = {}
    for row in rows:
        attachment_id = row["attachment_id"]
        result.setdefault(attachment_id, []).append(
            {
                "id": row["id"],
                "processing_status": row.get("processing_status"),
                "created_at": row.get("created_at"),
                "raw_text_preview": _truncate_text(row.get("raw_text"), 120),
                "review_route": None,
            }
        )
    return result


def _get_seller_target_attachment_or_404(
    db: Session,
    seller_target_id: UUID,
    attachment_id: UUID,
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              a.id, a.visibility, a.file_name, a.file_type, a.mime_type, a.file_size,
              a.storage_path, a.uploaded_by, a.uploaded_at::text as uploaded_at,
              a.parse_status, a.metadata_json, a.deleted_at::text as deleted_at
            from attachment a
            where a.id = :attachment_id
              and a.team_id = :team_id
              and a.workspace_id = :workspace_id
              and a.deleted_at is null
              and exists (
                select 1
                from attachment_link al
                where al.attachment_id = a.id
                  and al.team_id = a.team_id
                  and al.workspace_id = a.workspace_id
                  and al.entity_type = 'seller_target'
                  and al.entity_id = :seller_target_id
              )
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    return dict(row)


def _compact_target_attachment(
    row: dict[str, Any],
    related_business_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    parse_readiness = _compact_target_attachment_readiness(row)
    display_status = _target_attachment_display_status(row, parse_readiness)
    attachment_id = row["id"]
    seller_target_id = row["seller_target_id"]
    return {
        "id": attachment_id,
        "file_name": row.get("file_name"),
        "file_type": row.get("file_type"),
        "mime_type": row.get("mime_type"),
        "file_size": row.get("file_size"),
        "uploaded_by": row.get("uploaded_by"),
        "uploaded_by_name": row.get("uploaded_by_name"),
        "uploaded_at": row.get("uploaded_at"),
        "link_type": row.get("link_type"),
        "linked_at": row.get("linked_at"),
        "parse_status": row.get("parse_status"),
        "display_status": display_status,
        "parse_readiness": parse_readiness,
        "latest_job": _compact_target_attachment_job(row),
        "latest_parsed_document": _compact_target_attachment_parsed_document(row),
        "latest_evidence": _compact_target_attachment_evidence(row),
        "evidence_count": int(row.get("evidence_count") or 0),
        "related_business_updates": related_business_updates,
        "download_route": (
            f"/seller-targets/{seller_target_id}/attachments/{attachment_id}/download"
        ),
        "delete_route": f"/seller-targets/{seller_target_id}/attachments/{attachment_id}",
        "debug_ref": _debug_ref("attachment", attachment_id),
    }


def _compact_target_attachment_readiness(row: dict[str, Any]) -> dict[str, Any]:
    readiness = _attachment_parse_readiness(row)
    return {key: value for key, value in readiness.items() if key != "attachment"}


def _target_attachment_display_status(row: dict[str, Any], parse_readiness: dict[str, Any]) -> str:
    latest_job_status = str(row.get("latest_job_status") or "")
    parse_status = str(row.get("parse_status") or "")
    parsed_document_status = str(row.get("latest_parsed_document_status") or "")
    evidence_count = int(row.get("evidence_count") or 0)

    if (
        latest_job_status == "failed"
        or parse_status == "failed"
        or parsed_document_status == "failed"
    ):
        return "failed"
    if latest_job_status in {"queued", "running"} or parse_status == "parsing":
        return "parsing"
    if is_supported_multimodal_image(row):
        return "image_evidence"
    if (
        parse_status == "parsed"
        or parsed_document_status == "parsed"
        or evidence_count > 0
        or parse_readiness.get("readiness_status") == "parsed"
    ):
        return "parsed"
    if parse_readiness.get("readiness_status") == "ready":
        return "ready"
    return "pending"


def _compact_target_attachment_job(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("latest_job_id"):
        return None
    return {
        "id": row.get("latest_job_id"),
        "status": row.get("latest_job_status"),
        "queue_name": row.get("latest_job_queue"),
        "error_message": _truncate_text(row.get("latest_job_error_message"), 240),
        "debug_ref": _debug_ref("background_job", row["latest_job_id"]),
    }


def _compact_target_attachment_parsed_document(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("latest_parsed_document_id"):
        return None
    return {
        "id": row.get("latest_parsed_document_id"),
        "parse_status": row.get("latest_parsed_document_status"),
        "page_count": row.get("latest_parsed_document_page_count"),
        "token_count": row.get("latest_parsed_document_token_count"),
        "error_message": _truncate_text(row.get("latest_parsed_document_error_message"), 240),
    }


def _compact_target_attachment_evidence(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("latest_evidence_id"):
        return None
    return {
        "id": row.get("latest_evidence_id"),
        "text_excerpt": _truncate_text(row.get("latest_evidence_text_excerpt"), 500),
        "page_no": row.get("latest_evidence_page_no"),
    }


def _get_seller_target_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select
{SELLER_TARGET_OUT_COLUMNS},
              active_research_job.job_type as research_job_type,
              active_research_job.status as research_job_status
            from seller_target
{ACTIVE_RESEARCH_JOB_LATERAL_SQL}
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

    return _seller_target_out(row)


def _seller_target_params(payload: SellerTargetCreate, current_user: AuthContext) -> dict[str, Any]:
    target_name = payload.target_name.strip()
    target_type = payload.target_type or "company"
    target_subject_name = _normalize_optional_text(payload.target_subject_name)
    # 创建人默认成为负责人；只有管理员可以在创建时指定他人。
    owner_user_id = payload.owner_user_id if current_user.is_admin and payload.owner_user_id else current_user.user_id
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "target_name": target_name,
        "target_type": target_type,
        "target_subject_name": target_subject_name,
        "owner_user_id": owner_user_id,
        "lifecycle_status": payload.lifecycle_status,
        "information_status": payload.information_status,
        "industry_l1": _normalize_optional_text(payload.industry_l1),
        "industry_l2": _normalize_optional_text(payload.industry_l2),
        "industry_pairs_json": payload.industry_pairs_json,
        "location_province": normalize_province(payload.location_province),
        "location_city": normalize_city(payload.location_city),
        "location_district": normalize_district(payload.location_district),
        "listed_status": payload.listed_status,
        "current_revenue_yuan": payload.current_revenue_yuan,
        "current_net_profit_yuan": payload.current_net_profit_yuan,
        "valuation_yuan": payload.valuation_yuan,
        "valuation_date": _normalize_optional_text(payload.valuation_date),
        "asking_price_yuan": payload.asking_price_yuan,
        "asking_price_date": _normalize_optional_text(payload.asking_price_date),
        "pe_ratio": payload.pe_ratio,
        "is_for_sale": payload.is_for_sale,
        "can_control": payload.can_control,
        "can_consolidate": payload.can_consolidate,
        "business_summary": payload.business_summary,
        "transaction_summary": payload.transaction_summary,
        "risk_summary": payload.risk_summary,
        "created_by": current_user.user_id,
        "updated_by": current_user.user_id,
    }


def _seller_target_parse_fallback_text(target: dict[str, Any]) -> str:
    parts = [
        target.get("target_name"),
        target.get("target_subject_name"),
        target.get("business_summary"),
        target.get("transaction_summary"),
        target.get("risk_summary"),
    ]
    return "\n".join(str(part).strip() for part in parts if part is not None and str(part).strip())


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _latest_active_parse_job(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'seller_target_parse'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_job(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, job_type, status, queue_name, entity_type, entity_id,
              error_code, error_message, attempt_count, max_attempts,
              started_at::text as started_at, finished_at::text as finished_at,
              created_at::text as created_at, updated_at::text as updated_at,
              result_json, metadata_json
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'seller_target_parse'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_trace(db: Session, seller_target_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, trace_type, node_name, job_id, provider_name, model_name,
              prompt_version, status, raw_output_text, parsed_output_json,
              schema_validation_json, error_code, error_message,
              latency_ms, prompt_tokens, completion_tokens, total_tokens,
              started_at::text as started_at, finished_at::text as finished_at
            from ai_trace
            where team_id = :team_id
              and workspace_id = :workspace_id
              and node_name = 'seller_target_parser'
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
            order by started_at desc
            limit 1
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _recent_parse_update_logs(db: Session, seller_target_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, field_path, old_value_json, new_value_json, source_type, source_id,
              applied_at::text as applied_at, can_rollback, rollback_at::text as rollback_at
            from action_application_log
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'seller_target'
              and entity_id = :seller_target_id
              and source_type = 'seller_target_parse'
            order by applied_at desc
            limit 50
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _compact_parse_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "job_type": job["job_type"],
        "status": job["status"],
        "queue_name": job["queue_name"],
        "error_code": job.get("error_code"),
        "error_message": job.get("error_message"),
        "attempt_count": job.get("attempt_count"),
        "max_attempts": job.get("max_attempts"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "result_json": job.get("result_json"),
        "debug_ref": _debug_ref("background_job", job["id"]),
    }


def _compact_parse_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": trace["id"],
        "trace_type": trace["trace_type"],
        "node_name": trace["node_name"],
        "job_id": trace.get("job_id"),
        "provider_name": trace.get("provider_name"),
        "model_name": trace.get("model_name"),
        "prompt_version": trace.get("prompt_version"),
        "status": trace["status"],
        "raw_output_preview": _truncate_text(trace.get("raw_output_text"), 800),
        "parsed_output_json": trace.get("parsed_output_json"),
        "schema_validation_json": trace.get("schema_validation_json"),
        "error_code": trace.get("error_code"),
        "error_message": trace.get("error_message"),
        "latency_ms": trace.get("latency_ms"),
        "prompt_tokens": trace.get("prompt_tokens"),
        "completion_tokens": trace.get("completion_tokens"),
        "total_tokens": trace.get("total_tokens"),
        "started_at": trace.get("started_at"),
        "finished_at": trace.get("finished_at"),
        "debug_ref": _debug_ref("background_job", trace["job_id"]) if trace.get("job_id") else None,
    }


def _debug_ref(entity_type: str, entity_id: Any) -> dict[str, str]:
    entity_id_text = str(entity_id)
    return {
        "entity_type": entity_type,
        "entity_id": entity_id_text,
        "route": f"/debug/entities/{entity_type}/{entity_id_text}",
    }


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."
