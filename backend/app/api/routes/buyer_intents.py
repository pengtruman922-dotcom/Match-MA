from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.authn import AuthContext, CurrentUser, require_admin
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
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
    owner_scope_sql,
    write_action_log,
    write_action_logs_for_diff,
)
from backend.app.db import get_db
from backend.app.registry.nodes import buyer_parse_node_names
from backend.app.services.recommendation_conditions import normalize_condition_effects, normalize_scenario_fields
from backend.app.services.search_docs import create_search_doc_rebuild_job
from backend.app.services.buyer_intent_processing_state import buyer_intent_processing_states

router = APIRouter(prefix="/buyer-intents", tags=["buyer-intents"])

YesNoRequirement = Literal["yes", "no", "unknown", "likely"]
RequirementStrength = Literal["required", "preferred", "not_required", "unknown"]
EquityRequirementType = Literal[
    "control_required",
    "consolidation_required",
    "minority_acceptable",
    "minority_only",
    "flexible",
    "specific_range",
    "unknown",
]
ListedStatusRequirement = Literal["listed", "unlisted", "pre_ipo", "preparing_listing", "any", "unknown"]
ListingMarketRegion = Literal["domestic", "overseas", "unknown"]


class BuyerIntentCreate(BaseModel):
    intent_name: str = Field(min_length=1, max_length=300)
    buyer_party_id: UUID | None = None
    owner_user_id: UUID | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    industries_json: list[Any] | None = None
    industry_l2_json: list[Any] | None = None
    excluded_industries_json: list[Any] | None = None
    industry_focus_tags_json: list[Any] | None = None
    region_scope_summary: str | None = None
    parsed_requirement_json: dict[str, Any] | None = None
    region_constraints_json: list[Any] | dict[str, Any] | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    min_total_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_ps: Decimal | None = None
    min_net_margin: Decimal | None = None
    min_gross_margin: Decimal | None = None
    min_valuation_yuan: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    min_market_cap_yuan: Decimal | None = None
    max_market_cap_yuan: Decimal | None = None
    market_cap_range_summary: str | None = None
    requires_control: YesNoRequirement = "unknown"
    requires_consolidation: YesNoRequirement = "unknown"
    accepts_minority_investment: YesNoRequirement = "unknown"
    desired_equity_ratio_min: Decimal | None = None
    desired_equity_ratio_max: Decimal | None = None
    equity_ratio_summary: str | None = None
    equity_requirement_type: EquityRequirementType | None = None
    acceptable_control_paths_json: list[Any] | dict[str, Any] | None = None
    preferred_listed_status: ListedStatusRequirement | None = "unknown"
    acceptable_listed_status_json: list[Any] | None = None
    condition_effects_json: dict[str, Any] | None = None
    listing_board_requirement_summary: str | None = None
    financing_stage_requirement_summary: str | None = None
    transaction_type: str | None = None
    transaction_types_json: list[Any] | dict[str, Any] | None = None
    premium_tolerance_summary: str | None = None
    max_premium_rate: Decimal | None = None
    max_debt_ratio: Decimal | None = None
    debt_ratio_requirement_summary: str | None = None
    major_risk_tolerance_summary: str | None = None
    buyer_industry_advantage_summary: str | None = None
    acceptable_cash_flow_status_json: list[Any] | None = None
    acceptable_profitability_status_json: list[Any] | None = None
    requires_relocation: RequirementStrength = "unknown"
    relocation_target_regions_json: list[Any] | None = None
    requires_return_investment: RequirementStrength = "unknown"
    return_investment_multiple: Decimal | None = None
    requires_team_retention: RequirementStrength = "unknown"
    earnout_requirement: RequirementStrength = "unknown"
    listing_market_region: ListingMarketRegion | None = None
    budget_min_yuan: Decimal | None = None
    budget_max_yuan: Decimal | None = None
    needs_confirmation_json: list[Any] | None = None
    negative_summary: str | None = None
    priority_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None

    @field_validator("equity_requirement_type", "listing_market_region", mode="before")
    @classmethod
    def normalize_nullable_enum(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class BuyerIntentOut(BaseModel):
    id: UUID
    buyer_party_id: UUID | None
    buyer_name: str | None = None
    intent_name: str
    status: str
    contact_name: str | None
    raw_requirement_text: str | None
    intent_summary: str | None
    industry_primary: str | None
    industry_secondary: str | None
    industries_json: list[Any] = []
    industry_l2_json: list[Any] = []
    excluded_industries_json: list[Any] = []
    industry_focus_tags_json: list[Any] = []
    region_scope_summary: str | None
    parsed_requirement_json: dict[str, Any]
    region_constraints_json: list[Any] | dict[str, Any]
    min_revenue_yuan: Decimal | None
    min_net_profit_yuan: Decimal | None
    min_total_profit_yuan: Decimal | None
    max_pe: Decimal | None
    max_ps: Decimal | None
    min_net_margin: Decimal | None
    min_gross_margin: Decimal | None
    min_valuation_yuan: Decimal | None
    max_valuation_yuan: Decimal | None
    min_market_cap_yuan: Decimal | None
    max_market_cap_yuan: Decimal | None
    market_cap_range_summary: str | None
    requires_control: str
    requires_consolidation: str
    accepts_minority_investment: str
    desired_equity_ratio_min: Decimal | None
    desired_equity_ratio_max: Decimal | None
    equity_ratio_summary: str | None
    equity_requirement_type: str | None
    acceptable_control_paths_json: list[Any] | dict[str, Any]
    preferred_listed_status: str | None
    acceptable_listed_status_json: list[Any] = []
    condition_effects_json: dict[str, Any] = {}
    listing_board_requirement_summary: str | None
    financing_stage_requirement_summary: str | None
    transaction_type: str | None
    transaction_types_json: list[Any] | dict[str, Any]
    premium_tolerance_summary: str | None
    max_premium_rate: Decimal | None
    max_debt_ratio: Decimal | None
    debt_ratio_requirement_summary: str | None
    major_risk_tolerance_summary: str | None
    buyer_industry_advantage_summary: str | None
    acceptable_cash_flow_status_json: list[Any] = []
    acceptable_profitability_status_json: list[Any] = []
    requires_relocation: str
    relocation_target_regions_json: list[Any] = []
    requires_return_investment: str
    return_investment_multiple: Decimal | None
    requires_team_retention: str
    earnout_requirement: str
    listing_market_region: str | None
    budget_min_yuan: Decimal | None
    budget_max_yuan: Decimal | None
    needs_confirmation_json: list[Any] = []
    reviewed_at: str | None = None
    reviewed_by: UUID | None = None
    negative_summary: str | None
    priority_summary: str | None
    preference_summary: str | None
    unknown_summary: str | None
    owner_user_id: UUID | None = None
    owner_name: str | None = None
    scenario_labels: list[str] = []
    created_at: str
    updated_at: str
    processing_state: dict[str, Any] | None = None


class BuyerIntentListOut(BaseModel):
    items: list[BuyerIntentOut]
    total: int
    limit: int
    offset: int


class BuyerIntentUpdate(BaseModel):
    intent_name: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["active", "paused", "closed"] | None = None
    pause_reason: str | None = None
    contact_name: str | None = None
    raw_requirement_text: str | None = None
    intent_summary: str | None = None
    industry_primary: str | None = None
    industry_secondary: str | None = None
    industries_json: list[Any] | None = None
    industry_l2_json: list[Any] | None = None
    excluded_industries_json: list[Any] | None = None
    industry_focus_tags_json: list[Any] | None = None
    region_scope_summary: str | None = None
    parsed_requirement_json: dict[str, Any] | None = None
    region_constraints_json: list[Any] | dict[str, Any] | None = None
    min_revenue_yuan: Decimal | None = None
    min_net_profit_yuan: Decimal | None = None
    min_total_profit_yuan: Decimal | None = None
    max_pe: Decimal | None = None
    max_ps: Decimal | None = None
    min_net_margin: Decimal | None = None
    min_gross_margin: Decimal | None = None
    min_valuation_yuan: Decimal | None = None
    max_valuation_yuan: Decimal | None = None
    min_market_cap_yuan: Decimal | None = None
    max_market_cap_yuan: Decimal | None = None
    market_cap_range_summary: str | None = None
    requires_control: YesNoRequirement | None = None
    requires_consolidation: YesNoRequirement | None = None
    accepts_minority_investment: YesNoRequirement | None = None
    desired_equity_ratio_min: Decimal | None = None
    desired_equity_ratio_max: Decimal | None = None
    equity_ratio_summary: str | None = None
    equity_requirement_type: EquityRequirementType | None = None
    acceptable_control_paths_json: list[Any] | dict[str, Any] | None = None
    preferred_listed_status: ListedStatusRequirement | None = None
    acceptable_listed_status_json: list[Any] | None = None
    condition_effects_json: dict[str, Any] | None = None
    listing_board_requirement_summary: str | None = None
    financing_stage_requirement_summary: str | None = None
    transaction_type: str | None = None
    transaction_types_json: list[Any] | dict[str, Any] | None = None
    premium_tolerance_summary: str | None = None
    max_premium_rate: Decimal | None = None
    max_debt_ratio: Decimal | None = None
    debt_ratio_requirement_summary: str | None = None
    major_risk_tolerance_summary: str | None = None
    buyer_industry_advantage_summary: str | None = None
    acceptable_cash_flow_status_json: list[Any] | None = None
    acceptable_profitability_status_json: list[Any] | None = None
    requires_relocation: RequirementStrength | None = None
    relocation_target_regions_json: list[Any] | None = None
    requires_return_investment: RequirementStrength | None = None
    return_investment_multiple: Decimal | None = None
    requires_team_retention: RequirementStrength | None = None
    earnout_requirement: RequirementStrength | None = None
    listing_market_region: ListingMarketRegion | None = None
    budget_min_yuan: Decimal | None = None
    budget_max_yuan: Decimal | None = None
    needs_confirmation_json: list[Any] | None = None
    negative_summary: str | None = None
    priority_summary: str | None = None
    preference_summary: str | None = None
    unknown_summary: str | None = None
    owner_user_id: UUID | None = None

    @field_validator("equity_requirement_type", "listing_market_region", mode="before")
    @classmethod
    def normalize_nullable_enum(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class BuyerIntentParseRequest(BaseModel):
    raw_requirement_text: str | None = Field(default=None, min_length=1)
    force: bool = False


class BuyerIntentReviewRequest(BaseModel):
    clear_confirmations: bool = False


class BuyerIntentParseJobOut(BaseModel):
    job_id: UUID
    job_type: str
    status: str
    queue_name: str
    buyer_intent_id: UUID


class BuyerIntentParseStatusOut(BaseModel):
    buyer_intent: dict[str, Any]
    processing_state: dict[str, Any]
    latest_job: dict[str, Any] | None
    latest_trace: dict[str, Any] | None
    recent_update_logs: list[dict[str, Any]]
    debug_ref: dict[str, Any]


class BuyerIntentFilterOptionOut(BaseModel):
    value: str
    label: str
    count: int


class BuyerIntentFilterOptionsOut(BaseModel):
    industries: list[BuyerIntentFilterOptionOut]
    regions: list[BuyerIntentFilterOptionOut]
    statuses: list[BuyerIntentFilterOptionOut]
    listed_statuses: list[BuyerIntentFilterOptionOut]
    consolidation_requirements: list[BuyerIntentFilterOptionOut]
    owners: list[BuyerIntentFilterOptionOut] = []


class BuyerIntentSuggestionOut(BaseModel):
    id: UUID
    search_field: Literal["intent_name", "buyer_name", "raw_requirement_text", "intent_summary"]
    match_type: Literal["intent", "buyer", "requirement", "summary"]
    match_label: str
    match_text: str
    intent_name: str
    buyer_party_id: UUID | None
    buyer_name: str | None
    snippet: str | None


class BuyerIntentBulkDeleteRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class BuyerIntentBulkDeleteOut(BaseModel):
    status: str
    deleted_count: int
    deleted_ids: list[UUID]
    skipped_ids: list[UUID]


# jsonb 展开前的防御性收敛：列里存了非数组时 jsonb_array_elements* 会在运行时报错，
# 用它兜成空数组，避免单条脏数据把整个列表或筛选项接口打成 500。
_JSONB_ARRAY = "case when jsonb_typeof({column}) = 'array' then {column} else '[]'::jsonb end"


BUYER_INTENT_OUT_COLUMNS = """
              bi.id, bi.buyer_party_id, bp.buyer_name as buyer_name, bi.intent_name, bi.status, bi.contact_name,
              bi.raw_requirement_text, bi.intent_summary, bi.parsed_requirement_json,
              bi.industry_primary, bi.industry_secondary,
              bi.industries_json, bi.industry_l2_json,
              bi.excluded_industries_json, bi.industry_focus_tags_json,
              bi.region_scope_summary,
              bi.region_constraints_json, bi.min_revenue_yuan, bi.min_net_profit_yuan,
              bi.min_total_profit_yuan, bi.max_pe, bi.max_ps,
              bi.min_net_margin, bi.min_gross_margin,
              bi.min_valuation_yuan, bi.max_valuation_yuan,
              bi.min_market_cap_yuan, bi.max_market_cap_yuan, bi.market_cap_range_summary,
              bi.requires_control, bi.requires_consolidation,
              bi.accepts_minority_investment, bi.desired_equity_ratio_min,
              bi.desired_equity_ratio_max, bi.equity_ratio_summary, bi.equity_requirement_type,
              bi.acceptable_control_paths_json, bi.preferred_listed_status,
              bi.acceptable_listed_status_json, bi.condition_effects_json,
              bi.listing_board_requirement_summary, bi.financing_stage_requirement_summary,
              bi.transaction_type, bi.transaction_types_json, bi.premium_tolerance_summary,
              bi.max_premium_rate, bi.max_debt_ratio, bi.debt_ratio_requirement_summary,
              bi.major_risk_tolerance_summary, bi.buyer_industry_advantage_summary,
              bi.acceptable_cash_flow_status_json, bi.acceptable_profitability_status_json,
              bi.requires_relocation, bi.relocation_target_regions_json,
              bi.requires_return_investment, bi.return_investment_multiple,
              bi.requires_team_retention, bi.earnout_requirement,
              bi.listing_market_region, bi.budget_min_yuan, bi.budget_max_yuan,
              bi.needs_confirmation_json, bi.reviewed_at::text as reviewed_at, bi.reviewed_by,
              bi.negative_summary, bi.priority_summary, bi.preference_summary, bi.unknown_summary,
              bi.owner_user_id,
              (select au.name from app_user au where au.id = bi.owner_user_id) as owner_name,
              (select coalesce(jsonb_agg(s.label order by s.sort_order, s.created_at), '[]'::jsonb)
                 from buyer_intent_scenario s
                where s.buyer_intent_id = bi.id
                  and s.team_id = bi.team_id
                  and s.workspace_id = bi.workspace_id
                  and s.active
                  and s.deleted_at is null) as scenario_labels,
              bi.created_at::text as created_at, bi.updated_at::text as updated_at
"""


BUYER_INTENT_SEARCH_COLUMNS = {
    "intent_name": "bi.intent_name",
    "buyer_name": "bp.buyer_name",
    "raw_requirement_text": "bi.raw_requirement_text",
    "intent_summary": "bi.intent_summary",
}


@router.post("", response_model=BuyerIntentOut, status_code=status.HTTP_201_CREATED)
def create_buyer_intent(
    payload: BuyerIntentCreate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.buyer_party_id is not None:
        ensure_entity_writable(db, current_user, entity_type="buyer_party", entity_id=payload.buyer_party_id)
    row = db.execute(
        text(
            """
            insert into buyer_intent (
              team_id, workspace_id, buyer_party_id, owner_user_id,
              intent_name, contact_name, raw_requirement_text, intent_summary,
              parsed_requirement_json, industry_primary, industry_secondary,
              industries_json, industry_l2_json, excluded_industries_json, industry_focus_tags_json,
              region_scope_summary, region_constraints_json,
              min_revenue_yuan, min_net_profit_yuan, min_total_profit_yuan,
              max_pe, max_ps, min_net_margin, min_gross_margin,
              min_valuation_yuan, max_valuation_yuan,
              min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, acceptable_listed_status_json, condition_effects_json,
              listing_board_requirement_summary,
              financing_stage_requirement_summary, transaction_type, transaction_types_json,
              premium_tolerance_summary, max_premium_rate, max_debt_ratio,
              debt_ratio_requirement_summary, major_risk_tolerance_summary,
              buyer_industry_advantage_summary,
              acceptable_cash_flow_status_json, acceptable_profitability_status_json,
              requires_relocation, relocation_target_regions_json,
              requires_return_investment, return_investment_multiple,
              requires_team_retention, earnout_requirement, listing_market_region,
              budget_min_yuan, budget_max_yuan, needs_confirmation_json,
              negative_summary, priority_summary,
              preference_summary, unknown_summary,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :buyer_party_id, :owner_user_id,
              :intent_name, :contact_name, :raw_requirement_text, :intent_summary,
              :parsed_requirement_json, :industry_primary, :industry_secondary,
              :industries_json, :industry_l2_json, :excluded_industries_json, :industry_focus_tags_json,
              :region_scope_summary, :region_constraints_json,
              :min_revenue_yuan, :min_net_profit_yuan, :min_total_profit_yuan,
              :max_pe, :max_ps, :min_net_margin, :min_gross_margin,
              :min_valuation_yuan, :max_valuation_yuan,
              :min_market_cap_yuan, :max_market_cap_yuan, :market_cap_range_summary,
              :requires_control, :requires_consolidation, :accepts_minority_investment,
              :desired_equity_ratio_min, :desired_equity_ratio_max, :equity_ratio_summary,
              :equity_requirement_type, :acceptable_control_paths_json,
              :preferred_listed_status, :acceptable_listed_status_json, :condition_effects_json,
              :listing_board_requirement_summary,
              :financing_stage_requirement_summary, :transaction_type, :transaction_types_json,
              :premium_tolerance_summary, :max_premium_rate, :max_debt_ratio,
              :debt_ratio_requirement_summary, :major_risk_tolerance_summary,
              :buyer_industry_advantage_summary,
              :acceptable_cash_flow_status_json, :acceptable_profitability_status_json,
              :requires_relocation, :relocation_target_regions_json,
              :requires_return_investment, :return_investment_multiple,
              :requires_team_retention, :earnout_requirement, :listing_market_region,
              :budget_min_yuan, :budget_max_yuan, :needs_confirmation_json,
              :negative_summary, :priority_summary,
              :preference_summary, :unknown_summary,
              :created_by, :updated_by
            )
            returning id
            """
        ).bindparams(
            bindparam("parsed_requirement_json", type_=JSONB),
            bindparam("industries_json", type_=JSONB),
            bindparam("industry_l2_json", type_=JSONB),
            bindparam("excluded_industries_json", type_=JSONB),
            bindparam("industry_focus_tags_json", type_=JSONB),
            bindparam("region_constraints_json", type_=JSONB),
            bindparam("acceptable_control_paths_json", type_=JSONB),
            bindparam("acceptable_listed_status_json", type_=JSONB),
            bindparam("condition_effects_json", type_=JSONB),
            bindparam("transaction_types_json", type_=JSONB),
            bindparam("acceptable_cash_flow_status_json", type_=JSONB),
            bindparam("acceptable_profitability_status_json", type_=JSONB),
            bindparam("relocation_target_regions_json", type_=JSONB),
            bindparam("needs_confirmation_json", type_=JSONB),
        ),
        _buyer_intent_params(payload, current_user, db),
    ).mappings().one()
    db.flush()
    created = _get_buyer_intent_or_404(db, row["id"])
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=created["id"],
        source="buyer_intent_create",
    )
    db.commit()
    return created


@router.get("", response_model=BuyerIntentListOut)
def list_buyer_intents(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    search_field: Literal["intent_name", "buyer_name", "raw_requirement_text", "intent_summary"] | None = Query(
        default=None
    ),
    buyer_party_id: UUID | None = None,
    industry: str | None = Query(default=None, max_length=200),
    region: str | None = Query(default=None, max_length=200),
    status: Literal["active", "paused", "closed"] | None = Query(default=None),
    # 保持宽松：过期书签里的旧值（如 any/unknown）自然匹配 0 行，好过 422 被前端吞掉。
    listed_status: str | None = Query(default=None, max_length=80),
    requires_consolidation: Literal["yes", "no", "likely", "unknown"] | None = Query(default=None),
    owner: str | None = Query(default=None, max_length=50),
) -> dict[str, Any]:
    where = ["bi.team_id = :team_id", "bi.workspace_id = :workspace_id", "bi.deleted_at is null"]
    params: dict[str, Any] = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "limit": limit,
        "offset": offset,
    }

    append_owner_scope(where, params, current_user, entity_type="buyer_intent", alias="bi")

    owner_condition = owner_filter_condition(owner, column="bi.owner_user_id")
    if owner_condition:
        condition_sql, owner_param = owner_condition
        where.append(condition_sql)
        if owner_param is not None:
            params["owner_user_id"] = owner_param

    if q:
        if search_field:
            where.append(f"{BUYER_INTENT_SEARCH_COLUMNS[search_field]} ilike :q")
        else:
            where.append(
                "("
                "bi.intent_name ilike :q or bp.buyer_name ilike :q or bp.legal_name ilike :q "
                "or bi.raw_requirement_text ilike :q or bi.intent_summary ilike :q "
                "or bi.industry_primary ilike :q or bi.industry_secondary ilike :q or bi.region_scope_summary ilike :q"
                ")"
            )
        params["q"] = f"%{q}%"
    if buyer_party_id:
        where.append("bi.buyer_party_id = :buyer_party_id")
        params["buyer_party_id"] = buyer_party_id
    if industry:
        where.append("bi.industries_json ? :industry")
        params["industry"] = industry
    if region:
        where.append(
            "exists ("
            "select 1 from jsonb_array_elements("
            + _JSONB_ARRAY.format(column="bi.region_constraints_json")
            + ") rc "
            "where rc->>'province' = :region "
            "and coalesce(rc->>'effect', 'preferred') <> 'excluded'"
            ")"
        )
        params["region"] = region
    if status:
        where.append("bi.status = :status")
        params["status"] = status
    if listed_status:
        where.append("bi.acceptable_listed_status_json ? :listed_status")
        params["listed_status"] = listed_status
    if requires_consolidation:
        where.append("bi.requires_consolidation = :requires_consolidation")
        params["requires_consolidation"] = requires_consolidation

    where_sql = " and ".join(where)
    total = db.execute(
        text(
            f"""
            select count(*)
            from buyer_intent bi
            left join buyer_party bp
              on bp.id = bi.buyer_party_id
             and bp.deleted_at is null
            where {where_sql}
            """
        ),
        params,
    ).scalar_one()

    rows = db.execute(
        text(
            f"""
            select
{BUYER_INTENT_OUT_COLUMNS}
            from buyer_intent bi
            left join buyer_party bp
              on bp.id = bi.buyer_party_id
             and bp.deleted_at is null
            where {where_sql}
            order by bi.updated_at desc
            limit :limit offset :offset
            """
        ),
        params,
    ).mappings().all()
    items = [dict(row) for row in rows]
    states = buyer_intent_processing_states(db, items)
    for item in items:
        item["processing_state"] = states[str(item["id"])]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options", response_model=BuyerIntentFilterOptionsOut)
def buyer_intent_filter_options(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    scope_clause = ""
    # Same predicate, aliased form for the queries that join buyer_intent as bi.
    scope_clause_bi = ""
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
        scope_clause = "and owner_user_id = :scope_user_id"
        scope_clause_bi = "and bi.owner_user_id = :scope_user_id"
    industries = _filter_options(
        db,
        f"""
        select ind.value as value, count(distinct bi.id) as count
        from buyer_intent bi
        cross join lateral jsonb_array_elements_text({_JSONB_ARRAY.format(column="bi.industries_json")}) as ind(value)
        where bi.team_id = :team_id
          and bi.workspace_id = :workspace_id
          and bi.deleted_at is null
          {scope_clause_bi}
          and nullif(ind.value, '') is not null
        group by ind.value
        order by count desc, value asc
        limit 80
        """,
        params,
    )
    regions = _filter_options(
        db,
        f"""
        select rc.elem->>'province' as value, count(distinct bi.id) as count
        from buyer_intent bi
        cross join lateral jsonb_array_elements({_JSONB_ARRAY.format(column="bi.region_constraints_json")}) as rc(elem)
        where bi.team_id = :team_id
          and bi.workspace_id = :workspace_id
          and bi.deleted_at is null
          {scope_clause_bi}
          and nullif(rc.elem->>'province', '') is not null
          and coalesce(rc.elem->>'effect', 'preferred') <> 'excluded'
        group by rc.elem->>'province'
        order by count desc, value asc
        limit 80
        """,
        params,
    )
    statuses = _filter_options(
        db,
        f"""
        select status as value, count(*) as count
        from buyer_intent
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by status
        order by count desc, status asc
        """,
        params,
        labels={"active": "持续推荐", "paused": "暂停推荐", "closed": "已结束"},
    )
    listed_statuses = _filter_options(
        db,
        f"""
        select st.value as value, count(distinct bi.id) as count
        from buyer_intent bi
        cross join lateral jsonb_array_elements_text({_JSONB_ARRAY.format(column="bi.acceptable_listed_status_json")}) as st(value)
        where bi.team_id = :team_id
          and bi.workspace_id = :workspace_id
          and bi.deleted_at is null
          {scope_clause_bi}
          and nullif(st.value, '') is not null
        group by st.value
        order by count desc, value asc
        """,
        params,
        labels={
            "listed": "已上市",
            "unlisted": "未上市",
            "pre_ipo": "拟上市",
        },
    )
    consolidation_requirements = _filter_options(
        db,
        f"""
        select requires_consolidation as value, count(*) as count
        from buyer_intent
        where team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
          {scope_clause}
        group by requires_consolidation
        order by count desc, requires_consolidation asc
        """,
        params,
        labels={"yes": "需要并表", "likely": "可能需要", "no": "不需要并表", "unknown": "未知"},
    )
    owners = [] if owner_scope_required(current_user) else owner_filter_options(db, "buyer_intent", params)
    return {
        "industries": industries,
        "regions": regions,
        "statuses": statuses,
        "listed_statuses": listed_statuses,
        "consolidation_requirements": consolidation_requirements,
        "owners": owners,
    }


@router.get("/suggestions", response_model=list[BuyerIntentSuggestionOut])
def buyer_intent_suggestions(
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
        scope_clause = f"and {owner_scope_sql('buyer_intent', 'bi')}"

    rows = db.execute(
        text(
            f"""
            with matches as (
              select
                bi.id, bi.intent_name, bi.buyer_party_id, bp.buyer_name,
                bi.raw_requirement_text, bi.intent_summary, bi.updated_at,
                'intent_name'::text as search_field,
                'intent'::text as match_type,
                bi.intent_name as match_text,
                1 as priority
              from buyer_intent bi
              left join buyer_party bp on bp.id = bi.buyer_party_id and bp.deleted_at is null
              where bi.team_id = :team_id
                and bi.workspace_id = :workspace_id
                and bi.deleted_at is null
                {scope_clause}
                and bi.intent_name ilike :q
              union all
              select
                bi.id, bi.intent_name, bi.buyer_party_id, bp.buyer_name,
                bi.raw_requirement_text, bi.intent_summary, bi.updated_at,
                'buyer_name'::text as search_field,
                'buyer'::text as match_type,
                bp.buyer_name as match_text,
                2 as priority
              from buyer_intent bi
              join buyer_party bp on bp.id = bi.buyer_party_id and bp.deleted_at is null
              where bi.team_id = :team_id
                and bi.workspace_id = :workspace_id
                and bi.deleted_at is null
                {scope_clause}
                and bp.buyer_name ilike :q
              union all
              select
                bi.id, bi.intent_name, bi.buyer_party_id, bp.buyer_name,
                bi.raw_requirement_text, bi.intent_summary, bi.updated_at,
                'raw_requirement_text'::text as search_field,
                'requirement'::text as match_type,
                bi.raw_requirement_text as match_text,
                3 as priority
              from buyer_intent bi
              left join buyer_party bp on bp.id = bi.buyer_party_id and bp.deleted_at is null
              where bi.team_id = :team_id
                and bi.workspace_id = :workspace_id
                and bi.deleted_at is null
                {scope_clause}
                and bi.raw_requirement_text ilike :q
              union all
              select
                bi.id, bi.intent_name, bi.buyer_party_id, bp.buyer_name,
                bi.raw_requirement_text, bi.intent_summary, bi.updated_at,
                'intent_summary'::text as search_field,
                'summary'::text as match_type,
                bi.intent_summary as match_text,
                4 as priority
              from buyer_intent bi
              left join buyer_party bp on bp.id = bi.buyer_party_id and bp.deleted_at is null
              where bi.team_id = :team_id
                and bi.workspace_id = :workspace_id
                and bi.deleted_at is null
                {scope_clause}
                and bi.intent_summary ilike :q
            )
            select distinct on (id)
              id, intent_name, buyer_party_id, buyer_name, raw_requirement_text,
              intent_summary, search_field, match_type, match_text
            from matches
            order by id, priority, updated_at desc
            """
        ),
        params,
    ).mappings().all()
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            {"intent": 1, "buyer": 2, "requirement": 3, "summary": 4}[row["match_type"]],
            row["intent_name"],
        ),
    )
    labels = {"intent": "意向", "buyer": "买家", "requirement": "需求", "summary": "摘要"}
    return [
        {
            "id": row["id"],
            "search_field": row["search_field"],
            "match_type": row["match_type"],
            "match_label": labels[row["match_type"]],
            "match_text": row["match_text"],
            "intent_name": row["intent_name"],
            "buyer_party_id": row["buyer_party_id"],
            "buyer_name": row["buyer_name"],
            "snippet": _truncate_text(row["intent_summary"] or row["raw_requirement_text"], 80),
        }
        for row in sorted_rows[:limit]
        if row["match_text"]
    ]


class BuyerIntentBatchAssignOwnerRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)
    owner_user_id: UUID | None = None


