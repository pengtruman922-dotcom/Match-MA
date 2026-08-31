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
    # screening 2026-08-28 置 False（判决一的连带后果，**不是它降级了**）。
    # 它仍是唯一的标的行业事实源（总纲 §2.3 不变），仍然解析、仍然显示、
    # 仍然进深评 —— 变的是买家侧那三个行业条件本轮退役之后，**没有任何买家条件
    # 能再打在它上面**，它不再是一个可筛维度。
    # 标的侧的 screening 只喂信息页那个「筛」角标，角标撒谎的代价是顾问按它决定
    # 先补哪个字段、补错方向，所以这里必须跟着改。
    # 行业匹配整体交给 LLM 读业务摘要（正向 search_targets 的 business_scan、
    # 反向 skills/buyer-search 的接口一）。要恢复行业硬筛，两侧同时改回来。
    Indicator("industry_pairs_json", "所属行业", "business_product", "json", writable_by=_BOTH_MANUAL),
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

# 退役字段的可写来源。「退役」不是删列（阶段 A 一列没删），是**改标志位**：
# writable_by 去掉 parse 之后，字段从 _buyer_intent_field_contract() 生成的
# field_contract_json 里消失，模型再也看不到它、也就永远写不进来，
# extracted_action 的 apply 白名单同步收缩（两者本来就是同一个派生）。
# 列还在、存量数据还在、想恢复就是把这一个常量改回 _BI_WRITE。
#
# 留 manual 而不是清空，是为了过渡期还能人工修：阶段 B 删列之前，
# 存量值仍然可能需要有人去订正一条。
_BI_RETIRED = _MANUAL
# 解析中间产物与派生列退役后没有任何合法写入方：industry_primary /
# industry_secondary 是解析溯源（内容已并进 intent_business_summary），
# preferred_listed_status 由 acceptable_listed_status_json 单向计算，
# condition_effects_json 的三个消费方本轮全部拆掉。
_BI_RETIRED_READONLY: frozenset[str] = frozenset()

