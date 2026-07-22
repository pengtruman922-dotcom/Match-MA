from datetime import date
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
from backend.app.services.attachment_storage import (
    AttachmentNotFoundError,
    AttachmentStorageError,
    AttachmentTooLargeError,
    read_attachment_bytes,
)
from backend.app.services.image_inputs import is_supported_multimodal_image
from backend.app.services.search_docs import create_search_doc_rebuild_job

router = APIRouter(prefix="/seller-targets", tags=["seller-targets"])


class SellerTargetCreate(BaseModel):
    target_name: str = Field(min_length=1, max_length=300)
    target_type: str = "company"
    target_subject_name: str | None = Field(default=None, max_length=300)
    owner_user_id: UUID | None = None
    lifecycle_status: Literal["active", "sold", "off_market"] = "active"
    recommendation_status: Literal["recommendable", "not_recommendable"] = "not_recommendable"
    information_status: Literal[
        "normal",
        "insufficient",
        "pending_review",
        "parsing",
        "researching",
        "parse_failed",
    ] = "pending_review"
    industry_primary: str | None = None
    industry_secondary: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
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
    recommendation_status: str
    information_status: str
    industry_l1: str | None = None
    industry_l2: str | None = None
    industry_primary: str | None
    industry_secondary: str | None
    registered_province: str | None
    registered_city: str | None
    headquarter_province: str | None
    headquarter_city: str | None
    raw_region_text: str | None
    region_granularity: str | None
    listed_status: str
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
    operation_stability_status: str | None
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
    transfer_flexibility_type: str | None
    consolidation_path_summary: str | None
    accepts_relocation: str
    accepts_return_investment: str
    management_team_summary: str | None
    management_retention_possible: str
    earnout_dependency_status: str | None
    business_summary: str | None
    transaction_summary: str | None
    risk_summary: str | None
    gap_summary: str | None
    owner_user_id: UUID | None = None
    owner_name: str | None = None
    # 调研节流靠界面二次确认，不靠服务端静默跳过，所以列表也要带上最近调研时间。
    last_research_at: str | None = None
    research_last_outcome: str | None = None
    created_at: str
    updated_at: str
    latest_follow_up_on: str | None = None
    latest_follow_up_content: str | None = None


class SellerTargetListOut(BaseModel):
    items: list[SellerTargetOut]
    total: int
    limit: int
    offset: int


class SellerTargetUpdate(BaseModel):
    target_name: str | None = Field(default=None, min_length=1, max_length=300)
    target_type: str | None = None
    target_subject_name: str | None = Field(default=None, max_length=300)
    industry_primary: str | None = None
    industry_secondary: str | None = None
    registered_province: str | None = None
    registered_city: str | None = None
    headquarter_province: str | None = None
    headquarter_city: str | None = None
    raw_region_text: str | None = None
    region_granularity: str | None = None
    listed_status: str | None = None
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
    operation_stability_status: str | None = None
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
    transfer_flexibility_type: str | None = None
    consolidation_path_summary: str | None = None
    accepts_relocation: str | None = None
    accepts_return_investment: str | None = None
    management_team_summary: str | None = None
    management_retention_possible: str | None = None
    earnout_dependency_status: str | None = None
    lifecycle_status: Literal["active", "sold", "off_market"] | None = None
    recommendation_status: str | None = None
    information_status: str | None = None
    business_summary: str | None = None
    transaction_summary: str | None = None
    risk_summary: str | None = None
    gap_summary: str | None = None
    owner_user_id: UUID | None = None


class SellerTargetParseRequest(BaseModel):
    raw_target_text: str | None = Field(default=None, min_length=1)
    force: bool = False


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


class SellerTargetFilterOptionsOut(BaseModel):
    industries: list[SellerTargetFilterOptionOut]
    regions: list[SellerTargetFilterOptionOut]
    statuses: list[SellerTargetFilterOptionOut]
    recommendation_statuses: list[SellerTargetFilterOptionOut] = []
    parse_statuses: list[SellerTargetFilterOptionOut] = []
    owners: list[SellerTargetFilterOptionOut] = []


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


class TargetFollowUpCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    occurred_on: date | None = None
    related_buyer_party_ids: list[UUID] = Field(default_factory=list, max_length=20)


class TargetFollowUpBuyerRef(BaseModel):
    id: UUID
    buyer_name: str


class TargetFollowUpOut(BaseModel):
    id: UUID
    seller_target_id: UUID
    occurred_on: str
    content: str
    related_buyer_parties: list[TargetFollowUpBuyerRef]
    created_at: str


