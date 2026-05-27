# Match-MA 一期字段收敛草案 v0.1

状态：讨论草案  
范围：将 `seller_target` 和 `buyer_intent` 从完整数据模型收敛为一期可落地字段。本文用于辅助后续 PostgreSQL schema v0.1 设计，不是最终 DDL。

---

## 1. 收敛原则

### 1.1 一期主表只放高频、稳定、可展示、可筛选字段

主表字段应优先满足：

- 列表页展示。
- 详情页顶部摘要。
- 高频筛选和排序。
- 推荐候选池初筛。
- 常用统计。
- 与买家意向高频条件一一对应。

不建议把所有信息都塞进主表。

### 1.2 复杂、低频、多值字段拆表或 JSONB

以下信息不建议一期全部主表化：

- 多年度财务明细。
- 多个产品 / 资质 / 客户 / 赛道标签。
- 多条风险记录。
- 多个区域点位。
- 买家复杂 OR 条件。
- 推荐过程临时判断。
- 长文本摘要和证据。

处理方式：

```text
多值结构化信息 -> 子表
半结构化信息 -> JSONB / tag 表
长文本信息 -> summary text / search_doc
复杂规则 -> buyer_intent_constraint
```

### 1.3 seller_target 存事实，buyer_intent 存需求

两者字段语义对应，但不是完全同构。

```text
seller_target = 标的实际情况
buyer_intent = 买家希望什么
buyer_intent_constraint = 具体规则和判断方式
```

例如：

| 业务项 | seller_target | buyer_intent / constraint |
| --- | --- | --- |
| 利润 | 当前净利润 2500 万 | 净利润 >= 2000 万 |
| 区域 | 标的经营地浙江 | 长三角 hard，浙江 preference |
| PE | PE = 12.8 | PE <= 13，unknown 降权 |
| 并表 | 可并表未知 | 要并表，unknown 标记缺口 |

### 1.4 字段分级

本文使用以下分级：

| 分级 | 含义 |
| --- | --- |
| P0 | 一期必须主表字段，影响核心流程、列表、推荐或状态 |
| P1 | 一期建议字段，可提升推荐质量，但可为空 |
| P2 | 二期或扩展字段，一期可以 JSONB / 文本 / 子表承接 |
| Derived | 派生 / 计算字段，不一定人工录入 |
| Child | 子表字段，不放主表 |
| Constraint | 买家意向规则字段，放 `buyer_intent_constraint` |

---

## 2. `seller_target` 一期主表字段收敛

### 2.1 P0：一期必须主表字段

