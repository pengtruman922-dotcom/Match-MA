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


# 「技术与团队」解散于 2026-08-07：全库 70 个标的里团队可留任 3 个、管理团队 0 个，
# 而它的两个字段说的其实是「交易能力」不是「技术」—— 团队可留任的买家对手方
# requires_team_retention 就在买家的「交易与能力要求」模块里。字段归位到 deal_terms，
# 该栏的画像内容（产能、资质、技术路线）并入产业优势。
GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("identity", "身份与地区", "identity"),
    IndicatorGroup("business_product", "业务与产品", "business_product"),
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
# 问卷第 6 项「能否接受标的公司有重大风险」把风险类型枚举好了，照抄即可。
# 三种状态由同一个字段表达：[] 未核查 / ["none"] 已核查无风险 / 其余已核查有风险。
_MAJOR_RISK_FLAGS = (
    ("litigation", "涉诉"),
    ("equity_frozen", "股权冻结"),
    ("enforcement", "被执行"),
    ("violation", "违规违法"),
    ("none", "已核查无重大风险"),
)
# 买家侧「不接受的重大风险」：_MAJOR_RISK_FLAGS 的 4 值子集。none 是「核查状态」
# 不是「风险类型」，「不接受已核查无风险」讲不通，所以它不进买家侧。
# 配对审计按「子集」档校验（差集只允许 unknown 或状态值），不是等号。
_UNACCEPTABLE_RISK_FLAGS = (
    ("litigation", "涉诉"),
    ("equity_frozen", "股权冻结"),
    ("enforcement", "被执行"),
    ("violation", "违规违法"),
)
# 问卷第 7 项「交易方式（多选）」。与控股维度（can_control / can_consolidate /
# accepts_minority_investment）正交：增资扩股可以控股也可以参股，股权转让同理。
# 两个维度都要留，不能互相派生。
_TRANSACTION_STRUCTURES = (
    ("equity_transfer", "股权转让（老股）"),
    ("capital_increase", "增资扩股（新股）"),
    ("asset_purchase", "资产收购"),
    ("merger", "吸收合并"),
    ("other", "其他"),
)
_PE_SOURCE = (("user_input", "人工录入"), ("document", "文件"), ("calculated", "计算"), ("research", "调研"), ("unknown", "未知"))
# 上市地：2026-08-07 从「境内/境外」换成具体交易所。旧枚举在生产里完全空转 ——
# 买家侧 44 个需求全是 NULL，标的侧 16 个有值且全部 domestic，只有一个取值在用。
# 列名仍叫 listing_market_region（改名要动 25 处，而列名不出现在界面上）。
# `unknown` 与 NULL 不同：前者是「查过但不确定在哪上市」，后者是「没查过」。
_LISTING_EXCHANGE = (
    ("sse", "上交所"),
    ("szse", "深交所"),
    ("bse", "北交所"),
    ("hkex", "港交所"),
    ("nyse", "纽交所"),
    ("nasdaq", "纳斯达克"),
    ("other", "其他"),
    ("unknown", "未知"),
)
_REQUIREMENT_STRENGTH = (
    ("required", "必须满足"),
    ("preferred", "优先满足"),
    ("not_required", "不作要求"),
    ("unknown", "需要确认"),
)
# 级别是推荐初筛的唯一闸门：E 不进推荐，A-D 进。A-D 之间**不影响**召回与排序
# （所以不设 screening / deterministic_rank），只服务筛选与人工优先级。
# 字母没有中文别名，两列共用同一个闭集。
_GRADE = (("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"))
# E 的细分原因。级别与原因严格双向绑定，由 services/entity_grade.py 单点派生，
# DB 的 chk_*_grade_* 约束兜底。
_LIFECYCLE_STATUS = (("active", "在售中"), ("sold", "已售出"), ("off_market", "已停售"))
_INTENT_STATUS = (("active", "持续推荐"), ("paused", "暂停推荐"), ("closed", "结束推荐"))


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
    # 行业只到 L2：「做锂电池正极材料的」与「做锂电池 PACK 的」归在同一个 L2 下。
    # 产品词是长尾，建受控字典的维护成本无上限且字典外的词会被丢弃，所以走自由
    # 文本 + 深评。买家侧对手方是已存在的 industry_focus_tags_json（语义配对）。
    # 不塞进 business_summary：后者有 300 字上限，塞进去会被截断。
    Indicator("main_products_text", "主要产品", "business_product", "text", writable_by=_BOTH_MANUAL),
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
    #
    # 解析也要能写：解析是标的的主要入口，只给 research 会让「防止旧期覆盖新期」
    # 与同期冲突判定对解析写入的数据全部失效。
    Indicator("financial_period_end_date", "财务期间截止日", "ops_quality", "date", writable_by=_RESEARCH | _PARSE, fold_into="financial_period_label"),
    Indicator("profitability_status", "盈利状态", "ops_quality", "enum", screening=True, writable_by=_ALL, enum_options=_PROFITABILITY),
    Indicator("cash_flow_status", "现金流状态", "ops_quality", "enum", screening=True, writable_by=_ALL, enum_options=_CASH_FLOW),
    # 交易属性
    Indicator("listed_status", "上市状态", "deal_terms", "enum", screening=True, writable_by=_BOTH_MANUAL, enum_options=_LISTED_STATUS),
    Indicator("stock_code", "股票代码", "deal_terms", "text", writable_by=_BOTH_MANUAL),
    Indicator("listing_market_region", "上市地", "deal_terms", "enum", screening=True, writable_by=_MANUAL | _RESEARCH, enum_options=_LISTING_EXCHANGE),
    Indicator("market_cap_yuan", "市值", "deal_terms", "yuan", screening=True, writable_by=_ALL),
    Indicator("valuation_yuan", "估值", "deal_terms", "yuan", screening=True, writable_by=_ALL),
    Indicator("valuation_date", "估值时间", "deal_terms", "date", writable_by=_ALL),
    Indicator("asking_price_yuan", "报价", "deal_terms", "yuan", writable_by=_PARSE_MANUAL),
    Indicator("asking_price_date", "报价时间", "deal_terms", "date", writable_by=_PARSE_MANUAL),
    Indicator("pe_ratio", "PE", "deal_terms", "ratio", screening=True, writable_by=_ALL),
    Indicator("pe_source_type", "PE 口径", "deal_terms", "enum", writable_by=_ALL, enum_options=_PE_SOURCE),
    Indicator("premium_rate", "溢价率", "deal_terms", "ratio", writable_by=_PARSE_MANUAL),
    Indicator("transfer_ratio_min", "出售比例", "deal_terms", "ratio", screening=True, writable_by=_PARSE_MANUAL),
    Indicator("transfer_ratio_max", "出售比例上限", "deal_terms", "ratio", screening=True, writable_by=_PARSE_MANUAL, fold_into="transfer_ratio_min"),
    Indicator("transfer_ratio_text", "出售比例说明", "deal_terms", "text", writable_by=_PARSE_MANUAL, fold_into="transfer_ratio_min"),
    Indicator("can_control", "可控股", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("can_consolidate", "可并表", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("accepts_minority_investment", "接受少数股权", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("accepts_relocation", "接受迁址", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    Indicator("accepts_return_investment", "接受返投", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    # 团队可留任说的是「交易能力」不是「技术」：它的对手方 requires_team_retention
    # 就在买家的「交易与能力要求」模块里，两侧模块必须对齐。
    Indicator("management_retention_possible", "团队可留任", "deal_terms", "enum", screening=True, writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    # 0817 接线：买家侧 transaction_types_json 已改成同一个闭集并声明了
    # operator="overlap"，这一列因此第一次有了对手方，screening 转 True。
    Indicator("acceptable_transaction_structures_json", "可接受交易结构", "deal_terms", "json", screening=True, writable_by=_PARSE_MANUAL, enum_options=_TRANSACTION_STRUCTURES, multi_value=True),
    Indicator("transaction_summary", "交易摘要", "deal_terms", "text", writable_by=_PARSE_MANUAL),
    # 出售诉求
    Indicator("is_for_sale", "是否还卖", "deal_terms", "enum", writable_by=_PARSE_MANUAL, enum_options=_YES_NO_LIKE),
    # 风险的可筛选投影；risk_summary 继续承担明细（哪个案子、金额多少、进展如何），
    # 两者的关系与 industry_pairs_json ↔ 画像栏一致。
    # 调研可写是有意的：工商公开信息正是调研 Agent 最擅长核的，存量标的的风险
    # 只能靠它回填。0817 接线：买家侧 unacceptable_risk_flags_json 已建，
    # screening 转 True。注意它的 SQL 不是裸 not_overlap ——「未核查」（[]）必须
    # 先出局，否则「没查过」会被当成「干净」，见方案 0817 §4.1。
    Indicator("major_risk_flags_json", "重大风险", "deal_terms", "json", screening=True, writable_by=_ALL, enum_options=_MAJOR_RISK_FLAGS, multi_value=True),
    Indicator("risk_summary", "风险摘要", "deal_terms", "text", writable_by=_ALL),
    # 标的级别与它的 E 细分原因。0814 起两者都进注册表：以前 lifecycle_status 是
    # 「系统列特例」，在 handlers/common.py 开白名单、在 extracted_action_apply.py
    # 自己拼 UPDATE 和审计日志，绕过 field_writer 的校验与来源记录。进来之后校验、
    # 审计、模型词汇表、回滚清单全部自动覆盖。group=None 所以不进信息页模块
    # （meta.py 只渲染 group is not None 的指标）。
    Indicator("target_grade", "标的级别", None, "enum", writable_by=_PARSE_MANUAL, enum_options=_GRADE),
    Indicator("lifecycle_status", "交易状态", None, "enum", writable_by=_PARSE_MANUAL, enum_options=_LIFECYCLE_STATUS),
    # 系统状态不是信息页业务事实，不允许手动编辑。
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
    # 行业原文两列是解析溯源，**不参与任何匹配**：结构化的对手方是
    # industries_json / industry_l2_json。group=None 所以信息页也不显示它们。
    Indicator("industry_primary", "行业原文（一级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industry_secondary", "行业原文（二级）", None, "text", writable_by=_BI_PARSE),
    Indicator("industries_json", "可接受一级行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json.l1", operator="overlap", default_effect="required", effect_editable=True, scenario_allowed=True, multi_value=True, sql_recall=True, deterministic_rank=True, editor="industry"),
    Indicator("industry_l2_json", "二级关注行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json.l2", operator="overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="industry_l2"),
    Indicator("excluded_industries_json", "排除行业", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="industry_pairs_json", operator="not_overlap", default_effect="required", effect_editable=False, scenario_allowed=True, multi_value=True, sql_recall=True, deterministic_rank=True, editor="industry"),
    # 深评项，不进初筛：标的侧对手方 main_products_text 是自由文本，两侧粒度
    # 也对不上（实测标签从「能源/电力」粗到「钙钛矿/异质结光伏组件材料」细）。
    # 解析必须**先试二级行业字典**，能落进字典的一律进 industry_l2_json，
    # 只有字典里确实没有的才进这里 —— 倒进自由标签等于让它在推荐里失效。
    Indicator("industry_focus_tags_json", "字典外细分方向", "intent_scope", "json", writable_by=_BI_WRITE, scenario_allowed=True, multi_value=True, editor="tags"),
    # 不参与匹配，但**不能退役**：它装的是 region_constraints_json 装不下的语气
    # （「优先」「最好但非强制」「以…为主」），深评要读。解析必须两者同时产出 ——
    # 实测 30/44 有摘要而只有 5/44 有结构化约束，那 25 条地域要求在推荐里
    # 完全不存在，这是买家侧最大的单点召回损失。
    Indicator("region_scope_summary", "地域摘要（兼容）", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True, editor="text"),
    Indicator("region_constraints_json", "可接受地区", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="location_province,location_city,location_district", operator="region_any", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="region_multi"),
    Indicator("min_revenue_yuan", "最低营收", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_revenue_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, sql_recall=True, deterministic_rank=True),
    Indicator("min_net_profit_yuan", "最低净利润", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_total_profit_yuan", "最低利润总额", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_total_profit_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    # **口径警告**：本列存百分数（实测 8.0 / 1.0），而 target_column 现算出来是
    # 分数（0.1692）。SQL 模板必须把标的侧 ×100 再比，否则这个条件筛出来
    # 恒为空集且不报错。注册表这一层表达不了单位，所以写在这里。
    Indicator("min_net_margin", "最低净利率", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan/current_revenue_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    # 不进初筛（0817）：标的侧没有毛利率列，也没有营业成本可推算，而买家侧只有
    # 1/44 填了 —— 缺失即出局下，这一条会把那个需求的候选池直接打成 0。
    # default_effect 保留：它表达的是**需求单链路的规则打分强度**，与「进不进
    # 初筛」是两件事（后者由 screening 表达）。要做毛利率就是「标的列 + 买家
    # 条件 + 解析提示词」一次做齐，不能只留买家侧。
    Indicator("min_gross_margin", "最低毛利率", "intent_financial", "ratio", writable_by=_BI_WRITE, default_effect="preferred", effect_editable=True, scenario_allowed=True),
    Indicator("max_pe", "PE 上限", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="pe_ratio", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    # 移出初筛（0817）：**声明的** target_column 只认 market_cap_yuan，而它只有
    # 上市标的有（11/71）—— 缺失即出局下一带就把非上市那一半整体打空。
    # 需求单打分器另有一套手写口径（market_cap 缺就退回 valuation，
    # recommendation_flow.py:2543），那条路继续有效，所以 default_effect 保留。
    # 想让 PS 进初筛，要先让 target_column 表达得了 coalesce，那是算子语法的事。
    Indicator("max_ps", "PS 上限", "intent_financial", "ratio", writable_by=_BI_WRITE, target_column="market_cap_yuan/current_revenue_yuan", operator="lte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
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
    # 算子与对手方本来就声明好了，0817 只补 screening。**代价要知道**：标的侧
    # 70/71 是 unknown，按 requirement_capability 的新语义（in ('yes','likely')）
    # 这个条件一带只剩 1 家；而它是 {parse, manual}，调研补不了。
    Indicator("accepts_minority_investment", "接受少数股权", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="accepts_minority_investment", operator="requirement_capability", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    # 解析中间产物，不参与匹配：模型先判类型，再展开成 requires_control /
    # requires_consolidation / accepts_minority_investment 三个布尔更稳。
    # 语义与那三列重叠是有意的，不要试图让它自己去筛。
    Indicator("equity_requirement_type", "股权诉求类型", "intent_deal", "enum", writable_by=_BI_WRITE, scenario_allowed=True, enum_options=_BI_EQUITY_TYPE),
    Indicator("desired_equity_ratio_min", "期望股比下限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_max", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("desired_equity_ratio_max", "期望股比上限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_min", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("equity_ratio_summary", "股权比例说明", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("acceptable_listed_status_json", "可接受上市状态", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="listed_status", operator="in", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_BI_LISTED_ACCEPTABLE),
    # 派生列，由 _legacy_listed_status() 从 acceptable_listed_status_json 单向
    # 计算（buyer_intents.py），**不可手写、不参与匹配**。
    Indicator("preferred_listed_status", "上市要求（兼容字段）", None, "enum", writable_by=_BI_PARSE, enum_options=_BI_LISTED),
    # 单值 eq，与标的侧同一个闭集。「A股都行」这种说法要多值 overlap，
    # 但改 operator 就是改筛选契约，跟接线那一轮一起做。
    Indicator("listing_market_region", "上市地要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="listing_market_region", operator="eq", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_LISTING_EXCHANGE),
    # 三条能力项 0817 移出初筛：标的侧 accepts_relocation / accepts_return_investment
    # 全库 71/71 都是 unknown，management_retention_possible 只有 3 个 yes ——
    # 按 requirement_capability 的新语义它们返回 0 行，按旧语义（<> 'no'）它们
    # 恒真，两种读法下都**从未筛掉过任何一家**。
    # 列、成对关系、target_column、operator 全部保留：等标的侧有数据了，
    # 改回 screening=True + default_effect="preferred" 就是一行。
    # 这三列是 {parse, manual}，调研补不了，所以短期内不会自己变好。
    Indicator("requires_relocation", "迁址要求", "intent_deal", "enum", writable_by=_BI_WRITE, target_column="accepts_relocation", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("requires_return_investment", "返投要求", "intent_deal", "enum", writable_by=_BI_WRITE, target_column="accepts_return_investment", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    Indicator("requires_team_retention", "团队留任要求", "intent_deal", "enum", writable_by=_BI_WRITE, target_column="management_retention_possible", operator="requirement_capability", default_effect="preferred", scenario_allowed=True, deterministic_rank=True, enum_options=_REQUIREMENT_STRENGTH),
    # 对赌：两侧都归深评（0817）。标的侧 earnout_dependency_status 已在迁移 016
    # 删除（删前 0/70），买家侧 43/44 是 unknown。它是**谈判条款**不是标的的既有
    # 属性 —— 在 LOI 阶段定，不会写在标的材料里，这正是标的侧那一列建了就空的原因。
    # 保留本列供深评阅读，**不参与匹配**，也不要再为它新建标的列。
    Indicator("earnout_requirement", "对赌要求", "intent_deal", "enum", writable_by=_BI_WRITE, scenario_allowed=True, enum_options=_REQUIREMENT_STRENGTH),
    # 返投整条链路已降级，本列 0/44，不再作为多方案字段。
    Indicator("return_investment_multiple", "返投倍数", "intent_deal", "ratio", writable_by=_BI_WRITE),
    Indicator("listing_board_requirement_summary", "上市板块要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("financing_stage_requirement_summary", "融资阶段要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # 交易方式原文（0817 从「兼容标量」改判）：迁移 018 把 transaction_types_json
    # 重写成闭集之前，先把原数组的中文原话存进这里。存量取值混了三个正交轴，
    # 只有「交易结构」那一轴对得上标的侧闭集，支付方式（全现金/换股/现金+股份）
    # 与控制权诉求（控股收购/少数股权）在标的侧没有对手方列 —— 它们的信息
    # 只在这一列里活着，进深评，不参与匹配。
    Indicator("transaction_type", "交易方式原文", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # 与标的侧共用同一个 _TRANSACTION_STRUCTURES，不要复制一份闭集。
    Indicator("transaction_types_json", "可接受交易结构", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="acceptable_transaction_structures_json", operator="overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_TRANSACTION_STRUCTURES),
    # 买家不接受的重大风险（0817 新建）。标的侧对手方是 major_risk_flags_json。
    # **三态由代码派生，不由 SQL 判**（services/buyer_risk_tolerance.py）：
    #   []       未提及 → 不带这个条件
    #   四值全集  不接受全部（落库时展开）
    #   其余子集  不接受特定类型
    # SQL 不是裸 not_overlap：标的侧 [] 表示「未核查」，必须先出局，
    # 否则「没查过」会被当成「干净」。见方案 0817 §4.1。
    # default_effect 取 preferred 而非 required：标的侧只有 2/71 有值，
    # 当硬条件会直接把候选池打空；靠调研回填（本列对手方 writable_by 含 research）。
    Indicator("unacceptable_risk_flags_json", "不接受的重大风险", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="major_risk_flags_json", operator="not_overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_UNACCEPTABLE_RISK_FLAGS),
    # 不进初筛（用户 0817 拍板）：可接受溢价范围是与买家预算、标的估值/报价挂钩的
    # 计算值，与标的侧 premium_rate 不同轴，硬比会得出错误结论。归深评。
    # 注册表**不给它 operator / target_column**，所以它物理上进不了筛选 schema。
    Indicator("max_premium_rate", "溢价上限", "intent_deal", "ratio", writable_by=_BI_WRITE, default_effect="preferred", effect_editable=True, scenario_allowed=True),
    Indicator("premium_tolerance_summary", "溢价要求", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("debt_ratio_requirement_summary", "负债率要求说明", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # unacceptable_risk_flags_json 的明细载体，关系与标的侧
    # risk_summary ↔ major_risk_flags_json 完全同构：枚举用于筛选，本列是明细
    # （能接受什么程度、什么前提下能接受）。两者并存，不要合并。
    Indicator("major_risk_tolerance_summary", "风险容忍", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    Indicator("buyer_industry_advantage_summary", "产业优势", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # **只服务需求单链路**：recommendation_flow.py 用它把 industries_json /
    # min_revenue_yuan / requires_control 三道硬门槛按 effect 放宽。
    # 对话链路不读它 —— 那边的条件强度由解析节点输出的 strength 承载，
    # 由主 Agent 的调用策略表达。两套强度表达并存是有意为之。
    Indicator("condition_effects_json", "条件作用", None, "json", writable_by=_BI_WRITE),
    # 需求级别与它的 E 细分原因，与标的侧同一套语义。status 从「需求状态」降级成
    # 「E 的细分原因」，取值不变，只是不再单独作为闸门。
    Indicator("intent_grade", "需求级别", None, "enum", writable_by=_BI_WRITE, enum_options=_GRADE),
    Indicator("status", "推荐状态", None, "enum", writable_by=_BI_PARSE, enum_options=_INTENT_STATUS),
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


def multi_value_enum_values(entity: str = "seller_target") -> dict[str, set[str]]:
    """闭集多值列的合法元素取值。

    与 writable_enum_values 的区别只在形状：这些列存的是数组，归一化时要逐个
    元素过字典而不是整体比对。买家侧原来在 handlers/common.py 手写了两项，
    标的侧新增闭集列时没人会想起去补那份手写表——所以改成从注册表派生。
    """
    return {
        indicator.column: {code for code, _ in indicator.enum_options}
        for indicator in indicators_for(entity)
        if indicator.enum_options is not None and indicator.multi_value
    }


# 注册表之外、但要跟着事实列一起被读出来的 seller_target 列。
# industry_l1 / industry_l2 是 industry_pairs_json 的兼容投影（总纲 §2.3），
# gap_summary 是零写入的历史列（判死待办，六处读路径仍在，见施工单 0806 §三）。
_SELLER_TARGET_EXTRA_FACT_COLUMNS: tuple[str, ...] = (
    "industry_l1",
    "industry_l2",
    "gap_summary",
)


def seller_target_fact_columns() -> list[str]:
    """标的事实列的唯一清单，给各处 SELECT 拼投影用。

    以前信息页、解析、采纳、业务更新各手写一份，加一列要逐个改，漏掉任何一处
    的表现都是「字段存进去了但某个页面/某条链路看不见」，最难查。列名来自注册表
    不是外部输入，可以安全拼接（同 handlers/common.py 的 _fetch_seller_targets）。

    只含注册表声明的列。id、时间戳、owner 这类系统列由调用方自己加，因为每处要的
    不一样；级别与交易状态 0814 起在注册表里，**不要再在调用处手工拼一份**，否则
    是重复列名、SQL 直接报错。
    """
    return [indicator.column for indicator in SELLER_TARGET_INDICATORS] + list(
        _SELLER_TARGET_EXTRA_FACT_COLUMNS
    )
