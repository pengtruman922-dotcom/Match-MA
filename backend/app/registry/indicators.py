"""The single declaration of structured Match-MA information fields.

Every consumer derives field names, write authority, enum validation and UI
metadata from this module.  It deliberately contains no SQL or transport code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndicatorGroup:
    key: str
    label: str
    section_code: str


@dataclass(frozen=True)
class Indicator:
    column: str
    label: str
    group: str | None
    kind: str  # text | yuan | ratio | enum | date | json
    screening: bool = False
    writable_by: frozenset[str] = field(default_factory=frozenset)
    # (stored code, Chinese display label).  Validation and display must share
    # this declaration so a new enum cannot silently render as an English code.
    enum_options: tuple[tuple[str, str], ...] | None = None
    fold_into: str | None = None
    # Buyer-demand comparison contract. Seller facts leave these values empty.
    target_column: str | None = None
    operator: str | None = None
    default_effect: str | None = None
    effect_editable: bool = False
    scenario_allowed: bool = False
    multi_value: bool = False
    sql_recall: bool = False
    deterministic_rank: bool = False
    deep_eval: bool = True
    editor: str | None = None


GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("identity", "身份与地区", "identity"),
    IndicatorGroup("business_product", "业务与产品", "business_product"),
    IndicatorGroup("tech_team", "技术与团队", "tech_team"),
    IndicatorGroup("ops_quality", "经营质量", "ops_quality"),
    IndicatorGroup("deal_terms", "交易属性与出售诉求", "deal_terms"),
)

# 和卖方一样：每个模块 = 结构化条件字段 + 一块「其他」自由文本。
# 原来还有个 intent_notes「深评与补充」，是 15 个字段的杂物间 —— 那些内容正是
# 各模块「其他」要装的东西，所以它解散了，字段按主题回到三个模块。
BUYER_GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("intent_scope", "行业与地区", "intent_scope"),
    IndicatorGroup("intent_financial", "经营与财务", "intent_financial"),
    IndicatorGroup("intent_deal", "交易与能力要求", "intent_deal"),
)

_PARSE = frozenset({"parse"})
_RESEARCH = frozenset({"research"})
_MANUAL = frozenset({"manual"})
_ALL = frozenset({"parse", "research", "manual"})
_PARSE_MANUAL = frozenset({"parse", "manual"})
_BOTH_MANUAL = frozenset({"parse", "research", "manual"})

_YES_NO_LIKE = (
    ("yes", "是"),
    ("no", "否"),
    ("unknown", "未知"),
    ("likely", "可能"),
)
_TARGET_TYPE = (
    ("company", "公司"), ("equity_package", "股权包"),
    ("business_unit", "业务单元"), ("asset_package", "资产包"),
    ("project", "项目"), ("other", "其他"),
)
_LISTED_STATUS = (("listed", "已上市"), ("unlisted", "未上市"), ("pre_ipo", "拟上市"), ("unknown", "未知"))
_PROFITABILITY = (("profitable", "盈利"), ("loss_making", "亏损"), ("break_even", "盈亏平衡"), ("unknown", "未知"))
_CASH_FLOW = (("stable_positive", "稳定为正"), ("positive", "为正"), ("negative", "为负"), ("unstable", "不稳定"), ("unknown", "未知"))
_OPERATION_STABILITY = (("stable", "稳定"), ("unstable", "不稳定"), ("unknown", "未知"), ("needs_review", "待核实"))
_TRANSFER_FLEXIBILITY = (
    ("control_available", "可控股"), ("consolidation_available", "可并表"),
    ("minority_available", "可少数股权"), ("full_sale_available", "可整体出售"),
    ("flexible", "可协商"), ("specific_range", "有明确范围"), ("unknown", "未知"),
)
_PE_SOURCE = (("user_input", "人工录入"), ("document", "文件"), ("calculated", "计算"), ("research", "调研"), ("unknown", "未知"))
_EARNOUT = (("none", "无"), ("low", "低"), ("medium", "中"), ("high", "高"), ("unknown", "未知"))
_MARKET_REGION = (("domestic", "境内"), ("overseas", "境外"), ("unknown", "未知"))
_REQUIREMENT_STRENGTH = (
    ("required", "必须满足"),
    ("preferred", "优先满足"),
    ("not_required", "不作要求"),
    ("unknown", "需要确认"),
)


SELLER_TARGET_INDICATORS: tuple[Indicator, ...] = (
    # 身份与地区
    Indicator("target_name", "标的名称", "identity", "text", writable_by=_PARSE_MANUAL),
    Indicator("target_subject_name", "标的主体", "identity", "text", writable_by=_BOTH_MANUAL),
    Indicator("target_type", "类型", "identity", "enum", writable_by=_PARSE_MANUAL, enum_options=_TARGET_TYPE),
    Indicator("location_province", "所在地", "identity", "text", screening=True, writable_by=_BOTH_MANUAL),
    Indicator("location_city", "所在市", "identity", "text", screening=True, writable_by=_BOTH_MANUAL, fold_into="location_province"),
    Indicator("location_district", "所在区", "identity", "text", screening=True, writable_by=_BOTH_MANUAL, fold_into="location_province"),
    # 业务与产品
    Indicator("industry_pairs_json", "所属行业", "business_product", "json", screening=True, writable_by=_BOTH_MANUAL),
    Indicator("business_summary", "业务摘要", "business_product", "text", writable_by=_BOTH_MANUAL),
    # 技术与团队
    Indicator("management_retention_possible", "团队可留任", "tech_team", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("management_team_summary", "管理团队", "tech_team", "text", writable_by=_MANUAL),
    # 经营质量
    Indicator("current_revenue_yuan", "营收", "ops_quality", "yuan", screening=True, writable_by=_ALL),
    Indicator("current_net_profit_yuan", "净利润", "ops_quality", "yuan", screening=True, writable_by=_ALL),
    Indicator("current_total_profit_yuan", "利润总额", "ops_quality", "yuan", screening=True, writable_by=_ALL),
    Indicator("current_assets_yuan", "总资产", "ops_quality", "yuan", writable_by=_ALL),
    Indicator("current_debt_ratio", "资产负债率", "ops_quality", "ratio", screening=True, writable_by=_ALL),
    Indicator("current_operating_cash_flow_yuan", "经营现金流", "ops_quality", "yuan", writable_by=_ALL),
    Indicator("financial_period_label", "财务期间", "ops_quality", "text", writable_by=_ALL),
    # Internal comparison key.  The mapper must provide as_of_date on each
    # financial fact; research_apply derives this column instead of asking the
    # model to invent a second period field.  fold_into keeps it out of the UI.
    Indicator("financial_period_end_date", "财务期间截止日", "ops_quality", "date", writable_by=_RESEARCH, fold_into="financial_period_label"),
    Indicator("profitability_status", "盈利状态", "ops_quality", "enum", screening=True, writable_by=_ALL, enum_options=_PROFITABILITY),
    Indicator("cash_flow_status", "现金流状态", "ops_quality", "enum", screening=True, writable_by=_ALL, enum_options=_CASH_FLOW),
    Indicator("operation_stability_status", "经营稳定性", "ops_quality", "enum", writable_by=_ALL, enum_options=_OPERATION_STABILITY),
    # 交易属性
    Indicator("listed_status", "上市状态", "deal_terms", "enum", screening=True, writable_by=_BOTH_MANUAL, enum_options=_LISTED_STATUS),
    Indicator("listing_market_region", "上市地", "deal_terms", "enum", screening=True, writable_by=_MANUAL | _RESEARCH, enum_options=_MARKET_REGION),
    Indicator("market_cap_yuan", "市值", "deal_terms", "yuan", screening=True, writable_by=_ALL),
    Indicator("valuation_yuan", "估值", "deal_terms", "yuan", screening=True, writable_by=_ALL),
    Indicator("valuation_date", "估值时间", "deal_terms", "date", writable_by=_ALL),
    Indicator("asking_price_yuan", "报价", "deal_terms", "yuan", writable_by=_PARSE_MANUAL),
    Indicator("asking_price_date", "报价时间", "deal_terms", "date", writable_by=_PARSE_MANUAL),
    Indicator("pe_ratio", "PE", "deal_terms", "ratio", screening=True, writable_by=_ALL),
    Indicator("pe_source_type", "PE 口径", "deal_terms", "enum", writable_by=_ALL, enum_options=_PE_SOURCE),
    Indicator("premium_rate", "溢价率", "deal_terms", "ratio", writable_by=_PARSE_MANUAL),
    Indicator("transfer_ratio_min", "出售比例", "deal_terms", "ratio", screening=True, writable_by=_PARSE_MANUAL),
    Indicator("transfer_ratio_max", "出售比例上限", "deal_terms", "ratio", writable_by=_PARSE_MANUAL, fold_into="transfer_ratio_min"),
    Indicator("transfer_ratio_text", "出售比例说明", "deal_terms", "text", writable_by=_PARSE_MANUAL, fold_into="transfer_ratio_min"),
    Indicator("transfer_flexibility_type", "转让灵活度", "deal_terms", "enum", writable_by=_PARSE_MANUAL, enum_options=_TRANSFER_FLEXIBILITY),
    Indicator("can_control", "可控股", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("can_consolidate", "可并表", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("accepts_minority_investment", "接受少数股权", "deal_terms", "enum", writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("consolidation_path_summary", "并表路径", "deal_terms", "text", writable_by=_MANUAL),
    Indicator("accepts_relocation", "接受迁址", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("accepts_return_investment", "接受返投", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("earnout_dependency_status", "对赌依赖", "deal_terms", "enum", writable_by=_PARSE_MANUAL, enum_options=_EARNOUT),
    Indicator("transaction_summary", "交易摘要", "deal_terms", "text", writable_by=_PARSE_MANUAL),
    # 出售诉求
    Indicator("is_for_sale", "是否还卖", "deal_terms", "enum", writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("risk_summary", "风险摘要", "deal_terms", "text", writable_by=_ALL),
    # 系统状态不是信息页业务事实，不允许手动编辑。交易状态（lifecycle_status）
    # 由详情页下拉维护，走专用流程，不进注册表。
    # pending_review 仅在数据库 check 中兼容历史行，不再向任何写入方暴露。
    Indicator("information_status", "信息状态", None, "enum", writable_by=_PARSE, enum_options=(("normal", "正常"), ("insufficient", "信息不足"), ("parsing", "解析中"), ("researching", "调研中"), ("parse_failed", "解析失败"))),
)

_BI_PARSE = frozenset({"parse"})
_BI_WRITE = frozenset({"parse", "manual"})
_BI_EQUITY_TYPE = (("control_required", "要求控股"), ("consolidation_required", "要求并表"), ("minority_acceptable", "可少数股权"), ("minority_only", "仅少数股权"), ("flexible", "可协商"), ("specific_range", "明确范围"), ("unknown", "未知"))
_BI_LISTED = (("listed", "已上市"), ("unlisted", "未上市"), ("pre_ipo", "拟上市"), ("any", "不限"), ("unknown", "未知"))
_BI_LISTED_ACCEPTABLE = (("listed", "已上市"), ("unlisted", "未上市"), ("pre_ipo", "拟上市"))

BUYER_INTENT_INDICATORS: tuple[Indicator, ...] = (
    Indicator("intent_summary", "需求摘要", None, "text", writable_by=_BI_WRITE, editor="textarea"),
    Indicator("raw_requirement_text", "原始需求", None, "text", writable_by=_BI_PARSE),
    Indicator("industry_primary", "行业原文（一级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industry_secondary", "行业原文（二级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industries_json", "可接受一级行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json.l1", operator="overlap", default_effect="required", effect_editable=True, scenario_allowed=True, multi_value=True, sql_recall=True, deterministic_rank=True, editor="industry"),
    Indicator("industry_l2_json", "二级关注行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json.l2", operator="overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="industry_l2"),
    Indicator("excluded_industries_json", "排除行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json", operator="not_overlap", default_effect="required", effect_editable=False, scenario_allowed=True, multi_value=True, sql_recall=True, deterministic_rank=True, editor="industry"),
    Indicator("industry_focus_tags_json", "字典外细分方向", "intent_scope", "json", writable_by=_BI_WRITE, scenario_allowed=True, multi_value=True, editor="tags"),
    Indicator("region_scope_summary", "地域摘要（兼容）", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True, editor="text"),
    Indicator("region_constraints_json", "可接受地区", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="location_province,location_city,location_district", operator="region_any", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="region_multi"),
    Indicator("min_revenue_yuan", "最低营收", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_revenue_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, sql_recall=True, deterministic_rank=True),
    Indicator("min_net_profit_yuan", "最低净利润", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_total_profit_yuan", "最低利润总额", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_total_profit_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_net_margin", "最低净利率", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan/current_revenue_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_gross_margin", "最低毛利率", "intent_financial", "ratio", writable_by=_BI_WRITE, default_effect="preferred", effect_editable=True, scenario_allowed=True),
    Indicator("max_pe", "PE 上限", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="pe_ratio", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_ps", "PS 上限", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan/current_revenue_yuan", operator="lte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_valuation_yuan", "最低估值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_valuation_yuan", "最高估值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_market_cap_yuan", "最低市值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_market_cap_yuan", "最高市值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="lte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("market_cap_range_summary", "市值范围说明", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("max_debt_ratio", "负债率上限", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="current_debt_ratio", operator="lte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("acceptable_cash_flow_status_json", "可接受现金流状态", "intent_financial", "json", screening=True, writable_by=_BI_WRITE, target_column="cash_flow_status", operator="in", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_CASH_FLOW),
    Indicator("acceptable_profitability_status_json", "可接受盈利状态", "intent_financial", "json", screening=True, writable_by=_BI_WRITE, target_column="profitability_status", operator="in", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_PROFITABILITY),
    Indicator("requires_control", "控股要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="can_control", operator="requirement_capability", default_effect="required", effect_editable=True, scenario_allowed=True, sql_recall=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("requires_consolidation", "并表要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="can_consolidate", operator="requirement_capability", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("accepts_minority_investment", "接受少数股权", "intent_deal", "enum", writable_by=_BI_WRITE, target_column="accepts_minority_investment", operator="requirement_capability", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("equity_requirement_type", "股权诉求类型", "intent_deal", "enum", writable_by=_BI_WRITE, scenario_allowed=True, enum_options=_BI_EQUITY_TYPE),
    Indicator("desired_equity_ratio_min", "期望股比下限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_max", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("desired_equity_ratio_max", "期望股比上限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_min", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("equity_ratio_summary", "股权比例说明", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("acceptable_listed_status_json", "可接受上市状态", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="listed_status", operator="in", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_BI_LISTED_ACCEPTABLE),
    Indicator("preferred_listed_status", "上市要求（兼容字段）", None, "enum", writable_by=_BI_PARSE, enum_options=_BI_LISTED),
    Indicator("listing_market_region", "上市地要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="listing_market_region", operator="eq", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_MARKET_REGION),
    Indicator("requires_relocation", "迁址要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="accepts_relocation", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("requires_return_investment", "返投要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="accepts_return_investment", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("requires_team_retention", "团队留任要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="management_retention_possible", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("earnout_requirement", "对赌要求", "intent_deal", "enum", writable_by=_BI_WRITE, scenario_allowed=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("return_investment_multiple", "返投倍数", "intent_deal", "ratio", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("listing_board_requirement_summary", "上市板块要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("financing_stage_requirement_summary", "融资阶段要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("transaction_type", "交易方式", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("transaction_types_json", "交易方式（多值）", "intent_deal", "json", writable_by=_BI_WRITE, scenario_allowed=True, multi_value=True, editor="tags"),
    Indicator("max_premium_rate", "溢价上限", "intent_deal", "ratio", writable_by=_BI_WRITE, default_effect="preferred", effect_editable=True, scenario_allowed=True),
    Indicator("premium_tolerance_summary", "溢价要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("debt_ratio_requirement_summary", "负债率要求说明", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("major_risk_tolerance_summary", "风险容忍", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("buyer_industry_advantage_summary", "产业优势", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("condition_effects_json", "条件作用", None, "json", writable_by=_BI_WRITE),
    Indicator("status", "状态", None, "enum", writable_by=_BI_PARSE, enum_options=(("active", "进行中"), ("paused", "暂停"), ("closed", "已结束"))),
    Indicator("pause_reason", "暂停原因", None, "text", writable_by=_BI_PARSE),
)

_BY_ENTITY: dict[str, tuple[Indicator, ...]] = {
    "seller_target": SELLER_TARGET_INDICATORS,
    "buyer_intent": BUYER_INTENT_INDICATORS,
}


def indicators_for(entity: str = "seller_target") -> tuple[Indicator, ...]:
    try:
        return _BY_ENTITY[entity]
    except KeyError:
        raise ValueError(f"registry does not cover entity {entity!r}") from None


def groups_for(entity: str = "seller_target") -> tuple[IndicatorGroup, ...]:
    if entity == "seller_target":
        return GROUPS
    if entity == "buyer_intent":
        return BUYER_GROUPS
    raise ValueError(f"registry does not cover entity {entity!r}")


def indicator_by_column(entity: str, column: str) -> Indicator:
    for indicator in indicators_for(entity):
        if indicator.column == column:
            return indicator
    raise KeyError(f"unknown {entity} indicator {column!r}")


def writable_columns(source: str, entity: str = "seller_target") -> set[str]:
    return {indicator.column for indicator in indicators_for(entity) if source in indicator.writable_by}


def screening_columns(entity: str = "seller_target") -> set[str]:
    return {indicator.column for indicator in indicators_for(entity) if indicator.screening}


def writable_enum_values(entity: str = "seller_target") -> dict[str, set[str]]:
    return {
        indicator.column: {code for code, _ in indicator.enum_options}
        for indicator in indicators_for(entity)
        if indicator.enum_options is not None
    }