| 字段 | 中文 | 列表展示 | 筛选/排序 | LLM推荐 | 高影响 | 需要来源 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `id` | 标的 ID | 是 | 是 | 是 | 否 | 否 | 系统生成 |
| `team_id` | 团队 ID | 否 | 是 | 否 | 否 | 否 | 权限隔离预留 |
| `workspace_id` | 数据空间 ID | 否 | 是 | 否 | 否 | 否 | 部门 / 项目组 / 数据空间隔离 |
| `target_name` | 标的名称 | 是 | 是 | 是 | 是 | 是 | 最小建档必填 |
| `target_type` | 标的类型 | 是 | 是 | 是 | 是 | 是 | 公司标的/股权包/业务线/资产包等 |
| `seller_party_id` | 卖方主体 | 可选 | 是 | 是 | 是 | 是 | 可为空，但建议尽量关联 |
| `owner_user_id` | 负责人 | 是 | 是 | 否 | 否 | 否 | 默认当前用户 |
| `recommendation_status` | 推荐状态 | 是 | 是 | 是 | 是 | 是 | 可推荐/暂不推荐 |
| `information_status` | 信息状态 | 是 | 是 | 是 | 否 | 否 | 信息不足/待确认/解析中等 |
| `industry_primary` | 一级行业 | 是 | 是 | 是 | 是 | 是 | 字典化 |
| `industry_secondary` | 二级行业 | 是 | 是 | 是 | 是 | 是 | 字典化，可为空 |
| `registered_province` | 注册省份 | 可选 | 是 | 是 | 否 | 是 | 注册地，默认非主要匹配依据 |
| `registered_city` | 注册城市 | 可选 | 是 | 是 | 否 | 是 | 注册地 |
| `headquarter_province` | 总部省份 | 是 | 是 | 是 | 否 | 是 | 推荐区域匹配重要字段 |
| `headquarter_city` | 总部城市 | 是 | 是 | 是 | 否 | 是 | 推荐区域匹配重要字段 |
| `operating_regions_json` | 经营区域 | 是 | 是 | 是 | 否 | 是 | 多区域，JSONB |
| `listed_status` | 上市状态 | 是 | 是 | 是 | 是 | 是 | 上市/非上市/拟上市/未知 |
| `current_revenue_yuan` | 当前营收 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `current_net_profit_yuan` | 当前净利润 | 是 | 是 | 是 | 是 | 是 | 高频匹配字段 |
| `financial_period_label` | 财务期间 | 是 | 是 | 是 | 否 | 是 | 例如 2024、TTM |
| `valuation_yuan` | 估值 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `asking_price_yuan` | 报价 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `pe_ratio` | PE | 是 | 是 | 是 | 是 | 是 | 可用户输入/材料披露/计算 |
| `pe_source_type` | PE 来源类型 | 可选 | 是 | 是 | 否 | 是 | user_input/document/calculated/research |
| `is_for_sale` | 是否还卖 | 是 | 是 | 是 | 是 | 是 | true/false/unknown |
| `can_control` | 是否可控股 | 是 | 是 | 是 | 是 | 是 | true/false/unknown/likely |
| `can_consolidate` | 是否可并表 | 是 | 是 | 是 | 是 | 是 | true/false/unknown/likely |
| `transfer_ratio_min` | 可转让比例下限 | 可选 | 是 | 是 | 是 | 是 | 数字明确时填写 |
| `transfer_ratio_max` | 可转让比例上限 | 可选 | 是 | 是 | 是 | 是 | 数字明确时填写 |
| `transfer_ratio_text` | 可转让比例说明 | 是 | 否 | 是 | 是 | 是 | 例如“控股权可谈” |
| `business_summary` | 业务摘要 | 是 | 全文 | 是 | 否 | 是 | 标的事实摘要 |
| `transaction_summary` | 交易摘要 | 是 | 全文 | 是 | 是 | 是 | 卖方诉求、交易结构 |
| `risk_summary` | 风险摘要 | 是 | 全文 | 是 | 是 | 是 | 结构化风险另见 risk 表 |
| `gap_summary` | 信息缺口摘要 | 是 | 否 | 是 | 否 | 否 | 系统生成/人工可编辑 |
| `last_business_update_at` | 最近业务更新 | 是 | 是 | 否 | 否 | 否 | 列表排序 |
| `created_at` / `updated_at` | 创建/更新时间 | 是 | 是 | 否 | 否 | 否 | 通用字段 |
| `deleted_at` | 删除时间 | 否 | 是 | 否 | 否 | 否 | soft delete |

### 2.2 P1：一期建议主表字段

