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
    # 标的侧没录这个数时，这条买家条件怎么办。**这不是「必须/优先」的替代品** ——
    # 「这个买家有多想要」（default_effect，2026-09-01 删除）模型判不准、SQL 也
    # 从来没用过，那个角标写着「优先」而 screening_sql.py 照硬筛，是在骗人。
    # 本字段问的是另一件事：**「标的没录这个数」算不算「标的不达标」**。
    # 那是工程问题，有确定答案，答案取决于标的侧的录入率：
    #   exclude —— 缺的是真缺（营收 77%、净利 82%、上市状态 87%、省份 97%）
    #   keep    —— 缺的是数据不是资质（PE 56%、估值 38%、市值 11%），通过但标记未知
    # 实测 48 需求 x 71 标的：全部淘汰里 73% 是「标的没录这个数」造成的，
    # 其中市值/估值/PE 五项贡献约 1250 次误杀、仅 320 次真淘汰。
    missing_policy: str = "exclude"
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
    # ===== 业务与门槛整体搬去方案层（2026-09-01） =====
    #
    # 需求不再是一组字段，是一个容器挂 1..N 个互相独立、各自完整的方案。
    # 原来的 23 个业务/门槛列全部退役到本文件下方的退役区，等价声明移到
    # BUYER_INTENT_SCENARIO_INDICATORS。**取消公共层不是重构口味，是修 bug**：
    # 实测生产库公共层与方案层的取值冲突 11 个格子，广百股份的公共层挂着
    # 「估值上限 30 亿 + 地区山东/广东」，而它两个方案是「重奢奥莱项目」和
    # 「超市便利店」—— 那两条约束属于哪一个，原文里根本看不出来，
    # 公共层就是解析器猜不出归属时的兜底桶，现在两个方案都被压着。
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

    # -- 2026-09-01 方案化：需求侧 23 个业务/门槛列整体退役 --
    #
    # 它们的等价声明在 BUYER_INTENT_SCENARIO_INDICATORS 里，打在
    # buyer_intent_scenario 的真列上。这里保留声明是为了阶段 B 的 drop 清单，
    # 以及「这些列还在库里」这个事实的唯一声明处。
    #
    # 六条**不进方案层**，内容并入方案的 other_requirements_text：
    # 控股要求与并表要求（实测 48x71 全量对判：用得最多的两个字段，
    # 真淘汰 0 次，只在标的 can_control 没录时开火）、期望股比上下限
    # （标的侧 transfer_ratio 录入率 3%）、可接受交易结构（对手方录入率 1%）、
    # 不接受的重大风险（4%）、排除地区（真淘汰 0 次）。
    Indicator("intent_business_tags_json", "需求业务标签（已退役）", None, "json", writable_by=_BI_RETIRED, multi_value=True, editor="tags"),
    Indicator("intent_business_summary", "需求业务说明（已退役）", None, "text", writable_by=_BI_RETIRED, editor="textarea"),
    Indicator("excluded_business_text", "排除业务方向（已退役）", None, "text", writable_by=_BI_RETIRED, editor="textarea"),
    Indicator("acceptable_regions_json", "可接受地区（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="location_province,location_city,location_district", operator="region_any", multi_value=True, deterministic_rank=True, editor="region_multi"),
    Indicator("excluded_regions_json", "排除地区（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="location_province,location_city,location_district", operator="region_none", multi_value=True, deterministic_rank=True, editor="region_multi"),
    Indicator("region_scope_summary", "地域摘要（已退役）", None, "text", writable_by=_BI_RETIRED, editor="text"),
    Indicator("buyer_industry_advantage_summary", "产业优势（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("min_revenue_yuan", "最低营收（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="current_revenue_yuan", operator="gte", deterministic_rank=True),
    Indicator("min_net_profit_yuan", "最低净利润（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="current_net_profit_yuan", operator="gte", deterministic_rank=True),
    Indicator("max_pe", "PE 上限（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="pe_ratio", operator="lte", deterministic_rank=True),
    Indicator("min_valuation_yuan", "最低估值（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="valuation_yuan", operator="gte", deterministic_rank=True),
    Indicator("max_valuation_yuan", "最高估值（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="valuation_yuan", operator="lte", deterministic_rank=True),
    Indicator("min_market_cap_yuan", "最低市值（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="market_cap_yuan", operator="gte", deterministic_rank=True),
    Indicator("max_market_cap_yuan", "最高市值（已退役）", None, "yuan", writable_by=_BI_RETIRED, target_column="market_cap_yuan", operator="lte", deterministic_rank=True),
    Indicator("major_risk_tolerance_summary", "风险容忍（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("requires_control", "控股要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="can_control", operator="requirement_capability", deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("requires_consolidation", "并表要求（已退役）", None, "enum", writable_by=_BI_RETIRED, target_column="can_consolidate", operator="requirement_capability", deterministic_rank=True, enum_options=_YES_NO_LIKE),
    Indicator("desired_equity_ratio_min", "期望股比下限（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="transfer_ratio_max", operator="gte", deterministic_rank=True),
    Indicator("desired_equity_ratio_max", "期望股比上限（已退役）", None, "ratio", writable_by=_BI_RETIRED, target_column="transfer_ratio_min", operator="lte", deterministic_rank=True),
    Indicator("acceptable_listed_status_json", "可接受上市状态（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="listed_status", operator="in", multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_BI_LISTED_ACCEPTABLE),
    Indicator("transaction_type", "交易方式原文（已退役）", None, "text", writable_by=_BI_RETIRED),
    Indicator("transaction_types_json", "可接受交易结构（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="acceptable_transaction_structures_json", operator="overlap", multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_TRANSACTION_STRUCTURES),
    Indicator("unacceptable_risk_flags_json", "不接受的重大风险（已退役）", None, "json", writable_by=_BI_RETIRED, target_column="major_risk_flags_json", operator="not_overlap", multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_UNACCEPTABLE_RISK_FLAGS),
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


# ================= 买家需求方案（2026-09-01） =================
#
# 一条买家需求 = 一个容器挂 1..N 个**互相独立、各自完整**的方案，
# 命中任意一个即算命中这条需求。没有公共层。
#
# **拆分标准（提示词与人工都按这一条）**：把这个需求的各维度取值列出来 ——
# 业务、地区、上市状态、营收、净利、市值、估值、PE。如果任意组合都成立，
# 就是一个方案；如果存在「A 维度取了这个值，B 维度就必须取那个值」的绑定，
# 就按绑定拆。**单个字段多值不算绑定** —— 湖北农发的十来个农业赛道配
# 「规模灵活，从四五亿估值到五十亿都看」，任一组合都成立，是一个方案。
# 岭南商旅的酒店/旅游/粮油食品，拿酒店的业务配粮油的财务门槛不成立，拆三个。
#
# **轴不固定。** 生产里北大健康按上市状态、广晟按业务板块、盐业按交易结构、
# 广百按业务方向。代码和提示词都不得预设「按上市/非上市拆」。
#
# **拿不准就拆。** 两个方向代价不对称：拆多了每个方案门槛更少、召回更宽；
# 该拆没拆，不兼容的条件被 AND 在一起（上市 AND 非上市 = 空集），直接筛出零条。
BUYER_INTENT_SCENARIO_GROUPS: tuple[IndicatorGroup, ...] = (
    IndicatorGroup("scenario_business", "要买什么", "scenario_business"),
    IndicatorGroup("scenario_threshold", "门槛", "scenario_threshold"),
)

BUYER_INTENT_SCENARIO_INDICATORS: tuple[Indicator, ...] = (
    # ===== 要买什么 =====
    #
    # 方案**不设名称**（label 列保留但停止写入）。摘要就是标题，它同时承担三个
    # 职责：界面上这个方案的标题、反向检索 skill 第一层扫描读的材料、
    # 业务匹配判断的主材料。
    #
    # **口径**：一段话说清这个方案要买什么业务、什么地域、什么规模。
    # 不写成条目列表，也不写成「符合公司战略的优质标的」这种话 ——
    # 那样写，这个方案在反向检索里就等于不存在。
    #
    # 不再单设「业务说明」：022 之后 intent_business_summary 中位只有 54 字，
    # 跟标签列表差不多长，再设一个跨业务与门槛的摘要，两个文本字段必然互相抄。
    Indicator("scenario_summary", "摘要", "scenario_business", "text", writable_by=_BI_WRITE, editor="textarea"),
    Indicator("business_tags_json", "业务标签", "scenario_business", "json", writable_by=_BI_WRITE, multi_value=True, editor="tags"),
    # 排除方向必须让 LLM 看见：首轮筛是纯文本判断，排除项不进上下文就等于没有。
    Indicator("excluded_business_text", "排除方向", "scenario_business", "text", writable_by=_BI_WRITE, editor="textarea"),

    # ===== 门槛 =====
    #
    # 名字从「可接受地区」改成「要求地区」，因为它是硬要求。
    # 「广东优先」「优先大湾区」这类偏好**不进这一列**，进 other_requirements_text ——
    # 实测 36 家买家原话里提到地域的 16 家中有 9 家说的是「优先/最好」，
    # 填进硬筛会把外地的好标的直接筛掉。
    # 空数组 = 不限，不是「没有要求地区」。
    Indicator("required_regions_json", "要求地区", "scenario_threshold", "json", screening=True, writable_by=_BI_WRITE, target_column="location_province,location_city,location_district", operator="region_any", multi_value=True, deterministic_rank=True, editor="region_multi"),
    Indicator("acceptable_listed_status_json", "上市状态", "scenario_threshold", "json", screening=True, writable_by=_BI_WRITE, target_column="listed_status", operator="in", multi_value=True, deterministic_rank=True, editor="multi_enum", enum_options=_BI_LISTED_ACCEPTABLE),
    # 缺失即出局的四项：标的侧录入率 77%/82%/87%/97%，缺的是真缺。
    Indicator("min_revenue_yuan", "最低营收", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_revenue_yuan", operator="gte", sql_recall=True, deterministic_rank=True),
    Indicator("min_net_profit_yuan", "最低净利润", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="current_net_profit_yuan", operator="gte", deterministic_rank=True),
    # 缺失不出局的五项：标的侧 PE 56%、估值 38%、市值 11%，缺的是数据不是资质。
    # 它们按现行「缺失即出局」语义会贡献约 1250 次误杀、只换来 320 次真淘汰。
    Indicator("max_pe", "PE 上限", "scenario_threshold", "ratio", screening=True, writable_by=_BI_WRITE, target_column="pe_ratio", operator="lte", missing_policy="keep", deterministic_rank=True),
    Indicator("min_market_cap_yuan", "最低市值", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="gte", missing_policy="keep", deterministic_rank=True),
    Indicator("max_market_cap_yuan", "最高市值", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="market_cap_yuan", operator="lte", missing_policy="keep", deterministic_rank=True),
    Indicator("min_valuation_yuan", "最低估值", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="gte", missing_policy="keep", deterministic_rank=True),
    Indicator("max_valuation_yuan", "最高估值", "scenario_threshold", "yuan", screening=True, writable_by=_BI_WRITE, target_column="valuation_yuan", operator="lte", missing_policy="keep", deterministic_rank=True),
    # 结构化字段装不下的约束全在这里：偏好语气、交易结构、控股与并表、股比、
    # 迁址、团队留任、返投、对赌、负债率、净利率、溢价、市场地位、风险清单。
    # **是 AI 归纳，不是原话** —— 保留全部约束信息，去掉冗余表达。
    # 它不参与初筛，进深评与反向检索的第二层。
    Indicator("other_requirements_text", "其他要求", "scenario_threshold", "text", writable_by=_BI_WRITE, editor="textarea"),
)

# 方案表的事实列：投影、搜索文档、skill 都从这里取，不要手写第二份。
def buyer_intent_scenario_fact_columns() -> list[str]:
    return [indicator.column for indicator in BUYER_INTENT_SCENARIO_INDICATORS]


_BY_ENTITY: dict[str, tuple[Indicator, ...]] = {
    "seller_target": SELLER_TARGET_INDICATORS,
    "buyer_intent": BUYER_INTENT_INDICATORS,
    "buyer_party": BUYER_PARTY_INDICATORS,
    "buyer_intent_scenario": BUYER_INTENT_SCENARIO_INDICATORS,
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
    if entity == "buyer_intent_scenario":
        return BUYER_INTENT_SCENARIO_GROUPS
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