BUYER_INTENT_INDICATORS: tuple[Indicator, ...] = (
    Indicator("raw_requirement_text", "原始需求", None, "text", writable_by=_BI_PARSE),
    # ===== 业务方向：本单新建的三列，取代整套行业字典 =====
    #
    # 三列都**不设 target_column / operator / default_effect** —— 它们没有对手方，
    # 这正是判决一的含义。写法与 buyer_party 的业务标签/业务说明同构（总纲 §5）。
    #
    # 跨侧匹配需要共享词表，那是行业字典存在的唯一理由。买家需求放弃字典，
    # 等价于放弃「行业」这一维的 SQL 硬筛 —— 代价是**正向初筛不再有行业条件**，
    # 业务匹配整体交给 LLM 读文本（正向 search_targets 的 business_scan、
    # 反向 skills/buyer-search 的接口一）。这个代价是判断的一部分，不是漏了。
    #
    # 依据：实测买家需求人均只填 1.25 个一级行业、二级行业只有 21% 有值，
    # 而信息主要落在**不参与匹配的** industry_primary(92%) /
    # industry_secondary(73%) 两个原文列里 —— 字典今天已经没在承担业务匹配。
    Indicator("intent_business_tags_json", "需求业务标签", "intent_scope", "json", writable_by=_BI_WRITE, scenario_allowed=True, multi_value=True, editor="tags"),
    # **口径**：必须写清「要买什么样的业务」。它是反向检索首轮筛选唯一读的东西，
    # 写成「符合公司战略的优质标的」这种话，那条需求在反向里就等于不存在。
    Indicator("intent_business_summary", "需求业务说明", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True, editor="textarea"),
    # 排除方向必须让 LLM 看见：首轮筛是纯文本判断，排除项不进上下文就等于没有。
    Indicator("excluded_business_text", "排除业务方向", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True, editor="textarea"),
    # ===== 地区：两个平铺数组，保留省市区三级，去掉 effect 三态 =====
    #
    # 只填省 = 全省命中，填到市 = 只匹配那个市，三级逐级独立生效。
    # **空数组 = 不限**，不是「没有可接受地区」—— 反向检索里把空当成「不满足」
    # 会让一半以上的买家当场消失，这是反向最容易写错的一处。
    #
    # required 与 preferred 的区别（「必须在广东」对「优先广东」）不再进枚举，
    # 交给 region_scope_summary 的原话承载：语气和强度归文本，阈值和枚举归字段。
    Indicator("acceptable_regions_json", "可接受地区", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="location_province,location_city,location_district", operator="region_any", default_effect="preferred", scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="region_multi"),
    # 排除地区从 effect="excluded" 拆成独立列，语义写在列名里。
    # 算子是 region_none：命中即出局，与 region_any 严格互补。
    Indicator("excluded_regions_json", "排除地区", "intent_scope", "json", screening=True, writable_by=_BI_WRITE, target_column="location_province,location_city,location_district", operator="region_none", default_effect="required", scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="region_multi"),
    # 不参与匹配，但**不能退役**：它装的是两个地区数组装不下的语气
    # （「优先」「最好但非强制」「以…为主」）。去掉 effect 三态之后，
    # 强弱信息只剩这一列在承载，所以它比改造前更重要，不是更次要。
    Indicator("region_scope_summary", "地域摘要", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True, editor="text"),
    # 讲买家自身的产业背景，对业务匹配有用，进首轮召回的业务卡片。
    Indicator("buyer_industry_advantage_summary", "产业优势", "intent_scope", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # ===== 经营与财务：留下的都是**可比较的量** =====
    Indicator("min_revenue_yuan", "最低营收", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_revenue_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, sql_recall=True, deterministic_rank=True),
    Indicator("min_net_profit_yuan", "最低净利润", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_pe", "PE 上限", "intent_financial", "ratio", screening=True, writable_by=_BI_WRITE, target_column="pe_ratio", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("min_valuation_yuan", "最低估值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_valuation_yuan", "最高估值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    # 市值两条只有 9% 填充率，仍然保留 —— **填充率不是判据**。判据是「这一维是不是
    # 真实存在的收购条件」和「对手方有没有数据」：上市公司买上市公司时市值区间是
    # 硬约束，标的侧 market_cap_yuan 也确实有值可比。而 accepts_minority_investment
    # 填充率 38% 反而退役，因为它的对手方 70/71 是 unknown，带上它候选池只剩 1 家。
    Indicator("min_market_cap_yuan", "最低市值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="gte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("max_market_cap_yuan", "最高市值", "intent_financial", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="lte", default_effect="preferred", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    # unacceptable_risk_flags_json 的明细载体（能接受什么程度、什么前提下能接受）。
    # 枚举用于筛选，本列是明细，两者并存，不要合并。
    Indicator("major_risk_tolerance_summary", "风险容忍", "intent_financial", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # ===== 交易与能力要求 =====
    # 标的侧对手方有数据（can_control 44% / can_consolidate 41%），
    # 是少数真能筛掉东西的枚举，所以留。
    Indicator("requires_control", "控股要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="can_control", operator="requirement_capability", default_effect="required", effect_editable=True, scenario_allowed=True, sql_recall=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("requires_consolidation", "并表要求", "intent_deal", "enum", screening=True, writable_by=_BI_WRITE, target_column="can_consolidate", operator="requirement_capability", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("desired_equity_ratio_min", "期望股比下限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_max", operator="gte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("desired_equity_ratio_max", "期望股比上限", "intent_deal", "ratio", screening=True, writable_by=_BI_WRITE, target_column="transfer_ratio_min", operator="lte", default_effect="required", effect_editable=True, scenario_allowed=True, deterministic_rank=True),
    Indicator("acceptable_listed_status_json", "可接受上市状态", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="listed_status", operator="in", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_BI_LISTED_ACCEPTABLE),
    # 交易方式原文：存量取值混了三个正交轴，只有「交易结构」那一轴对得上标的侧
    # 闭集，支付方式与控制权诉求的信息只在这一列里活着。进深评，不参与匹配。
    Indicator("transaction_type", "交易方式原文", "intent_deal", "text", writable_by=_BI_WRITE, scenario_allowed=True),
    # 0817 刚建的两列，还没跑出数据，**不判早**：填充率低不是退役的理由，
    # 「维度不真实」或「对手方没有数据」才是。这两条两样都不占。
    Indicator("transaction_types_json", "可接受交易结构", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="acceptable_transaction_structures_json", operator="overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_TRANSACTION_STRUCTURES),
    # 三态由代码派生，不由 SQL 判（services/buyer_risk_tolerance.py）：
    #   []       未提及 → 不带这个条件
    #   四值全集  不接受全部（落库时展开）
    #   其余子集  不接受特定类型
    # SQL 不是裸 not_overlap：标的侧 [] 表示「未核查」，必须先出局，
    # 否则「没查过」会被当成「干净」。
    Indicator("unacceptable_risk_flags_json", "不接受的重大风险", "intent_deal", "json", screening=True, writable_by=_BI_WRITE, target_column="major_risk_flags_json", operator="not_overlap", default_effect="preferred", effect_editable=True, scenario_allowed=True, multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_UNACCEPTABLE_RISK_FLAGS),
    # ===== 系统列 =====
    # 需求级别与它的 E 细分原因，与标的侧同一套语义。status 从「需求状态」降级成
    # 「E 的细分原因」，取值不变，只是不再单独作为闸门。
    Indicator("intent_grade", "需求级别", None, "enum", writable_by=_BI_WRITE, enum_options=_GRADE),
    Indicator("status", "推荐状态", None, "enum", writable_by=_BI_PARSE, enum_options=_INTENT_STATUS),
    Indicator("pause_reason", "暂停原因", None, "text", writable_by=_BI_PARSE),

    # ================= 退役区（2026-08-28，阶段 A） =================
    #
    # 以下 32 列**仍然存在、存量数据仍然完好**，只是不再被解析写入、不再进初筛、
    # 不再显示在需求信息页（group=None）。删列在阶段 B，等 Railway 全部服务跑上
    # 本轮代码之后另开迁移 —— 一次 drop 22 列，任何一处投影漏改都会让整个需求
    # 列表页 500，而且是 preDeploy 跑完之后才炸，那时数据已经没了。
    #
    # **不要把这一块当成注释掉的死代码删掉。** 它是阶段 B 的 drop 清单，
    # 也是「这些列还在库里」这个事实的唯一声明处 —— 从注册表里整条拿掉，
    # 等于让写入校验、更新记录的中文名、调试投影一起失去它们。
    #
    # 每条保留 target_column / operator 是**有意的**（同 min_net_margin、max_ps
    # 在 0817 的处理）：比对契约本身没有变坏，坏的是「有没有数据可比」。
    # 哪天对手方有数据了，改回 screening=True 就是一行。
    # 例外是行业三件套 —— 它们的比对契约**是真的被解散了**，见下。

    # -- 行业六件套：合并进 intent_business_tags_json + intent_business_summary
    #    + excluded_business_text（判决一）。
    #
    # 这三条与其它退役字段不同，**连 target_column / operator 一起去掉**：
    # 判决一解散的正是「买家行业词 ↔ 标的 industry_pairs_json」这个跨侧契约本身，
    # 而不只是暂时停用。留着 target_column 会让
    # test_seller_screening_matches_who_points_at_it 继续认为标的侧
    # industry_pairs_json 有买家条件在读它，于是信息页那个「筛」角标继续显示 ——
    # 而实际上已经没有任何条件能打在它上面。角标撒谎的代价是顾问按它决定
    # 先补哪个字段，补错方向。所以标的侧 industry_pairs_json 的 screening
    # 同批置 False：它仍是唯一的标的行业事实源（总纲 §2.3 不变），
    # 仍然解析、仍然显示、仍然进深评，只是不再是一个筛选维。
    Indicator("industries_json", "可接受一级行业（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="industry"),
    Indicator("industry_l2_json", "二级关注行业（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="industry_l2"),
    Indicator("excluded_industries_json", "排除行业（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="industry"),
    Indicator("industry_focus_tags_json", "字典外细分方向（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="tags"),
    # 两个行业原文列是解析溯源，从来不参与匹配。内容已由迁移 022 带前缀并进
    # intent_business_summary（92% / 73% 有值，是本次最值钱的存量）。
    Indicator("industry_primary", "行业原文（一级，已退役）", None, "text", writable_by=_BI_RETIRED_READONLY),
    Indicator("industry_secondary", "行业原文（二级，已退役）", None, "text", writable_by=_BI_RETIRED_READONLY),

    # -- 地区：被 acceptable_regions_json / excluded_regions_json 取代（判决二）。
    #    契约一并去掉：新的两列已经指向同一组 location_* 列，留着是重复声明。
    Indicator("region_constraints_json", "可接受地区（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="region_multi"),

    # -- 摘要：并入 intent_business_summary。
    Indicator("intent_summary", "需求摘要（已退役）", None, "text", writable_by=_BI_RETIRED, editor="textarea"),

    # -- 条件强度（判决三）：整个退役。
    #
    # ⚠️ 注册表的注释会过期。这一条原来写着「只服务需求单链路：recommendation_flow.py
    # 用它把三道硬门槛按 effect 放宽」—— 全仓库 grep 后 recommendation_flow.py 里
    # **根本没有它**，那个消费方在阶段五 5B 拆旧链路时一起删了，注释没跟着改。
    # 退役前先 grep 确认，不要只信注释。
    #
    # 生产里只有 5/52 有值，活着的三个消费方（前端角标、深评上下文的
    # 「条件作用」、写入路径）没有一个是筛选。将来若要让 Agent 知道某个门槛硬不硬，
    # 那句话写进需求业务说明正文由 LLM 读 —— 与地区的「优先/必须」交给原话
    # 是同一个处理方式。
    Indicator("condition_effects_json", "条件作用（已退役）", None, "json", writable_by=_BI_RETIRED_READONLY),

    # -- 股权冗余两条。
    # accepts_minority_investment 38% 有值，仍然退役：标的侧对手方 70/71 是
    # unknown，按 requirement_capability 的语义（in ('yes','likely')）带上它
    # 候选池只剩 1 家，而它是 {parse, manual}，调研补不了，短期不会自己变好。
    Indicator("accepts_minority_investment", "接受少数股权（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="accepts_minority_investment", operator="requirement_capability", enum_options=_YES_NO_LIKE),
    # 解析中间产物：模型先判类型，再展开成 requires_control / requires_consolidation
    # 两个布尔更稳。语义与那两列重叠，留着只是多让模型判一次。
    Indicator("equity_requirement_type", "股权诉求类型（已退役）", None, "enum", writable_by=_BI_RETIRED, enum_options=_BI_EQUITY_TYPE),

    # -- 上市派生列：由 acceptable_listed_status_json 单向计算，本来就不可手写。
    Indicator("preferred_listed_status", "上市要求（兼容字段，已退役）", None, "enum", writable_by=_BI_RETIRED_READONLY, enum_options=_BI_LISTED),

    # -- 双侧皆空的比率与阈值。整段的共同点是「买家侧接近没人填 + 标的侧比不了」，
    #    每多留一个，模型每次解析都要判一次「这里有没有这个信息」。
    #    normalizer 提示词里最长的「百分比口径」那张表六行，其中四行
    #    （负债率上限 1/52、最低净利率 2/52、最低毛利率 1/52、溢价上限 0/52）
    #    合计只有 4 条真实数据 —— 精简换的是解析准确率。
    Indicator("min_net_margin", "最低净利率（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="current_net_profit_yuan/current_revenue_yuan", operator="gte"),
    Indicator("min_gross_margin", "最低毛利率（已退役）", None, "ratio", writable_by=_BI_RETIRED),
    Indicator("max_ps", "PS 上限（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="market_cap_yuan/current_revenue_yuan", operator="lte"),
    Indicator("max_debt_ratio", "负债率上限（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="current_debt_ratio", operator="lte"),
    # 可接受溢价范围是与买家预算、标的报价挂钩的计算值，与标的侧 premium_rate
    # 不同轴，硬比会得出错误结论 —— 它本来就没有 target_column。
    Indicator("max_premium_rate", "溢价上限（已退役）", None, "ratio", writable_by=_BI_RETIRED),
    Indicator("min_total_profit_yuan", "最低利润总额（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="current_total_profit_yuan", operator="gte"),

    # -- 双侧皆空的枚举。
    Indicator("acceptable_cash_flow_status_json", "可接受现金流状态（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="cash_flow_status", operator="in", multi_value=True, editor="multi_enum", enum_options=_CASH_FLOW),
    Indicator("acceptable_profitability_status_json", "可接受盈利状态（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="profitability_status", operator="in", multi_value=True, editor="multi_enum", enum_options=_PROFITABILITY),
    Indicator("listing_market_region", "上市地要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="listing_market_region", operator="eq", enum_options=_LISTING_EXCHANGE),

    # -- 交易能力五项：标的侧对手方 71/71 unknown，或已在迁移 016 删列。
    #    按 requirement_capability 的新语义它们返回 0 行，按旧语义（<> 'no'）
    #    它们恒真 —— 两种读法下都**从未筛掉过任何一家**。
    Indicator("requires_relocation", "迁址要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="accepts_relocation", operator="requirement_capability", enum_options=_REQUIREMENT_STRENGTH),
    Indicator("requires_return_investment", "返投要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="accepts_return_investment", operator="requirement_capability", enum_options=_REQUIREMENT_STRENGTH),
    Indicator("return_investment_multiple", "返投倍数（已退役）", None, "ratio", writable_by=_BI_RETIRED),
    Indicator("requires_team_retention", "团队留任要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="management_retention_possible", operator="requirement_capability", enum_options=_REQUIREMENT_STRENGTH),
    # 对赌是**谈判条款**不是标的的既有属性 —— 在 LOI 阶段定，不会写在标的材料里，
    # 这正是标的侧那一列建了就空、并在 016 删掉的原因。
    Indicator("earnout_requirement", "对赌要求（已退役）", None, "enum", writable_by=_BI_RETIRED, enum_options=_REQUIREMENT_STRENGTH),

    # -- 六段说明文字：内容改由各模块的「其他」（entity_profile_section）承接。
    #
    # **降级不等于丢信息**：深评读的是 buyer_intent_search_doc.full_text，
    # 而它已经把 profile_sections 拼进去了；normalizer 提示词也已经在教模型
    # 「装不进结构化字段的说法写进 profile_sections」。所以从「独立结构化列」
    # 降级成「其他里的一句话」之后深评侧零损失，只损失「能被 SQL 筛」——
    # 而它们本来就不参与筛选。
    #
    # group=None 在这里还有一个**必须的**副作用：
    # _remove_structured_profile_duplicates 只拿「有 group 且 default_effect 为空」
    # 的字段去删「其他」里的重复句子。这六列一旦 group=None，它们的存量值就不再
    # 参与去重，模型新写进「其他」的那句话才留得下来。
    Indicator("equity_ratio_summary", "股权比例说明（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("market_cap_range_summary", "市值范围说明（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("listing_board_requirement_summary", "上市板块要求（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("financing_stage_requirement_summary", "融资阶段要求（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("premium_tolerance_summary", "溢价要求（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("debt_ratio_requirement_summary", "负债率要求说明（已退役）", None, "text", writable_by=_BI_RETIRED),
)

# 阶段 B 的 drop 清单，从上面的退役声明派生 —— 不要另手写一份。
# 手写第二份的表现是「阶段 B 少删了一列」，而少删不报错，只会让那一列
# 永远留在库里没人知道它还在。
RETIRED_BUYER_INTENT_COLUMNS: tuple[str, ...] = tuple(
    indicator.column
    for indicator in BUYER_INTENT_INDICATORS
    if indicator.writable_by in (_BI_RETIRED, _BI_RETIRED_READONLY) and indicator.group is None
)

# 买家主体（0824 建）。它回答的是「这家买家自己是做什么的」，与 buyer_intent
# 的「这次想买什么」严格分开：主体资料在同一买家的所有需求间共享。
#
# section_code 与 key 同名只是占位：主体没有 entity_profile_section 补充栏
# （那张表只服务标的与买家需求），买家信息 tab 也不渲染补充栏。
BUYER_PARTY_GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("party_identity", "基本信息", "party_identity"),
    IndicatorGroup("party_business", "业务信息", "party_business"),
    IndicatorGroup("party_financial", "财务信息", "party_financial"),
    IndicatorGroup("party_other", "其他", "party_other"),
)

# 企业性质。央企与地方国企**合并为一档**（用户 0824 决定）：两者的区别落到
# business_summary 表达，不值得为它开一个取值。基金 / PE 也不设独立取值，
# 按其出资方性质选 —— 国资背景基金选国企，市场化基金选私企。
_OWNERSHIP_TYPE = (
    ("state_owned", "国企"),
    ("private", "私企"),
    ("foreign", "外企"),
    ("other", "其他"),
    ("unknown", "未知"),
)

# 联系人三列只能来自非公开渠道，**不含 research 是业务规则不是笔误**：
# 联系人、联系方式、我方对接人不该出现在买家调研的目标信息里。规则编码进
# writable_by 之后，调研节点直接用 writable_columns("research", "buyer_party")
# 就拿到正确的白名单，不需要另写一份手工排除清单（手写清单必然漂）。
_BP_CONTACT = _PARSE_MANUAL

BUYER_PARTY_INDICATORS: tuple[Indicator, ...] = (
    # 基本信息
    # AI 可以改名，但更新接口要走复核、旧名要进别名：改错了影响所有关联需求、
    # 撮合关系和搜索，**而且不会报错**，只会让人找不到东西（buyer_parties.py）。
    Indicator("buyer_name", "买家名称", "party_identity", "text", writable_by=_ALL),
    Indicator("location_province", "所在地", "party_identity", "text", writable_by=_ALL),
    Indicator("location_city", "所在市", "party_identity", "text", writable_by=_ALL, fold_into="location_province"),
    Indicator("location_district", "所在区", "party_identity", "text", writable_by=_ALL, fold_into="location_province"),
    Indicator("ownership_type", "企业性质", "party_identity", "enum", writable_by=_ALL, enum_options=_OWNERSHIP_TYPE),
    # 与标的侧共用同一个 _LISTED_STATUS / _LISTING_EXCHANGE，不要复制一份闭集。
    # 新列名叫 listing_exchange 不叫 listing_market_region：标的侧那个列名名不副实
    # （闭集其实是交易所），改名要动 25 处所以没改，新建的不继承这个债。
    Indicator("listed_status", "上市状态", "party_identity", "enum", writable_by=_ALL, enum_options=_LISTED_STATUS),
    # 需求原文里基本不会有股票代码，它是自动刷新的锚点，由调研补。
    Indicator("stock_code", "股票代码", "party_identity", "text", writable_by=_MANUAL | _RESEARCH),
    Indicator("listing_exchange", "上市地", "party_identity", "enum", writable_by=_MANUAL | _RESEARCH, enum_options=_LISTING_EXCHANGE),
    Indicator("contact_name", "联系人", "party_identity", "text", writable_by=_BP_CONTACT),
    Indicator("contact_info_json", "联系方式", "party_identity", "json", writable_by=_BP_CONTACT, editor="textarea"),
    # 我方对接人。用 text 不用外键：对接人可能没有系统账号。
    Indicator("our_contact_name", "我方对接人", "party_identity", "text", writable_by=_BP_CONTACT),
    # 业务信息 —— 产业协同度这一维的全部依据。
    Indicator("business_tags_json", "业务标签", "party_business", "json", writable_by=_ALL, editor="tags"),
    Indicator("business_summary", "业务说明", "party_business", "text", writable_by=_ALL, editor="textarea"),
    # 财务信息。四个列名与标的侧一字不差是刻意的：MONEY_YUAN_FIELDS 的万元/亿元
    # 归一、以及「核心财务事实必须带期间」的守卫都能直接复用。**不要改名。**
    Indicator("market_cap_yuan", "市值", "party_financial", "yuan", writable_by=_ALL),
    # 行情日期是机器给的确定日子，所以是 date；估值时点是人写的中文标签
    # （「2025年一季度」），所以是 text。只有 date 才能判断「这个市值过没过 7 天」，
    # 而自动刷新要靠这个判断。这个差异是刻意的，不要为了「统一」把它改成 text。
    Indicator("market_cap_as_of", "市值日期", "party_financial", "date", writable_by=_ALL, fold_into="market_cap_yuan"),
    Indicator("valuation_yuan", "估值", "party_financial", "yuan", writable_by=_ALL),
    Indicator("valuation_date", "估值时点", "party_financial", "text", writable_by=_ALL, fold_into="valuation_yuan"),
    Indicator("current_revenue_yuan", "营收", "party_financial", "yuan", writable_by=_ALL),
    Indicator("current_operating_cash_flow_yuan", "经营现金流", "party_financial", "yuan", writable_by=_ALL),
    # 营收与现金流共用一个期间标签：它们来自同一份定期报告。
    Indicator("financial_period_label", "财务期间", "party_financial", "text", writable_by=_ALL, fold_into="current_revenue_yuan"),
    # 风险或其他可能影响并购的企业重要信息，**进推荐上下文**。
    # 与 notes 的分工：notes 是运营备注，不进任何推荐上下文，保持原义不变。
    # 两者不要合并，否则运营备注会被送进 LLM。
    Indicator("supplementary_summary", "补充信息", "party_other", "text", writable_by=_ALL, editor="textarea"),
)

_BY_ENTITY: dict[str, tuple[Indicator, ...]] = {
    "seller_target": SELLER_TARGET_INDICATORS,
    "buyer_intent": BUYER_INTENT_INDICATORS,
    "buyer_party": BUYER_PARTY_INDICATORS,
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
    if entity == "buyer_party":
        return BUYER_PARTY_GROUPS
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


def buyer_intent_fact_columns() -> list[str]:
    """买家需求事实列的唯一清单，给各处 SELECT 拼投影用（0828 建）。

    同 seller_target_fact_columns / buyer_party_fact_columns 的道理，但**建它的
    直接动因是阶段 B**：本轮退役的 32 列要在下一轮 drop，而 industries_json 一列
    就被 34 个文件引用。手写投影下，删列漏改一处的表现是整个需求列表页 500，
    而且是 preDeploy 迁移跑完之后才炸 —— 那时数据已经没了。

    走这个函数之后，阶段 B 的动作变成「把注册表退役区那一块删掉」，
    所有 SELECT 投影自动跟着收缩。

    只含注册表声明的列。id、intent_name、contact_*、parsed_requirement_json、
    needs_confirmation_json、reviewed_* 这类系统列由调用方自己加，因为每处要的
    不一样；intent_grade / status / pause_reason 在注册表里，**不要再在调用处
    手工拼一份**，否则是重复列名、SQL 直接报错。
    """
    return [indicator.column for indicator in BUYER_INTENT_INDICATORS]


def buyer_party_fact_columns() -> list[str]:
    """买家主体事实列的唯一清单，给各处 SELECT 拼投影用。

    同 seller_target_fact_columns 的道理：详情页、列表、深评上下文、买家解析
    上下文、业务更新各读一次主体，手写投影时加一列漏改一处的表现是
    「字段存进去了但某条链路看不见」。0824 之前正是这样漏的 —— 删两列
    打断了四处手写 SELECT。

    只含注册表声明的列。id、aliases_json、notes、status、时间戳这类系统列
    由调用方自己加，因为每处要的不一样。
    """
    return [indicator.column for indicator in BUYER_PARTY_INDICATORS]