| 字段 | 中文 | 列表展示 | 筛选/排序 | LLM推荐 | 高影响 | 需要来源 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `listing_board` | 上市板块 | 可选 | 是 | 是 | 是 | 是 | 主板/创业板/科创板/北交所 |
| `market_cap_yuan` | 市值 | 可选 | 是 | 是 | 是 | 是 | 上市公司需求高频 |
| `current_total_profit_yuan` | 利润总额 | 可选 | 是 | 是 | 是 | 是 | 国资需求常用 |
| `current_assets_yuan` | 资产总额 | 可选 | 是 | 是 | 是 | 是 | 部分需求要求资产规模 |
| `current_debt_ratio` | 负债率 | 可选 | 是 | 是 | 是 | 是 | 风险/财务约束 |
| `current_operating_cash_flow_yuan` | 经营现金流 | 可选 | 是 | 是 | 是 | 是 | 现金流稳定需求 |
| `profitability_status` | 盈利状态 | 可选 | 是 | 是 | 是 | 是 | 持续盈利/亏损/未知 |
| `cash_flow_status` | 现金流状态 | 可选 | 是 | 是 | 是 | 是 | 稳定/不稳定/未知 |
| `operation_stability_status` | 经营稳定性 | 可选 | 是 | 是 | 是 | 是 | 稳定/待确认/异常 |
| `accepts_minority_investment` | 是否接受参股 | 可选 | 是 | 是 | 是 | 是 | true/false/unknown/likely |
| `transfer_flexibility_type` | 转让灵活度类型 | 可选 | 是 | 是 | 是 | 是 | control_available 等 |
| `control_path_options_json` | 控制路径选项 | 可选 | 否 | 是 | 是 | 是 | 表决权委托/一致行动等 |
| `consolidation_path_summary` | 并表路径说明 | 可选 | 全文 | 是 | 是 | 是 | 非数字化说明 |
| `deal_paths_json` | 可接受交易路径 | 可选 | 是 | 是 | 是 | 是 | 股转/增资/借壳等 |
| `accepted_payment_methods_json` | 可接受支付方式 | 可选 | 是 | 是 | 是 | 是 | 现金/股份/混合 |
| `accepts_relocation` | 是否接受迁址 | 可选 | 是 | 是 | 是 | 是 | 招商类需求重要 |
| `acceptable_relocation_regions_json` | 可接受迁址区域 | 可选 | 是 | 是 | 是 | 是 | 可为空 |
| `accepts_return_investment` | 是否接受返投/固投 | 可选 | 是 | 是 | 是 | 是 | 招商需求重要 |
| `management_team_summary` | 管理团队摘要 | 可选 | 全文 | 是 | 否 | 是 | 团队稳定/保留管理层 |
| `management_retention_possible` | 是否可保留团队 | 可选 | 是 | 是 | 是 | 是 | true/false/unknown |
| `earnout_dependency_status` | 对赌依赖状态 | 可选 | 是 | 是 | 是 | 是 | none/low/high/unknown |
| `completeness_score` | 信息完整度 | 可选 | 是 | 是 | 是 | 否 | 系统计算 |

### 2.3 P2：不建议一期放主表的字段

| 信息 | 建议位置 | 原因 |
| --- | --- | --- |
| 多年度财务 | `seller_target_financial` | 多期间、多口径，不适合主表 |
| 风险明细 | `seller_target_risk` | 风险需类型、状态、等级、来源 |
| 细分赛道 | `seller_target_tag` + 摘要 | 多值、别名多 |
| 产品 | `seller_target_tag` + 摘要 | 多值、自由文本多 |
| 资质认证 | `seller_target_tag` + 摘要 | 多值、证据定位重要 |
| 主要客户 | tag / JSONB / summary | 客户敏感且多值 |
| 生产基地详细信息 | JSONB / 后续子表 | 一期可只存 `production_regions_json` |
| 资产所在地明细 | JSONB / 后续子表 | 资产包场景再细化 |
| 诉讼、环保、冻结、执行等 | `seller_target_risk` | 推荐硬排除需要结构化 |
| 字段来源 | `field_value_source` | 不放主表 |
| 证据片段 | `evidence_span` | 不放主表 |
| 搜索全文 | `seller_target_search_doc` | 检索专用 |

### 2.4 seller_target 一期建议主表最小集合

如果要进一步压缩，一期最小主表可以是：

```text
id
team_id
workspace_id
target_name
target_type
seller_party_id
owner_user_id
recommendation_status
information_status
industry_primary
industry_secondary
registered_province
registered_city
headquarter_province
headquarter_city
operating_regions_json
listed_status
current_revenue_yuan
current_net_profit_yuan
financial_period_label
valuation_yuan
asking_price_yuan
pe_ratio
pe_source_type
is_for_sale
can_control
can_consolidate
transfer_ratio_min
transfer_ratio_max
transfer_ratio_text
business_summary
transaction_summary
risk_summary
gap_summary
last_business_update_at
created_at
updated_at
deleted_at
```

---

## 3. `buyer_intent` 一期字段收敛

### 3.1 buyer_intent 主表定位

`buyer_intent` 主表是一张“买家意向卡”。

它主要用于：

- 买家意向列表展示。
- 详情页摘要。
- 推荐页加载默认上下文。
- 高频筛选。
- 快速理解买家要什么。

复杂规则不全部塞入主表，而是进入：

```text
buyer_intent_constraint
```

主表可以理解为“摘要和常用字段”，constraint 是“规则明细”。