class BuyerIntentBatchAssignOwnerOut(BaseModel):
    status: str
    updated_count: int
    updated_ids: list[UUID]


@router.post("/batch-assign-owner", response_model=BuyerIntentBatchAssignOwnerOut)
def batch_assign_buyer_intent_owner(
    payload: BuyerIntentBatchAssignOwnerRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    if payload.owner_user_id is not None:
        ensure_active_user(db, payload.owner_user_id)
    updated_ids = assign_owner_bulk(
        db,
        table="buyer_intent",
        entity_type="buyer_intent",
        entity_ids=list(dict.fromkeys(payload.ids)),
        new_owner_user_id=payload.owner_user_id,
        actor_user_id=current_user.user_id,
    )
    db.commit()
    return {"status": "ok", "updated_count": len(updated_ids), "updated_ids": updated_ids}


@router.post("/bulk-delete", response_model=BuyerIntentBulkDeleteOut)
def bulk_delete_buyer_intents(
    payload: BuyerIntentBulkDeleteRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_admin(current_user)
    intent_ids = list(dict.fromkeys(payload.ids))
    deleted_ids = _soft_delete_buyer_intents(db, intent_ids, actor_user_id=current_user.user_id)
    deleted_id_set = set(deleted_ids)
    skipped_ids = [intent_id for intent_id in intent_ids if intent_id not in deleted_id_set]
    db.commit()
    return {
        "status": "ok",
        "deleted_count": len(deleted_ids),
        "deleted_ids": deleted_ids,
        "skipped_ids": skipped_ids,
    }


@router.get("/{buyer_intent_id}", response_model=BuyerIntentOut)
def get_buyer_intent(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_visible(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    intent["processing_state"] = buyer_intent_processing_states(db, [intent])[str(buyer_intent_id)]
    return intent


@router.post("/{buyer_intent_id}/parse", response_model=BuyerIntentParseJobOut)
def parse_buyer_intent(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    payload: BuyerIntentParseRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    request = payload or BuyerIntentParseRequest()
    raw_requirement_text = request.raw_requirement_text or intent.get("raw_requirement_text")
    if not raw_requirement_text or not raw_requirement_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="raw_requirement_text is required to parse buyer intent.",
        )

    if request.raw_requirement_text and request.raw_requirement_text != intent.get("raw_requirement_text"):
        db.execute(
            text(
                """
                update buyer_intent
                set raw_requirement_text = :raw_requirement_text,
                    updated_at = now(),
                    updated_by = :updated_by
                where id = :buyer_intent_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ),
            {
                "raw_requirement_text": request.raw_requirement_text,
                "updated_by": current_user.user_id,
                "buyer_intent_id": buyer_intent_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        )

    if not request.force:
        existing_job = _latest_active_parse_job(db, buyer_intent_id)
        if existing_job:
            db.commit()
            return {
                "job_id": existing_job["id"],
                "job_type": existing_job["job_type"],
                "status": existing_job["status"],
                "queue_name": existing_job["queue_name"],
                "buyer_intent_id": existing_job["entity_id"],
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
              :team_id, :workspace_id, 'buyer_intent_parse', 100, 'llm',
              'buyer_intent', :buyer_intent_id, :idempotency_key, :payload_json,
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
            "buyer_intent_id": buyer_intent_id,
            "idempotency_key": f"buyer_intent_parse:{buyer_intent_id}:{uuid4()}",
            "payload_json": {
                "buyer_intent_id": str(buyer_intent_id),
                "raw_requirement_text": raw_requirement_text,
            },
            "created_by": current_user.user_id,
            "metadata_json": {"source": "buyer_intent_parse_api"},
        },
    ).mappings().one()
    db.commit()
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "buyer_intent_id": row["entity_id"],
    }


@router.get("/{buyer_intent_id}/parse-status", response_model=BuyerIntentParseStatusOut)
def get_buyer_intent_parse_status(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_visible(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    latest_job = _latest_parse_job(db, buyer_intent_id)
    latest_trace = _latest_parse_trace(db, buyer_intent_id)
    processing_state = buyer_intent_processing_states(db, [intent])[str(buyer_intent_id)]
    intent["processing_state"] = processing_state
    return {
        "buyer_intent": intent,
        "processing_state": processing_state,
        "latest_job": _compact_parse_job(latest_job) if latest_job else None,
        "latest_trace": _compact_parse_trace(latest_trace) if latest_trace else None,
        "recent_update_logs": _recent_parse_update_logs(db, buyer_intent_id),
        "debug_ref": _debug_ref("buyer_intent", buyer_intent_id),
    }


@router.patch("/{buyer_intent_id}", response_model=BuyerIntentOut)
def update_buyer_intent(
    buyer_intent_id: UUID,
    payload: BuyerIntentUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    original = _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    changes = payload.model_dump(exclude_unset=True)

    if "acceptable_listed_status_json" in changes:
        changes["acceptable_listed_status_json"] = _normalize_acceptable_listed_statuses(
            changes["acceptable_listed_status_json"]
        )
        changes["preferred_listed_status"] = _legacy_listed_status(changes["acceptable_listed_status_json"])
    elif "preferred_listed_status" in changes:
        changes["preferred_listed_status"] = _normalize_legacy_listed_status(changes["preferred_listed_status"])
        changes["acceptable_listed_status_json"] = _normalize_acceptable_listed_statuses(
            [changes["preferred_listed_status"]]
        )
    if "condition_effects_json" in changes:
        changes["condition_effects_json"] = normalize_condition_effects(changes["condition_effects_json"])

    if "owner_user_id" in changes:
        require_admin(current_user)
        if changes["owner_user_id"] is not None:
            ensure_active_user(db, changes["owner_user_id"])

    if "intent_name" in changes and changes["intent_name"] is not None:
        changes["intent_name"] = changes["intent_name"].strip()

    # Editing a field is the human resolution of a parser question about that
    # field. Keep unrelated questions, but do not leave the edited condition in
    # the "pending and therefore inactive" state.
    if "needs_confirmation_json" not in changes:
        pending = original.get("needs_confirmation_json")
        if isinstance(pending, list):
            resolved_fields = set(changes)
            remaining = [
                item
                for item in pending
                if not isinstance(item, dict) or str(item.get("field") or "") not in resolved_fields
            ]
            if remaining != pending:
                changes["needs_confirmation_json"] = remaining

    if not changes:
        return original

    diff = diff_payload(original, changes)
    if not diff:
        return original

    set_clauses = [f"{field} = :{field}" for field in changes]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    statement = text(
        f"""
        update buyer_intent
        set {', '.join(set_clauses)}
        where id = :buyer_intent_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        returning id
        """
    )
    json_fields = {
        "parsed_requirement_json",
        "region_constraints_json",
        "acceptable_control_paths_json",
        "transaction_types_json",
        "industries_json",
        "industry_l2_json",
        "excluded_industries_json",
        "industry_focus_tags_json",
        "acceptable_cash_flow_status_json",
        "acceptable_profitability_status_json",
        "relocation_target_regions_json",
        "needs_confirmation_json",
        "acceptable_listed_status_json",
        "condition_effects_json",
    }

    bind_params = [bindparam(field, type_=JSONB) for field in changes if field in json_fields]
    if bind_params:
        statement = statement.bindparams(*bind_params)

    row = db.execute(
        statement,
        {
            **changes,
            "updated_by": current_user.user_id,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one()
    db.flush()
    updated = _get_buyer_intent_or_404(db, row["id"])

    write_action_logs_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        diff=diff,
        applied_by=current_user.user_id,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="buyer_intent_update",
    )

    db.commit()
    return updated


@router.post("/{buyer_intent_id}/review", response_model=BuyerIntentOut)
def review_buyer_intent(
    buyer_intent_id: UUID,
    payload: BuyerIntentReviewRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    intent = _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    pending = intent.get("needs_confirmation_json")
    scenario_pending_count = db.execute(
        text(
            """
            select count(*)
            from buyer_intent_scenario
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and jsonb_array_length(needs_confirmation_json) > 0
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).scalar_one()
    if (pending or scenario_pending_count) and not payload.clear_confirmations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolve or explicitly clear pending confirmation items before completing review.",
        )

    db.execute(
        text(
            """
            update buyer_intent
            set needs_confirmation_json = case
                  when :clear_confirmations then '[]'::jsonb
                  else needs_confirmation_json
                end,
                reviewed_at = now(),
                reviewed_by = :reviewed_by,
                updated_at = now(),
                updated_by = :reviewed_by
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
            "reviewed_by": current_user.user_id,
            "clear_confirmations": payload.clear_confirmations,
        },
    )
    if payload.clear_confirmations:
        db.execute(
            text(
                """
                update buyer_intent_scenario
                set needs_confirmation_json = '[]'::jsonb,
                    updated_at = now(),
                    updated_by = :reviewed_by
                where buyer_intent_id = :buyer_intent_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ),
            {
                "buyer_intent_id": buyer_intent_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "reviewed_by": current_user.user_id,
            },
        )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="buyer_intent_review",
    )
    db.commit()
    return _get_buyer_intent_or_404(db, buyer_intent_id)


@router.delete("/{buyer_intent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_buyer_intent(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    require_admin(current_user)
    _get_buyer_intent_or_404(db, buyer_intent_id)
    _soft_delete_buyer_intents(db, [buyer_intent_id], actor_user_id=current_user.user_id)
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


def _soft_delete_buyer_intents(
    db: Session,
    buyer_intent_ids: list[UUID],
    *,
    actor_user_id: UUID | None = None,
) -> list[UUID]:
    if not buyer_intent_ids:
        return []
    actor = actor_user_id or DEFAULT_ADMIN_USER_ID

    rows = db.execute(
        text(
            """
            update buyer_intent
            set deleted_at = now(),
                deleted_by = :deleted_by,
                updated_at = now(),
                updated_by = :updated_by
            where id in :buyer_intent_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning id
            """
        ).bindparams(bindparam("buyer_intent_ids", expanding=True)),
        {
            "deleted_by": actor,
            "updated_by": actor,
            "buyer_intent_ids": buyer_intent_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    deleted_ids = [row["id"] for row in rows]
    for deleted_id in deleted_ids:
        write_action_log(
            db,
            entity_type="buyer_intent",
            entity_id=deleted_id,
            field_path="deleted_at",
            old_value=None,
            new_value="now()",
            applied_by=actor,
        )
    return deleted_ids


def _get_buyer_intent_or_404(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            f"""
            select
{BUYER_INTENT_OUT_COLUMNS}
            from buyer_intent bi
            left join buyer_party bp
              on bp.id = bi.buyer_party_id
             and bp.deleted_at is null
            where bi.id = :buyer_intent_id
              and bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
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


def _resolve_intent_owner(payload: BuyerIntentCreate, current_user: AuthContext, db: Session) -> UUID:
    """意向负责人：管理员可指定；否则默认继承所属买家的负责人，兜底为创建人。"""
    if current_user.is_admin and payload.owner_user_id:
        return payload.owner_user_id
    if payload.buyer_party_id:
        buyer_owner = db.execute(
            text(
                """
                select owner_user_id from buyer_party
                where id = :buyer_party_id and team_id = :team_id
                  and workspace_id = :workspace_id and deleted_at is null
                """
            ),
            {
                "buyer_party_id": payload.buyer_party_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).scalar()
        if buyer_owner:
            return buyer_owner
    return current_user.user_id


def _buyer_intent_params(payload: BuyerIntentCreate, current_user: AuthContext, db: Session) -> dict[str, Any]:
    acceptable_listed_statuses = _normalize_acceptable_listed_statuses(payload.acceptable_listed_status_json)
    if not acceptable_listed_statuses:
        acceptable_listed_statuses = _normalize_acceptable_listed_statuses([payload.preferred_listed_status])
    return {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "buyer_party_id": payload.buyer_party_id,
        "owner_user_id": _resolve_intent_owner(payload, current_user, db),
        "intent_name": payload.intent_name.strip(),
        "contact_name": payload.contact_name,
        "raw_requirement_text": payload.raw_requirement_text,
        "intent_summary": payload.intent_summary,
        "parsed_requirement_json": payload.parsed_requirement_json or {},
        "industry_primary": payload.industry_primary,
        "industry_secondary": payload.industry_secondary,
        "industries_json": payload.industries_json or [],
        "industry_l2_json": payload.industry_l2_json or [],
        "excluded_industries_json": payload.excluded_industries_json or [],
        "industry_focus_tags_json": payload.industry_focus_tags_json or [],
        "region_scope_summary": payload.region_scope_summary,
        "region_constraints_json": payload.region_constraints_json or [],
        "min_revenue_yuan": payload.min_revenue_yuan,
        "min_net_profit_yuan": payload.min_net_profit_yuan,
        "min_total_profit_yuan": payload.min_total_profit_yuan,
        "max_pe": payload.max_pe,
        "max_ps": payload.max_ps,
        "min_net_margin": payload.min_net_margin,
        "min_gross_margin": payload.min_gross_margin,
        "min_valuation_yuan": payload.min_valuation_yuan,
        "max_valuation_yuan": payload.max_valuation_yuan,
        "min_market_cap_yuan": payload.min_market_cap_yuan,
        "max_market_cap_yuan": payload.max_market_cap_yuan,
        "market_cap_range_summary": payload.market_cap_range_summary,
        "requires_control": payload.requires_control,
        "requires_consolidation": payload.requires_consolidation,
        "accepts_minority_investment": payload.accepts_minority_investment,
        "desired_equity_ratio_min": payload.desired_equity_ratio_min,
        "desired_equity_ratio_max": payload.desired_equity_ratio_max,
        "equity_ratio_summary": payload.equity_ratio_summary,
        "equity_requirement_type": payload.equity_requirement_type,
        "acceptable_control_paths_json": payload.acceptable_control_paths_json or [],
        "preferred_listed_status": _legacy_listed_status(acceptable_listed_statuses),
        "acceptable_listed_status_json": acceptable_listed_statuses,
        "condition_effects_json": normalize_condition_effects(payload.condition_effects_json),
        "listing_board_requirement_summary": payload.listing_board_requirement_summary,
        "financing_stage_requirement_summary": payload.financing_stage_requirement_summary,
        "transaction_type": payload.transaction_type,
        "transaction_types_json": payload.transaction_types_json or [],
        "premium_tolerance_summary": payload.premium_tolerance_summary,
        "max_premium_rate": payload.max_premium_rate,
        "max_debt_ratio": payload.max_debt_ratio,
        "debt_ratio_requirement_summary": payload.debt_ratio_requirement_summary,
        "major_risk_tolerance_summary": payload.major_risk_tolerance_summary,
        "buyer_industry_advantage_summary": payload.buyer_industry_advantage_summary,
        "acceptable_cash_flow_status_json": payload.acceptable_cash_flow_status_json or [],
        "acceptable_profitability_status_json": payload.acceptable_profitability_status_json or [],
        "requires_relocation": payload.requires_relocation,
        "relocation_target_regions_json": payload.relocation_target_regions_json or [],
        "requires_return_investment": payload.requires_return_investment,
        "return_investment_multiple": payload.return_investment_multiple,
        "requires_team_retention": payload.requires_team_retention,
        "earnout_requirement": payload.earnout_requirement,
        "listing_market_region": payload.listing_market_region,
        "budget_min_yuan": payload.budget_min_yuan,
        "budget_max_yuan": payload.budget_max_yuan,
        "needs_confirmation_json": payload.needs_confirmation_json or [],
        "negative_summary": payload.negative_summary,
        "priority_summary": payload.priority_summary,
        "preference_summary": payload.preference_summary,
        "unknown_summary": payload.unknown_summary,
        "created_by": current_user.user_id,
        "updated_by": current_user.user_id,
    }


def _normalize_acceptable_listed_statuses(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else []
    output: list[str] = []
    for value in values:
        normalized = _normalize_legacy_listed_status(value)
        if normalized in {"listed", "unlisted", "pre_ipo"} and normalized not in output:
            output.append(normalized)
    return output


def _normalize_legacy_listed_status(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "preparing_listing":
        return "pre_ipo"
    return normalized if normalized in {"listed", "unlisted", "pre_ipo", "any", "unknown"} else "unknown"


def _legacy_listed_status(values: list[str]) -> str:
    return values[0] if len(values) == 1 else "any"


def _latest_active_parse_job(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'buyer_intent_parse'
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_job(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
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
              and job_type = 'buyer_intent_parse'
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
            order by created_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _latest_parse_trace(db: Session, buyer_intent_id: UUID) -> dict[str, Any] | None:
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
              and node_name = any(:buyer_parse_node_names)
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
            order by started_at desc
            limit 1
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_parse_node_names": list(buyer_parse_node_names()),
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _recent_parse_update_logs(db: Session, buyer_intent_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select
              id, field_path, old_value_json, new_value_json, source_type, source_id,
              applied_at::text as applied_at, can_rollback, rollback_at::text as rollback_at
            from action_application_log
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = 'buyer_intent'
              and entity_id = :buyer_intent_id
              and source_type = 'buyer_intent_parse'
            order by applied_at desc
            limit 50
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
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
    return text_value[: max_length - 1] + "…"


class BuyerIntentScenarioOut(BaseModel):
    id: UUID
    buyer_intent_id: UUID
    label: str
    sort_order: int
    active: bool
    fields_json: dict[str, Any]
    needs_confirmation_json: list[Any] = []
    condition_effects_json: dict[str, Any] = {}
    source: str
    created_at: str
    updated_at: str


class BuyerIntentScenarioWrite(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sort_order: int = 0
    active: bool = True
    # 只接受条件白名单里的字段；越权字段在 normalize_scenario_fields 中被丢弃。
    fields_json: dict[str, Any] = Field(default_factory=dict)
    needs_confirmation_json: list[Any] = Field(default_factory=list)
    condition_effects_json: dict[str, Any] = Field(default_factory=dict)


@router.get("/{buyer_intent_id}/scenarios", response_model=list[BuyerIntentScenarioOut])
def list_buyer_intent_scenarios(
    buyer_intent_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_visible(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    rows = db.execute(
        text(
            """
            select
              id, buyer_intent_id, label, sort_order, active, fields_json,
              needs_confirmation_json, condition_effects_json, source,
              created_at::text as created_at, updated_at::text as updated_at
            from buyer_intent_scenario
            where buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            order by sort_order, created_at
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post(
    "/{buyer_intent_id}/scenarios",
    response_model=BuyerIntentScenarioOut,
    status_code=status.HTTP_201_CREATED,
)
def create_buyer_intent_scenario(
    buyer_intent_id: UUID,
    payload: BuyerIntentScenarioWrite,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    row = db.execute(
        text(
            """
            insert into buyer_intent_scenario (
              team_id, workspace_id, buyer_intent_id, label, sort_order, active,
              fields_json, needs_confirmation_json, condition_effects_json, source, created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :label, :sort_order, :active,
              :fields_json, :needs_confirmation_json, :condition_effects_json, 'manual', :user_id, :user_id
            )
            returning
              id, buyer_intent_id, label, sort_order, active, fields_json,
              needs_confirmation_json, condition_effects_json, source,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ).bindparams(
            bindparam("fields_json", type_=JSONB),
            bindparam("needs_confirmation_json", type_=JSONB),
            bindparam("condition_effects_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "label": payload.label,
            "sort_order": payload.sort_order,
            "active": payload.active,
            "fields_json": normalize_scenario_fields(payload.fields_json),
            "needs_confirmation_json": payload.needs_confirmation_json,
            "condition_effects_json": normalize_condition_effects(payload.condition_effects_json),
            "user_id": current_user.user_id,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.patch("/{buyer_intent_id}/scenarios/{scenario_id}", response_model=BuyerIntentScenarioOut)
def update_buyer_intent_scenario(
    buyer_intent_id: UUID,
    scenario_id: UUID,
    payload: BuyerIntentScenarioWrite,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    row = db.execute(
        text(
            """
            update buyer_intent_scenario
            set label = :label,
                sort_order = :sort_order,
                active = :active,
                fields_json = :fields_json,
                needs_confirmation_json = :needs_confirmation_json,
                condition_effects_json = :condition_effects_json,
                updated_at = now(),
                updated_by = :user_id
            where id = :scenario_id
              and buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            returning
              id, buyer_intent_id, label, sort_order, active, fields_json,
              needs_confirmation_json, condition_effects_json, source,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ).bindparams(
            bindparam("fields_json", type_=JSONB),
            bindparam("needs_confirmation_json", type_=JSONB),
            bindparam("condition_effects_json", type_=JSONB),
        ),
        {
            "scenario_id": scenario_id,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "label": payload.label,
            "sort_order": payload.sort_order,
            "active": payload.active,
            "fields_json": normalize_scenario_fields(payload.fields_json),
            "needs_confirmation_json": payload.needs_confirmation_json,
            "condition_effects_json": normalize_condition_effects(payload.condition_effects_json),
            "user_id": current_user.user_id,
        },
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found.")
    db.commit()
    return dict(row)


@router.delete(
    "/{buyer_intent_id}/scenarios/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_buyer_intent_scenario(
    buyer_intent_id: UUID,
    scenario_id: UUID,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
) -> None:
    _get_buyer_intent_or_404(db, buyer_intent_id)
    ensure_entity_writable(db, current_user, entity_type="buyer_intent", entity_id=buyer_intent_id)
    db.execute(
        text(
            """
            update buyer_intent_scenario
            set deleted_at = now(), updated_by = :user_id
            where id = :scenario_id
              and buyer_intent_id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "scenario_id": scenario_id,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "user_id": current_user.user_id,
        },
    )
    db.commit()