SELLER_TARGET_OUT_COLUMNS = """
              id, target_name, target_type, target_subject_name, lifecycle_status, recommendation_status, information_status,
              industry_l1, industry_l2, industry_primary, industry_secondary, registered_province, registered_city,
              headquarter_province, headquarter_city, raw_region_text, region_granularity,
              listed_status, listing_market_region, market_cap_yuan, current_revenue_yuan, current_net_profit_yuan,
              current_total_profit_yuan, current_assets_yuan, current_debt_ratio,
              current_operating_cash_flow_yuan, financial_period_label, profitability_status,
              cash_flow_status, operation_stability_status, valuation_yuan, valuation_date,
              asking_price_yuan, asking_price_date,
              pe_ratio, pe_source_type, premium_rate, is_for_sale, can_control, can_consolidate,
              accepts_minority_investment, transfer_ratio_min, transfer_ratio_max, transfer_ratio_text,
              transfer_flexibility_type, consolidation_path_summary, accepts_relocation,
              accepts_return_investment, management_team_summary, management_retention_possible,
              earnout_dependency_status, business_summary, transaction_summary, risk_summary, gap_summary,
              owner_user_id,
              (select au.name from app_user au where au.id = seller_target.owner_user_id) as owner_name,
              last_research_at::text as last_research_at, research_last_outcome,
              created_at::text as created_at, updated_at::text as updated_at
"""

# Single user-facing "status" derived from three orthogonal stored statuses:
# parse lifecycle beats deal lifecycle beats recommendability, so the UI can
# render one column while the database stays conflict-free.
SELLER_TARGET_DISPLAY_STATUS_SQL = """
              case
                when information_status in ('parsing', 'researching') then 'parsing'
                when information_status = 'parse_failed' then 'parse_failed'
                when lifecycle_status = 'sold' then 'sold'
                when lifecycle_status = 'off_market' then 'off_market'
                when recommendation_status = 'recommendable' then 'recommendable'
                else 'not_recommendable'
              end
"""

SELLER_TARGET_DISPLAY_STATUS_LABELS = {
    "parsing": "解析中",
    "parse_failed": "解析失败",
    "sold": "已售出",
    "off_market": "已停售",
    "recommendable": "可推荐",
    "not_recommendable": "暂不可推荐",
}