### 3.2 P0：一期必须主表字段

| 字段 | 中文 | 列表展示 | 筛选/排序 | LLM推荐 | 高影响 | 需要来源 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `id` | 买家意向 ID | 是 | 是 | 是 | 否 | 否 | 系统生成 |
| `team_id` | 团队 ID | 否 | 是 | 否 | 否 | 否 | 权限隔离预留 |
| `workspace_id` | 数据空间 ID | 否 | 是 | 否 | 否 | 否 | 部门 / 项目组 / 数据空间隔离 |
| `buyer_party_id` | 买家主体 | 是 | 是 | 是 | 否 | 否 | 可为空 |
| `owner_user_id` | 负责人 | 是 | 是 | 否 | 否 | 否 | 默认当前用户 |
| `intent_name` | 意向名称 | 是 | 是 | 是 | 是 | 是 | 例如“医药健康并表需求” |
| `status` | 意向状态 | 是 | 是 | 是 | 是 | 是 | 继续推荐/暂停推荐 |
| `pause_reason` | 暂停原因 | 可选 | 是 | 是 | 否 | 是 | 暂停时填写 |
| `contact_name` | 意向联系人 | 是 | 是 | 否 | 否 | 否 | 可为空 |
| `raw_requirement_text` | 原始需求 | 详情 | 全文 | 是 | 是 | 是 | LLM 解析依据 |
| `intent_summary` | 意向摘要 | 是 | 全文 | 是 | 是 | 是 | 列表和推荐上下文 |
| `parsed_requirement_json` | 解析结果 JSON | 否 | 否 | 是 | 是 | 是 | 保存 LLM 完整解析 |
| `industry_primary` | 一级行业 | 是 | 是 | 是 | 是 | 是 | 常用主行业 |
| `industry_secondary` | 二级行业 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `region_scope_summary` | 区域摘要 | 是 | 全文 | 是 | 是 | 是 | 例如“长三角，浙江优先” |
| `min_revenue_yuan` | 最低营收 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `min_net_profit_yuan` | 最低净利润 | 是 | 是 | 是 | 是 | 是 | 高频字段 |
| `max_pe` | PE 上限 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `max_valuation_yuan` | 估值上限 | 是 | 是 | 是 | 是 | 是 | 可为空 |
| `requires_control` | 是否要求控股 | 是 | 是 | 是 | 是 | 是 | true/false/unknown |
| `requires_consolidation` | 是否要求并表 | 是 | 是 | 是 | 是 | 是 | true/false/unknown |
| `preferred_listed_status` | 偏好上市状态 | 是 | 是 | 是 | 是 | 是 | 上市/非上市/不限/未知 |
| `transaction_type` | 交易类型 | 是 | 是 | 是 | 是 | 是 | 控股/参股/资产收购等摘要 |
| `negative_summary` | 负面清单摘要 | 是 | 全文 | 是 | 是 | 是 | 风险排除摘要 |
| `last_recommendation_at` | 最近推荐时间 | 是 | 是 | 否 | 否 | 否 | 列表排序 |
| `last_business_update_at` | 最近更新时间 | 是 | 是 | 否 | 否 | 否 | 列表排序 |
| `created_at` / `updated_at` | 创建/更新时间 | 是 | 是 | 否 | 否 | 否 | 通用字段 |
| `deleted_at` | 删除时间 | 否 | 是 | 否 | 否 | 否 | soft delete |

### 3.3 P1：一期建议主表字段

