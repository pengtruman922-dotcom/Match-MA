"""The indicator registry: one declaration per structured field.

A field's facts — which group it belongs to, whether it screens, what enum
values it accepts, who may write it — were spread across five places that a
human had to keep in step (the DB column, recommendation_flow's reads, the
frontend infoGroups, the parse whitelist, the research whitelist), guarded only
by sync tests. This module is the single source those five derive from.

Scope note: seller_target only, for now. buyer_intent joins in R3b. Until a
consumer is switched to read from here, the old source stays authoritative and
tests/test_indicator_registry.py pins this registry to it so the two cannot
drift while the migration is in flight.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndicatorGroup:
    key: str
    label: str
    # 画像六栏对应的 section_code；identity 组无画像栏。
    section_code: str | None


@dataclass(frozen=True)
class Indicator:
    column: str
    label: str
    # 所属分组 key；None = 系统字段，不在标的信息页展示。
    group: str | None
    # text | yuan | ratio | enum | date
    kind: str
    # 参与 SQL 硬筛或代码打分。判定依据是 recommendation_flow 实际读取的列。
    screening: bool = False
    # {"parse", "research"} 的子集——哪些来源可以写这个字段。manual 待 R3b 接入。
    writable_by: frozenset[str] = field(default_factory=frozenset)
    # 可写枚举的合法取值（供写入校验）；展示用中文名仍由前端 fieldLabels 映射。
    # 纯展示枚举（如 target_type）不在写白名单里，enum_values 留空。
    enum_values: tuple[str, ...] | None = None
    # 展示时折叠进另一列的行（如 registered_city 折进 registered_province）。
    fold_into: str | None = None


GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("identity", "身份与地区", None),
    IndicatorGroup("business_product", "业务与产品", "business_product"),
    IndicatorGroup("chain_position", "产业链位置与行业地位", "chain_position"),
    IndicatorGroup("tech_team", "技术与团队能力", "tech_team"),
    IndicatorGroup("ops_quality", "经营质量", "ops_quality"),
    IndicatorGroup("deal_terms", "交易属性与配合度", "deal_terms"),
    IndicatorGroup("sell_intent_risk", "出售诉求与风险缺口", "sell_intent_risk"),
)

_PARSE = frozenset({"parse"})
_RESEARCH = frozenset({"research"})
_BOTH = frozenset({"parse", "research"})

# yes/no/unknown/likely 三态枚举的公共取值。
_YES_NO_LIKE = ("yes", "no", "unknown", "likely")

SELLER_TARGET_INDICATORS: tuple[Indicator, ...] = (
    # 身份与地区 -----------------------------------------------------------
    Indicator("target_name", "标的名称", "identity", "text", writable_by=_PARSE),
    Indicator("target_subject_name", "标的主体", "identity", "text", writable_by=_BOTH),
    Indicator("target_type", "类型", "identity", "enum"),
    Indicator("registered_province", "注册地", "identity", "text", writable_by=_RESEARCH),
    Indicator("registered_city", "注册城市", "identity", "text", writable_by=_RESEARCH, fold_into="registered_province"),
    Indicator("headquarter_province", "总部", "identity", "text", screening=True, writable_by=_BOTH),
    Indicator("headquarter_city", "总部城市", "identity", "text", writable_by=_BOTH, fold_into="headquarter_province"),
    Indicator("raw_region_text", "地区原文", "identity", "text"),
    Indicator("region_granularity", "地区粒度", "identity", "enum"),
    # 业务与产品 -----------------------------------------------------------
    Indicator("industry_l1", "一级行业", "business_product", "text", screening=True, writable_by=_BOTH),
    Indicator("industry_l2", "二级行业", "business_product", "text", screening=True, writable_by=_BOTH),
    Indicator("industry_primary", "行业原文（一级）", "business_product", "text", writable_by=_BOTH),
    Indicator("industry_secondary", "行业原文（二级）", "business_product", "text", writable_by=_BOTH),
    Indicator("business_summary", "业务摘要", "business_product", "text", writable_by=_BOTH),
    # 产业链位置：无结构化字段，只有画像。
    # 技术与团队能力 -------------------------------------------------------
    Indicator("management_retention_possible", "团队可留任", "tech_team", "enum", screening=True),
    Indicator("management_team_summary", "管理团队", "tech_team", "text"),
    # 经营质量 -------------------------------------------------------------
    Indicator("current_revenue_yuan", "营收", "ops_quality", "yuan", screening=True, writable_by=_PARSE),
    Indicator("current_net_profit_yuan", "净利润", "ops_quality", "yuan", screening=True, writable_by=_PARSE),
    Indicator("current_total_profit_yuan", "利润总额", "ops_quality", "yuan", screening=True, writable_by=_PARSE),
    Indicator("current_assets_yuan", "总资产", "ops_quality", "yuan"),
    Indicator("current_debt_ratio", "资产负债率", "ops_quality", "ratio", screening=True),
    Indicator("current_operating_cash_flow_yuan", "经营现金流", "ops_quality", "yuan"),
    Indicator("financial_period_label", "财务期间", "ops_quality", "text", writable_by=_PARSE),
    Indicator("profitability_status", "盈利状态", "ops_quality", "enum", screening=True),
    Indicator("cash_flow_status", "现金流状态", "ops_quality", "enum", screening=True),
    Indicator("operation_stability_status", "经营稳定性", "ops_quality", "enum"),
    # 交易属性与配合度 -----------------------------------------------------
    Indicator("listed_status", "上市状态", "deal_terms", "enum", screening=True, writable_by=_BOTH,
              enum_values=("listed", "unlisted", "pre_ipo", "unknown")),
    Indicator("market_cap_yuan", "市值", "deal_terms", "yuan", screening=True),
    Indicator("listing_market_region", "上市地", "deal_terms", "enum", screening=True),
    Indicator("valuation_yuan", "估值", "deal_terms", "yuan", screening=True, writable_by=_PARSE),
    Indicator("valuation_date", "估值时间", "deal_terms", "date", writable_by=_PARSE),
    Indicator("asking_price_yuan", "报价", "deal_terms", "yuan", writable_by=_PARSE),
    Indicator("asking_price_date", "报价时间", "deal_terms", "date", writable_by=_PARSE),
    Indicator("pe_ratio", "PE", "deal_terms", "ratio", screening=True, writable_by=_PARSE),
    Indicator("pe_source_type", "PE 口径", "deal_terms", "enum"),
    Indicator("transfer_ratio_min", "出售比例", "deal_terms", "ratio", screening=True, writable_by=_PARSE),
    Indicator("transfer_ratio_max", "出售比例上限", "deal_terms", "ratio", writable_by=_PARSE, fold_into="transfer_ratio_min"),
    Indicator("transfer_ratio_text", "出售比例原文", "deal_terms", "text", writable_by=_PARSE, fold_into="transfer_ratio_min"),
    Indicator("transfer_flexibility_type", "转让灵活度", "deal_terms", "enum", writable_by=_PARSE,
              enum_values=("control_available", "consolidation_available", "minority_available",
                           "full_sale_available", "flexible", "specific_range", "unknown")),
    Indicator("can_control", "可控股", "deal_terms", "enum", screening=True, writable_by=_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("can_consolidate", "可并表", "deal_terms", "enum", screening=True, writable_by=_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("accepts_minority_investment", "接受少数股权", "deal_terms", "enum", writable_by=_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("consolidation_path_summary", "并表路径", "deal_terms", "text"),
    Indicator("accepts_relocation", "接受迁址", "deal_terms", "enum", screening=True),
    Indicator("accepts_return_investment", "接受返投", "deal_terms", "enum", screening=True),
    Indicator("earnout_dependency_status", "对赌依赖", "deal_terms", "enum"),
    Indicator("transaction_summary", "交易摘要", "deal_terms", "text", writable_by=_PARSE),
    # 出售诉求与风险缺口 ---------------------------------------------------
    Indicator("is_for_sale", "是否还卖", "sell_intent_risk", "enum", writable_by=_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("risk_summary", "风险摘要", "sell_intent_risk", "text", writable_by=_PARSE),
    Indicator("gap_summary", "缺口摘要", "sell_intent_risk", "text", writable_by=_PARSE),
    # 系统字段（不在信息页展示，但 parse 会写）---------------------------
    Indicator("information_status", "信息状态", None, "enum", writable_by=_PARSE,
              enum_values=("normal", "insufficient", "pending_review", "parsing", "researching", "parse_failed")),
    Indicator("recommendation_status", "推荐状态", None, "enum", writable_by=_PARSE,
              enum_values=("recommendable", "not_recommendable")),
)


# buyer_intent 指标：目前的消费方只有解析白名单与枚举校验（买家侧无注册表驱动
# 面板、无调研），所以 column + writable_by(parse) + enum_values 是被测试锁死的
# 部分；group 一律 None（无面板），label/kind 为将来建买家面板预留，best-effort。
_BI_PARSE = frozenset({"parse"})
_BI_EQUITY_TYPE = ("control_required", "consolidation_required", "minority_acceptable",
                   "minority_only", "flexible", "specific_range", "unknown")
_BI_LISTED = ("listed", "preparing_listing", "pre_ipo", "unlisted", "any", "unknown")

BUYER_INTENT_INDICATORS: tuple[Indicator, ...] = (
    Indicator("intent_summary", "需求摘要", None, "text", writable_by=_BI_PARSE),
    Indicator("raw_requirement_text", "原始需求", None, "text", writable_by=_BI_PARSE),
    Indicator("industry_primary", "行业原文（一级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industry_secondary", "行业原文（二级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industries_json", "关注行业", None, "json", writable_by=_BI_PARSE),
    Indicator("industry_focus_tags_json", "细分赛道", None, "json", writable_by=_BI_PARSE),
    Indicator("excluded_industries_json", "排除行业", None, "json", writable_by=_BI_PARSE),
    Indicator("region_scope_summary", "地域范围", None, "text", writable_by=_BI_PARSE),
    Indicator("min_revenue_yuan", "最低营收", None, "yuan", writable_by=_BI_PARSE),
    Indicator("min_net_profit_yuan", "最低净利润", None, "yuan", writable_by=_BI_PARSE),
    Indicator("min_total_profit_yuan", "最低利润总额", None, "yuan", writable_by=_BI_PARSE),
    Indicator("min_net_margin", "最低净利率", None, "ratio", writable_by=_BI_PARSE),
    Indicator("min_gross_margin", "最低毛利率", None, "ratio", writable_by=_BI_PARSE),
    Indicator("max_pe", "PE 上限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("max_ps", "PS 上限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("min_valuation_yuan", "最低估值", None, "yuan", writable_by=_BI_PARSE),
    Indicator("max_valuation_yuan", "最高估值", None, "yuan", writable_by=_BI_PARSE),
    Indicator("min_market_cap_yuan", "最低市值", None, "yuan", writable_by=_BI_PARSE),
    Indicator("max_market_cap_yuan", "最高市值", None, "yuan", writable_by=_BI_PARSE),
    Indicator("market_cap_range_summary", "市值范围", None, "text", writable_by=_BI_PARSE),
    Indicator("requires_control", "控股要求", None, "enum", writable_by=_BI_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("requires_consolidation", "并表要求", None, "enum", writable_by=_BI_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("accepts_minority_investment", "接受少数股权", None, "enum", writable_by=_BI_PARSE, enum_values=_YES_NO_LIKE),
    Indicator("equity_requirement_type", "股权诉求类型", None, "enum", writable_by=_BI_PARSE, enum_values=_BI_EQUITY_TYPE),
    Indicator("desired_equity_ratio_min", "期望股比下限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("desired_equity_ratio_max", "期望股比上限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("equity_ratio_summary", "股权比例", None, "text", writable_by=_BI_PARSE),
    Indicator("preferred_listed_status", "上市要求", None, "enum", writable_by=_BI_PARSE, enum_values=_BI_LISTED),
    Indicator("listing_board_requirement_summary", "上市板块要求", None, "text", writable_by=_BI_PARSE),
    Indicator("financing_stage_requirement_summary", "融资阶段要求", None, "text", writable_by=_BI_PARSE),
    Indicator("transaction_type", "交易方式", None, "text", writable_by=_BI_PARSE),
    Indicator("transaction_types_json", "交易方式（多值）", None, "json", writable_by=_BI_PARSE),
    Indicator("max_premium_rate", "溢价上限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("premium_tolerance_summary", "溢价要求", None, "text", writable_by=_BI_PARSE),
    Indicator("max_debt_ratio", "负债率上限", None, "ratio", writable_by=_BI_PARSE),
    Indicator("debt_ratio_requirement_summary", "负债率要求", None, "text", writable_by=_BI_PARSE),
    Indicator("major_risk_tolerance_summary", "风险容忍", None, "text", writable_by=_BI_PARSE),
    Indicator("buyer_industry_advantage_summary", "产业优势", None, "text", writable_by=_BI_PARSE),
    Indicator("priority_summary", "优先条件", None, "text", writable_by=_BI_PARSE),
    Indicator("preference_summary", "其他偏好", None, "text", writable_by=_BI_PARSE),
    Indicator("negative_summary", "排除项", None, "text", writable_by=_BI_PARSE),
    Indicator("unknown_summary", "待确认", None, "text", writable_by=_BI_PARSE),
    Indicator("status", "状态", None, "enum", writable_by=_BI_PARSE, enum_values=("active", "paused", "closed")),
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


def writable_columns(source: str, entity: str = "seller_target") -> set[str]:
    """Columns a given source (parse/research) may write."""
    return {ind.column for ind in indicators_for(entity) if source in ind.writable_by}


def screening_columns(entity: str = "seller_target") -> set[str]:
    return {ind.column for ind in indicators_for(entity) if ind.screening}


def writable_enum_values(entity: str = "seller_target") -> dict[str, set[str]]:
    """Valid enum keys per writable enum column, for write-time validation."""
    return {
        ind.column: set(ind.enum_values)
        for ind in indicators_for(entity)
        if ind.enum_values is not None
    }