@router.post("", response_model=SellerTargetOut, status_code=status.HTTP_201_CREATED)
def create_seller_target(
    payload: SellerTargetCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            insert into seller_target (
              team_id, workspace_id, target_name, target_type, target_subject_name, owner_user_id,
              lifecycle_status, recommendation_status, information_status,
              industry_primary, industry_secondary, headquarter_province, headquarter_city,
              listed_status, current_revenue_yuan, current_net_profit_yuan,
              valuation_yuan, valuation_date, asking_price_yuan, asking_price_date, pe_ratio,
              is_for_sale, can_control, can_consolidate,
              business_summary, transaction_summary, risk_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :target_name, :target_type, :target_subject_name, :owner_user_id,
              :lifecycle_status, :recommendation_status, :information_status,
              :industry_primary, :industry_secondary, :headquarter_province, :headquarter_city,
              :listed_status, :current_revenue_yuan, :current_net_profit_yuan,
              :valuation_yuan, :valuation_date, :asking_price_yuan, :asking_price_date, :pe_ratio,
              :is_for_sale, :can_control, :can_consolidate,
              :business_summary, :transaction_summary, :risk_summary,
              :created_by, :updated_by
            )
            returning
{SELLER_TARGET_OUT_COLUMNS}
            """
        ),
        _seller_target_params(payload, current_user),
    ).mappings().one()
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=row["id"],
        source="seller_target_create",
    )
    db.commit()
    return dict(row)


SELLER_TARGET_SEARCH_COLUMNS = {
    "target_name": "target_name",
    "target_subject_name": "target_subject_name",
    "business_summary": "business_summary",
}


@router.get("", response_model=SellerTargetListOut)
def list_seller_targets(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    search_field: Literal["target_name", "target_subject_name", "business_summary"] | None = Query(default=None),
    industry: str | None = Query(default=None, max_length=200),
    region: str | None = Query(default=None, max_length=200),
    status: Literal[
        "recommendable",
        "not_recommendable",
        "parsing",
        "parse_failed",
        "sold",
        "off_market",
    ] | None = Query(default=None),
    recommendation_status: Literal["recommendable", "sold", "off_market"] | None = Query(default=None),
    parse_status: Literal["parsing", "parse_failed", "parsed"] | None = Query(default=None),
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

    if q:
        if search_field:
            where.append(f"{SELLER_TARGET_SEARCH_COLUMNS[search_field]} ilike :q")
        else:
            where.append("(target_name ilike :q or target_subject_name ilike :q or business_summary ilike :q)")
        params["q"] = f"%{q}%"
    if industry:
        where.append(
            "concat_ws(' / ', nullif(industry_primary, ''), nullif(industry_secondary, '')) = :industry"
        )
        params["industry"] = industry
    if region:
        where.append(
            "concat_ws(' ', nullif(headquarter_province, ''), nullif(headquarter_city, '')) = :region"
        )
        params["region"] = region
    if status:
        where.append(f"({SELLER_TARGET_DISPLAY_STATUS_SQL}) = :status")
        params["status"] = status
    if recommendation_status:
        if recommendation_status in {"sold", "off_market"}:
            where.append("lifecycle_status = :recommendation_status")
        else:
            where.append("lifecycle_status = 'active' and recommendation_status = 'recommendable'")
        params["recommendation_status"] = recommendation_status
    if parse_status:
        if parse_status == "parsing":
            where.append("information_status in ('parsing', 'researching')")
        elif parse_status == "parse_failed":
            where.append("information_status = 'parse_failed'")
        else:
            where.append("information_status not in ('parsing', 'researching', 'parse_failed')")

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
              lf.occurred_on::text as latest_follow_up_on,
              lf.content as latest_follow_up_content
            from seller_target
            left join lateral (
              select f.occurred_on, f.content
              from target_follow_up f
              where f.seller_target_id = seller_target.id
                and f.deleted_at is null
              order by f.occurred_on desc, f.created_at desc
              limit 1
            ) lf on true
            where {where_sql}
            order by updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options", response_model=SellerTargetFilterOptionsOut)
def seller_target_filter_options(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    scope_clause = ""
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        scope_clause = "and owner_user_id = :scope_user_id"
    industries = _filter_options(
        db,
        f"""
        select
          concat_ws(' / ', nullif(industry_primary, ''), nullif(industry_secondary, '')) as value,
          count(*) as count
        from seller_target
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
          and concat_ws(' / ', nullif(industry_primary, ''), nullif(industry_secondary, '')) <> ''
        group by value
        order by count desc, value asc
        limit 80
        """,
        params,
    )
    regions = _filter_options(
        db,
        f"""
        select
          concat_ws(' ', nullif(headquarter_province, ''), nullif(headquarter_city, '')) as value,
          count(*) as count
        from seller_target
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
          and concat_ws(' ', nullif(headquarter_province, ''), nullif(headquarter_city, '')) <> ''
        group by value
        order by count desc, value asc
        limit 80
        """,
        params,
    )
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
    recommendation_statuses = _filter_options(
        db,
        f"""
        select
          case
            when lifecycle_status = 'sold' then 'sold'
            when lifecycle_status = 'off_market' then 'off_market'
            when lifecycle_status = 'active' and recommendation_status = 'recommendable' then 'recommendable'
            else null
          end as value,
          count(*) as count
        from seller_target
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by value
        order by count desc, value asc
        """,
        params,
        labels={"recommendable": "可推荐", "sold": "已售出", "off_market": "已停售"},
    )
    parse_statuses = _filter_options(
        db,
        f"""
        select
          case
            when information_status in ('parsing', 'researching') then 'parsing'
            when information_status = 'parse_failed' then 'parse_failed'
            else 'parsed'
          end as value,
          count(*) as count
        from seller_target
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by value
        order by count desc, value asc
        """,
        params,
        labels={"parsing": "解析中", "parse_failed": "解析失败", "parsed": "已解析"},
    )
    owners = [] if owner_scope_required(current_user) else owner_filter_options(db, "seller_target", params)
    return {
        "industries": industries,
        "regions": regions,
        "statuses": statuses,
        "recommendation_statuses": recommendation_statuses,
        "parse_statuses": parse_statuses,
        "owners": owners,
    }


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
    require_admin(current_user)
    target_ids = list(dict.fromkeys(payload.ids))
    deleted_ids = _soft_delete_seller_targets(db, target_ids, actor_user_id=current_user.user_id)
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


@router.get("/{seller_target_id}/follow-ups", response_model=list[TargetFollowUpOut])
def list_target_follow_ups(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_visible(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    rows = db.execute(
        text(
            """
            select
              id, seller_target_id, occurred_on::text as occurred_on, content,
              related_buyer_party_ids_json, created_at::text as created_at
            from target_follow_up
            where team_id = :team_id
              and workspace_id = :workspace_id
              and seller_target_id = :seller_target_id
              and deleted_at is null
            order by occurred_on desc, created_at desc
            limit :limit
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": seller_target_id,
            "limit": limit,
        },
    ).mappings().all()
    return _follow_ups_with_buyer_refs(db, [dict(row) for row in rows])