| 字段 | 中文 | 列表展示 | 筛选/排序 | LLM推荐 | 高影响 | 需要来源 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `contact_info_json` | 联系方式 | 详情 | 否 | 否 | 否 | 否 | 可选 |
| `region_constraints_json` | 区域规则快照 | 否 | 可选 | 是 | 是 | 是 | LLM 展开结果，可与 constraint 同步 |
| `min_total_profit_yuan` | 最低利润总额 | 可选 | 是 | 是 | 是 | 是 | 国资需求常用 |
| `market_cap_range_summary` | 市值范围摘要 | 可选 | 全文 | 是 | 是 | 是 | 上市公司需求 |
| `desired_equity_ratio_min` | 拟收购比例下限 | 可选 | 是 | 是 | 是 | 是 | 数字明确时填写 |
| `desired_equity_ratio_max` | 拟收购比例上限 | 可选 | 是 | 是 | 是 | 是 | 数字明确时填写 |
| `equity_ratio_summary` | 收购比例说明 | 是 | 全文 | 是 | 是 | 是 | 例如“51%以上”“可并表即可” |
| `equity_requirement_type` | 股权要求类型 | 可选 | 是 | 是 | 是 | 是 | control_required 等 |
| `accepts_minority_investment` | 是否接受参股 | 可选 | 是 | 是 | 是 | 是 | true/false/unknown/conditional |
| `acceptable_control_paths_json` | 可接受控制路径 | 可选 | 否 | 是 | 是 | 是 | 表决权委托/一致行动等 |
| `priority_summary` | 优先级摘要 | 是 | 全文 | 是 | 否 | 是 | 例如现金流优先、产业协同其次 |
| `preference_summary` | 偏好摘要 | 是 | 全文 | 是 | 否 | 是 | 技术壁垒/资质/出口等 |
| `unknown_summary` | 待确认摘要 | 是 | 全文 | 是 | 否 | 否 | LLM 解析出的缺口 |

### 3.4 buyer_intent 一期建议主表最小集合

```text
id
team_id
workspace_id
buyer_party_id
owner_user_id
intent_name
status
pause_reason
contact_name
raw_requirement_text
intent_summary
parsed_requirement_json
industry_primary
industry_secondary
region_scope_summary
min_revenue_yuan
min_net_profit_yuan
max_pe
max_valuation_yuan
requires_control
requires_consolidation
preferred_listed_status
transaction_type
negative_summary
last_recommendation_at
last_business_update_at
created_at
updated_at
deleted_at
```

---

## 4. `buyer_intent_constraint` 字段收敛

### 4.1 constraint 的业务定位

`buyer_intent_constraint` 是“买家意向规则库”。

它用于：

- 把自然语言需求变成可执行规则。
- 区分硬条件、偏好和未知。
- 决定未知字段如何处理。
- 支持复杂 OR 条件。
- 支持风险排除。
- 支持推荐理由生成。
- 支持后续意向更新建议。

主表是“意向卡片”，constraint 是“规则明细”。

### 4.2 一期必须支持的 constraint 类型

| 业务规则 | field 示例 | operator 示例 | 备注 |
| --- | --- | --- | --- |
| 行业 | `industry` | `in` / `exclude` | 可对应行业字典 |
| 细分赛道 | `sector` | `in` / `preferred_in` / `exclude` | 可对应 tag |
| 产品 | `product` | `in` / `preferred_in` | 半结构化 |
| 区域 | `operating_region` | `in` / `preferred_in` | LLM 展开省市 |
| 注册地 | `registered_region` | `in` | 买家明确要求时使用 |
| 上市状态 | `listed_status` | `=` / `in` | 上市/非上市 |
| 上市板块 | `listing_board` | `in` | 主板/创业板等 |
| 营收 | `revenue_yuan` | `>=` / `between` | 数值规则 |
| 净利润 | `net_profit_yuan` | `>=` / `between` | 高频规则 |
| 利润总额 | `total_profit_yuan` | `>=` | 可选 |
| 估值 | `valuation_yuan` | `<=` / `between` | 可选 |
| PE | `pe_ratio` | `<=` / `between` | 高频规则 |
| 市值 | `market_cap_yuan` | `between` / `<=` | 上市公司需求 |
| 负债率 | `debt_ratio` | `<=` | 可选 |
| 控股 | `can_control` | `=` | true/false/unknown |
| 并表 | `can_consolidate` | `=` | true/false/unknown |
| 收购比例 | `equity_ratio` | `between` / `>=` / `<=` | 数字明确时使用 |
| 交易方式 | `deal_path` | `in` / `preferred_in` | 股转/增资/借壳等 |
| 支付方式 | `payment_method` | `in` / `preferred_in` | 现金/股份/混合 |
| 迁址 | `relocation` | `=` | 招商类需求 |
| 返投/固投 | `return_investment` | `=` | 招商类需求 |
| 风险排除 | `risk` | `exclude` | 诉讼/环保/冻结等 |
| 团队稳定 | `team_stability` | `=` / `preferred` | 偏好为主 |
| 对赌依赖 | `earnout_dependency` | `exclude` / `preferred` | 可选 |

### 4.3 constraint 字段建议

```text
id
team_id
buyer_intent_id
field
operator
value_json
unit
scope
normalized_key
constraint_type
unknown_policy
weight
raw_text
source_type
source_id
confidence
review_status
created_at
created_by
updated_at
updated_by
```

新增说明：

| 字段 | 说明 |
| --- | --- |
| `scope` | 约束作用对象，例如 operating_region / registered_region |
| `value_json` | 存结构化值，例如区域展开、省市列表、数值区间 |
| `normalized_key` | 字典化 key，例如 healthcare.medical_device |
| `constraint_type` | hard / preference / unknown |
| `unknown_policy` | allow_but_flag_gap / allow_but_deprioritize / exclude / ask_user |
| `weight` | 偏好权重，可后续用于排序 |
| `raw_text` | 原始表述，便于解释和复核 |

### 4.4 constraint 示例

#### 区域：长三角 hard，浙江 preference

```json
{
  "field": "operating_region",
  "operator": "in",
  "value_json": {
    "raw_text": "长三角",
    "expanded_regions": ["上海市", "江苏省", "浙江省", "安徽省"],
    "scope": "operating_region"
  },
  "constraint_type": "hard",
  "unknown_policy": "allow_but_flag_gap"
}
```

```json
{
  "field": "operating_region",
  "operator": "preferred_in",
  "value_json": {
    "raw_text": "浙江省内优先",
    "expanded_regions": ["浙江省"],
    "scope": "operating_region"
  },
  "constraint_type": "preference",
  "weight": 0.8
}
```

#### 利润：2000 万以上

```json
{
  "field": "net_profit_yuan",
  "operator": ">=",
  "value_json": 20000000,
  "unit": "yuan",
  "constraint_type": "hard",
  "unknown_policy": "allow_but_deprioritize"
}
```

#### PE：原则不超过 13

```json
{
  "field": "pe_ratio",
  "operator": "<=",
  "value_json": 13,
  "constraint_type": "preference",
  "unknown_policy": "allow_but_deprioritize",
  "raw_text": "PE 原则上不超过 13 倍"
}
```

#### 并表：必须并表，但未知可提示

```json
{
  "field": "can_consolidate",
  "operator": "=",
  "value_json": true,
  "constraint_type": "hard",
  "unknown_policy": "allow_but_flag_gap",
  "raw_text": "要并表"
}
```

#### 风险：排除涉诉、冻结、执行、违规违法

```json
{
  "field": "risk",
  "operator": "exclude",
  "value_json": {
    "risk_types": ["litigation", "asset_freeze", "enforcement", "regulatory_violation"],
    "risk_status": ["confirmed_present", "suspected"],
    "min_severity": "medium"
  },
  "constraint_type": "hard",
  "unknown_policy": "allow_but_flag_gap"
}
```

---

## 5. 一期轻量证据字段策略

### 5.1 哪些字段需要来源

原则：

```text
影响推荐判断、交易判断、风险判断的字段都需要来源。
```

必须需要来源的字段：

- 行业。
- 区域。
- 上市状态。
- 营收。
- 利润。
- 估值。
- 报价。
- PE。
- 是否还卖。
- 是否可控股。
- 是否可并表。
- 可转让比例。
- 交易方式。
- 风险。
- 资质。
- 重大客户。

可不强制来源的字段：

- 系统 ID。
- 负责人。
- 创建时间。
- 信息状态。
- 系统计算字段。
- 信息缺口摘要。

### 5.2 轻量版效果

一期轻量版证据目标：

```text
用户能回答：这个字段从哪里来的？
```

示例：

```text
净利润：2500 万
来源：2024审计报告.pdf / P12
更新时间：2026-05-26
状态：已确认
[查看来源]
```

点击后：

```text
字段：净利润
当前值：2500 万
来源文件：2024审计报告.pdf
页码：P12
证据片段：公司2024年度实现净利润人民币2500万元……
提取方式：附件解析
确认人：张三
确认时间：2026-05-26 14:20
```