@router.post(
    "/{seller_target_id}/follow-ups",
    response_model=TargetFollowUpOut,
    status_code=status.HTTP_201_CREATED,
)
def create_target_follow_up(
    seller_target_id: UUID,
    payload: TargetFollowUpCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_seller_target_or_404(db, seller_target_id)
    ensure_entity_writable(db, current_user, entity_type="seller_target", entity_id=seller_target_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="content is required.")
    related_ids = [str(party_id) for party_id in dict.fromkeys(payload.related_buyer_party_ids)]
    row = db.execute(
        text(
            """
            insert into target_follow_up (
              team_id, workspace_id, seller_target_id, occurred_on, content,
              related_buyer_party_ids_json, created_by
            )
            values (
              :team_id, :workspace_id, :seller_target_id,
              coalesce(:occurred_on, current_date), :content,
              :related_buyer_party_ids_json, :created_by
            )
            returning
              id, seller_target_id, occurred_on::text as occurred_on, content,
              related_buyer_party_ids_json, created_at::text as created_at
            """
        ).bindparams(bindparam("related_buyer_party_ids_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": seller_target_id,
            "occurred_on": payload.occurred_on,
            "content": content,
            "related_buyer_party_ids_json": related_ids,
            "created_by": current_user.user_id,
        },
    ).mappings().one()
    db.commit()
    return _follow_ups_with_buyer_refs(db, [dict(row)])[0]


@router.delete("/{seller_target_id}/follow-ups/{follow_up_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target_follow_up(
    seller_target_id: UUID,
    follow_up_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    # 跟进记录允许"管理员或标的负责人"删除（软删除，仅影响这一条记录）。
    target = _get_seller_target_or_404(db, seller_target_id)
    if not current_user.is_admin and target.get("owner_user_id") != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员或标的负责人可删除跟进记录。")
    result = db.execute(
        text(
            """
            update target_follow_up
            set deleted_at = now(), deleted_by = :deleted_by
            where id = :follow_up_id
              and seller_target_id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "follow_up_id": follow_up_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "deleted_by": current_user.user_id,
        },
    )
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Follow-up not found.")
    db.commit()
    return None


def _follow_ups_with_buyer_refs(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    party_ids: list[UUID] = []
    for row in rows:
        for raw_id in row.get("related_buyer_party_ids_json") or []:
            try:
                party_ids.append(UUID(str(raw_id)))
            except (TypeError, ValueError):
                continue
    name_map: dict[str, str] = {}
    if party_ids:
        buyer_rows = db.execute(
            text(
                """
                select id, buyer_name
                from buyer_party
                where team_id = :team_id
                  and workspace_id = :workspace_id
                  and id = any(:party_ids)
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "party_ids": list(dict.fromkeys(party_ids)),
            },
        ).mappings().all()
        name_map = {str(buyer["id"]): buyer["buyer_name"] for buyer in buyer_rows}

    results: list[dict[str, Any]] = []
    for row in rows:
        related = [
            {"id": raw_id, "buyer_name": name_map[str(raw_id)]}
            for raw_id in (row.get("related_buyer_party_ids_json") or [])
            if str(raw_id) in name_map
        ]
        results.append(
            {
                "id": row["id"],
                "seller_target_id": row["seller_target_id"],
                "occurred_on": row["occurred_on"],
                "content": row["content"],
                "related_buyer_parties": related,
                "created_at": row["created_at"],
            }
        )
    return results


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
    return dict(row)


@router.delete("/{seller_target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_seller_target(
    seller_target_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    require_admin(current_user)
    _get_seller_target_or_404(db, seller_target_id)
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
) -> list[UUID]:
    if not seller_target_ids:
        return []
    actor = actor_user_id or DEFAULT_ADMIN_USER_ID

    rows = db.execute(
        text(
            """
            update seller_target
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id in :seller_target_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning id
            """
        ).bindparams(bindparam("seller_target_ids", expanding=True)),
        {
            "deleted_by": actor,
            "updated_by": actor,
            "seller_target_ids": seller_target_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
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
{SELLER_TARGET_OUT_COLUMNS}
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
        "recommendation_status": payload.recommendation_status,
        "information_status": payload.information_status,
        "industry_primary": _normalize_optional_text(payload.industry_primary),
        "industry_secondary": _normalize_optional_text(payload.industry_secondary),
        "headquarter_province": _normalize_optional_text(payload.headquarter_province),
        "headquarter_city": _normalize_optional_text(payload.headquarter_city),
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