人工录入示例：

```text
报价：3.5 亿
来源：张三手动输入
来源说明：与项目方电话沟通确认
更新时间：2026-05-26
```

系统计算示例：

```text
PE：14.0
来源：系统计算
计算依据：报价 3.5 亿 / 净利润 2500 万
```

### 5.3 一期不做的复杂证据功能

一期暂不做：

- PDF 坐标框 bbox 高亮。
- Word 段落精确定位。
- Excel 单元格强定位。
- 多证据冲突图谱。
- 文档全文高亮。

一期先做到：

```text
附件名 + 页码 / sheet + 文本片段 + 来源说明
```

---

## 6. search_doc 一期策略

### 6.1 建议一期做实体表

建议一期保留实体表：

```text
seller_target_search_doc
buyer_intent_search_doc
```

用途：

- 全文检索。
- pgvector 语义召回。
- 标签文本召回。
- 候选池构建。
- 推荐 Trace 调试。

已确认：

```text
向量检索用于语义召回和兜底召回，不用于硬条件判断。
```

一期 embedding 建议：

```text
模型：阿里云 text-embedding-v4
维度：1024
```

说明：

- `text-embedding-v4` 支持指定维度，默认 1024。
- 一期固定 1024，避免不同维度混用。
- `search_doc` 表保存 `embedding_model` 和 `embedding_dim`。
- 未来需要多模型或多维度时，再拆独立 embedding 表。

### 6.2 与动态 evidence pack 的分工

推荐采用：

```text
实体 search_doc 用于检索召回；
服务层动态 evidence pack 用于最终 LLM 推荐。
```

流程：

```text
结构化筛选
↓
search_doc 全文/向量召回
↓
候选池合并去重
↓
服务层读取最新主表/风险/关系/证据
↓
组装 evidence pack
↓
LLM 最终推荐和解释
```

向量适合的文本：

- 标的业务摘要。
- 细分赛道 / 产品描述。
- 附件摘要。
- 联网调研摘要。
- 买家意向长文本。
- 历史反馈摘要。

向量不适合的判断：

- 利润 / PE / 估值等数值比较。
- 地区硬条件。
- 是否可并表。
- 是否已不感兴趣。
- 风险硬排除。
- 权限隔离。

### 6.3 为什么不只动态生成

只动态生成的问题：

- 慢。
- 难建向量索引。
- 难复现召回原因。
- 每次推荐重复拼装文本。
- 候选池规模大时成本高。

但动态 evidence pack 仍然需要，用于保证最终推荐看到最新事实。

---

## 7. 一期业务更新三张表必须落地

已确认一期落地：

```text
business_update
extracted_action
action_application_log
```

三者职责：

| 表 | 解决的问题 |
| --- | --- |
| `business_update` | 用户原始输入是什么 |
| `extracted_action` | AI 从原文中拆出了哪些待复核动作 |
| `action_application_log` | 用户确认后，系统实际改了哪些字段 |

这三张表支撑：

- 统一业务更新。
- 字段变更历史。
- 详情页更新记录 tab。
- AI 拆解结果复核。
- 审计和回滚。

---

## 8. 当前确认与下一步

当前已确认：

1. `seller_target` P0 字段可作为一期主表快照字段基线，暂不继续强压缩。
2. `buyer_intent` P0 字段用于买家意向列表、条件抽屉和推荐候选池生成。
3. `constraint` 一期采用白名单，LLM 输出 filter DSL / constraint，服务端校验并转 SQL。
4. `risk_type` 一期保持开放 text，同时 seed P0 风险字典用于归一化和买家负面清单解析。
5. 行业一级字典采用轻量非穷尽版本，覆盖当前买家意向合集中的高频方向；二级行业和长尾赛道允许保留原文或待归一化。
6. 区域别名配置一期落表，覆盖“长三角、江浙沪、江浙、珠三角、沿海发达地区”等常见表达。
7. `yes / no / unknown / likely` 作为交易状态类字段的统一四值表达。
8. PostgreSQL schema v0.1 和初始 migration 已开始固化。

下一步建议：进入后端工程骨架和 ORM/Alembic 设计，或基于真实样本先做字段抽取与推荐评测集。
