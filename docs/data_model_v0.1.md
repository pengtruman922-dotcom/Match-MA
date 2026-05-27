# Match-MA 数据模型与核心表结构草案 v0.1

状态：讨论草案  
范围：围绕已确认的核心业务边界，先定义标的、买家意向、买家-标的关系、推荐会话与结果的数据库模型。本文不是最终 SQL DDL，后续表结构、字段类型、索引和迁移脚本仍需继续细化。

---

## 1. 已确认的数据建模原则

### 1.1 标的管理对象是 `seller_target`

系统管理目标是标的项目：

```text
seller_target = 标的项目 / 推荐对象 / 跟进对象
seller_party  = 卖方主体 / 公司主体
```

一个卖方主体可能有多个标的项目。

示例：

```text
seller_party：某集团 / 某公司主体
  ├─ seller_target A：出售公司股权
  ├─ seller_target B：出售某条业务线
  └─ seller_target C：出售某资产包
```

因此：

- 标的管理页管理 `seller_target`，不是管理主体。
- 推荐结果指向 `seller_target`。
- 买家-标的关系指向 `seller_target`。
- 附件、字段证据、更新记录优先归属 `seller_target`。
- `seller_party` 是主体主数据，用于去重、归并和多项目关联。

### 1.2 主表存当前快照，历史统一留痕

已确认：

```text
seller_target 主表只存当前快照。
历史变化统一放 business_update / extracted_action / action_application_log。
```

例如：

```text
seller_target.asking_price_yuan = 当前报价
```

历史变化：

```text
报价：3 亿 → 3.5 亿
是否还卖：未知 → 仍愿意卖
净利润：未知 → 2500 万
```

进入：

```text
business_update
extracted_action
action_application_log
```

只有后续确实需要频繁分析趋势的字段，再考虑独立 history 表。

### 1.3 高频检索字段结构化，复杂信息保留 JSONB 和文本

总体原则：

```text
硬条件交给数据库，模糊匹配交给召回，复杂权衡交给 LLM。
```

数据层采用：

```text
结构化字段 + 标签字典 + 别名体系 + 全文检索 + 向量召回 + LLM rerank
```

字段分层：

| 类型 | 存储方式 | 典型字段 |
| --- | --- | --- |
| 高频硬筛字段 | 主表列 / constraint 表 | 地区、行业一级/二级、利润、PE、是否并表、推荐状态 |
| 半标准化字段 | 标签表 + 原文 + 说明 | 细分赛道、产品、资质、客户类型、能力标签 |
| 复杂非结构化信息 | 文本 / JSONB / search doc | 业务摘要、调研摘要、历史沟通、推荐理由 |

### 1.4 AI 输出默认是建议，不等于事实

AI 解析、抽取、分类后的结果先进入：

```text
extracted_action
```

默认状态为：

```text
pending_review
```

已确认：

- 高影响字段默认待复核。
- 低风险字段可自动写入，但必须保留来源、证据和可编辑能力。
- 用户接受、编辑后接受、忽略都需要记录日志。

### 1.5 推荐结果只结构化保存“用户采用的结果”

已确认：

- 推荐对话记录需要保存，方便用户回看。
- LLM 某轮输出但用户没有选中的候选，不单独进入正式结构化推荐结果表。
- 用户加入推荐列表 / 采用的项目，才写入 `recommendation_selected_item`。
- 加入推荐列表不更新买家-标的关系。
- 生成推荐报告不自动更新买家-标的关系。
- 只有用户显式点击“标记这些项目为已推荐”，才写入 `buyer_seller_relation` 和 `relation_event`。

---

## 2. 通用字段约定

### 2.1 ID 与基础字段

核心业务表建议统一使用：

```text
id
team_id
workspace_id
created_at
created_by
updated_at
updated_by
deleted_at
deleted_by
metadata_json
```

说明：

- `id` 建议使用 UUID / ULID，具体后续技术实现时决定。
- `team_id` 表示组织 / 公司 / 租户级隔离，即使一期只有一个团队，也建议预留。
- `workspace_id` 表示部门 / 项目组 / 数据空间 / 专项项目隔离。
- 核心业务对象建议支持 soft delete。
- `metadata_json` 用于低频扩展，不应承载核心查询字段。

### 2.1.1 `team_id` 与 `workspace_id`

已确认：除 `team_id` 外，需要增加类似部门 ID 的隔离字段。

建议命名为：

```text
workspace_id
```

而不是固定为 `department_id`。

原因：

- 未来隔离维度不一定只是部门。
- 也可能是项目组、区域团队、客户专项组、政府招商专项、基金项目或内部数据空间。
- `workspace_id` 更适合作为通用数据空间概念。

推荐权限层级：

```text
team_id       = 公司 / 租户 / 大组织
workspace_id  = 部门 / 项目空间 / 数据隔离空间
owner_user_id = 负责人
```

典型查询条件：

```sql
where team_id = :current_team_id
  and workspace_id in (:user_accessible_workspace_ids)
  and deleted_at is null
```

管理员查看全团队数据时，可以只限制：

```sql
where team_id = :current_team_id
  and deleted_at is null
```

核心业务表建议都带：

```text
team_id
workspace_id
```

包括：

- `seller_target`
- `seller_party`
- `buyer_party`
- `buyer_intent`
- `buyer_seller_relation`
- `relation_event`
- `business_update`
- `extracted_action`
- `action_application_log`
- `recommendation_session`
- `recommendation_selected_item`
- `recommendation_report`
- `attachment`
- `attachment_link`
- `parsed_document`
- `field_value_source`
- `evidence_span`
- `seller_target_search_doc`
- `buyer_intent_search_doc`

字典类表可以允许：

```text
team_id nullable
workspace_id nullable
```

用于支持：

| 范围 | team_id | workspace_id |
| --- | --- | --- |
| 全局默认字典 | null | null |
| 团队自定义字典 | 有值 | null |
| 数据空间自定义字典 | 有值 | 有值 |

一期可以先只实现 `team_id + workspace_id` 的数据归属，不必一次性实现复杂权限后台。

### 2.2 负责人字段

建议核心业务对象都保留负责人：

```text
owner_user_id
```

适用对象：

- `seller_target`
- `seller_party`
- `buyer_party`
- `buyer_intent`
- `buyer_seller_relation`，可选

### 2.3 来源与证据

字段来源可以来自：

- 附件解析。
- 用户手动输入。
- 统一业务更新。
- 联网调研。
- 系统计算。

建议通过以下对象统一承接：

```text
attachment
parsed_document
evidence_span
field_value_source
action_application_log
```

其中：

- `field_value_source` 记录当前采用字段值的来源。
- `action_application_log` 记录字段变化历史。
- `evidence_span` 记录附件页码、文本片段、截图 OCR、单元格等证据定位。

---

## 3. 卖方主体与标的

### 3.1 `seller_party`

用途：卖方主体 / 公司主体主数据。

它不是推荐核心对象，但用于：

- 多个标的项目归属。
- 公司主体去重。
- 合并重复主体。
- 主体层面的公开信息补全。

关键字段：

```text
seller_party
- id
- team_id
- party_name
- legal_name
- aliases_json
- unified_credit_code
- party_type
- region_province
- region_city
- address
- website
- profile_summary
- owner_user_id
- status
- merged_into_id
- metadata_json
- created_at / created_by
- updated_at / updated_by
- deleted_at / deleted_by
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `party_name` | 系统展示名，可为简称 |
| `legal_name` | 工商主体全称 |
| `aliases_json` | 曾用名、简称、项目内部别名 |
| `unified_credit_code` | 统一社会信用代码，后续去重重要字段 |
| `party_type` | 公司 / 集团 / 个人 / 其他 |
| `status` | `active / archived / merged` |
| `merged_into_id` | 重复主体合并后的主主体 ID |

索引建议：

- `party_name`、`legal_name` 使用 trigram / similarity 索引，支持快速查重。
- `unified_credit_code` 唯一或半唯一索引，允许为空。
- `team_id + status` 常规索引。

### 3.2 `seller_target`

用途：标的项目，Match-MA 的核心管理对象之一。

关键字段：

```text
seller_target
- id
- team_id
- target_name
- target_type
- seller_party_id
- owner_user_id

- recommendation_status
- information_status

- target_summary
- business_summary
- transaction_summary
- risk_summary
- gap_summary

- industry_primary
- industry_secondary
- registered_country
- registered_province
- registered_city
- headquarter_province
- headquarter_city
- operating_regions_json
- production_regions_json
- asset_regions_json
- raw_region_text
- region_granularity
- listed_status

- current_revenue_yuan
- current_net_profit_yuan
- current_total_profit_yuan
- current_assets_yuan
- current_debt_ratio
- financial_period_label

- valuation_yuan
- asking_price_yuan
- pe_ratio
- pe_source_type
- pe_calculation_basis_json

- is_for_sale
- can_control
- can_consolidate
- accepts_minority_investment
- transfer_ratio_min
- transfer_ratio_max
- transfer_ratio_text
- transfer_flexibility_type
- control_path_options_json
- consolidation_path_summary
- deal_paths_json
- accepted_payment_methods_json
- accepts_relocation
- acceptable_relocation_regions_json
- accepts_return_investment

- completeness_score
- last_business_update_at
- last_research_at
- last_attachment_parse_at

- metadata_json
- created_at / created_by
- updated_at / updated_by
- deleted_at / deleted_by
```

#### 3.2.1 `target_type`

建议枚举：

| 枚举 | 中文 |
| --- | --- |
| `company` | 公司标的 |
| `equity_package` | 股权包 |
| `business_unit` | 业务线 |
| `asset_package` | 资产包 |
| `project` | 项目 |
| `other` | 其他 |

#### 3.2.2 区域字段

已确认原则：

```text
seller_target 只存标的区域事实，不存“是否落在某买家偏好区域”。
```

原因：

- 偏好区域属于 `buyer_intent`。
- 同一个标的会面对多个买家意向，不同意向的区域偏好不同。
- 是否匹配某个买家偏好，应由推荐引擎在推荐时动态计算。

`seller_target` 区域建议拆分为：

```text
registered_country
registered_province
registered_city

headquarter_province
headquarter_city

operating_regions_json
production_regions_json
asset_regions_json

raw_region_text
region_granularity

accepts_relocation
acceptable_relocation_regions_json
accepts_return_investment
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `registered_*` | 注册地 |
| `headquarter_*` | 总部所在地 |
| `operating_regions_json` | 主要经营地，可多个 |
| `production_regions_json` | 生产基地，可多个 |
| `asset_regions_json` | 资产包 / 业务线所在地，可多个 |
| `raw_region_text` | 原始区域描述，例如“长三角”“江浙沪” |
| `region_granularity` | 区域粒度：省 / 市 / 区域组 / 未知 |
| `acceptable_relocation_regions_json` | 如接受迁址，可记录可迁往区域 |

注意：

```text
如果标的材料只说“位于长三角”，不能把标的事实直接展开成上海、江苏、浙江、安徽。
```

这种情况应保留：

```text
raw_region_text = 长三角
region_granularity = region_group
registered_province / operating_regions_json = null 或待确认
```

推荐时可以作为“可能匹配长三角”的候选，但不能当作“浙江标的”。

业务默认匹配区域时，优先使用：

```text
经营地 / 总部所在地 / 资产所在地
```

注册地作为辅助信息。只有买家明确要求注册地时，才用注册地做硬筛。

#### 3.2.3 推荐状态与信息状态

已确认拆分：

```text
recommendation_status
information_status
```

`recommendation_status` 建议：

| 枚举 | 中文 | 含义 |
| --- | --- | --- |
| `recommendable` | 可推荐 | 业务上可以进入推荐候选池 |
| `not_recommendable` | 暂不推荐 | 业务上暂不进入推荐候选池 |

`information_status` 建议：

| 枚举 | 中文 |
| --- | --- |
| `normal` | 正常 |
| `insufficient` | 信息不足 |
| `pending_review` | 待确认 |
| `parsing` | 附件解析中 |
| `researching` | 调研中 |
| `parse_failed` | 解析失败 |

示例组合：

```text
可推荐 + 信息不足
可推荐 + 待确认
暂不推荐 + 信息完整
可推荐 + 调研中
```

#### 3.2.4 交易比例、控股与并表

已确认原则：

```text
股权比例、控股、并表、参股是相关但不同的概念，不能只用一个比例字段表达。
```

原因：

- “控股权可谈”不等于固定转让 51%。
- “可并表即可”不一定要求直接持股 51%。
- “29.9% 以下”也可能通过表决权委托、一致行动、董事会控制等实现控制。
- “参股也可以”表示买家接受少数股权，不应被控股规则误排除。

`seller_target` 侧建议字段：

```text
transfer_ratio_min
transfer_ratio_max
transfer_ratio_text

can_control
can_consolidate
accepts_minority_investment

transfer_flexibility_type
control_path_options_json
consolidation_path_summary

deal_paths_json
accepted_payment_methods_json
```

`transfer_ratio_min / max` 只存能明确数字化的比例区间。

示例：

```text
51%以上      -> min = 51, max = 100
20%-30%     -> min = 20, max = 30
29.9%以下   -> min = 0, max = 29.9
```

非数字表达不强行转成固定比例。

例如“控股权可谈”：

```text
transfer_ratio_min = null
transfer_ratio_max = null
transfer_ratio_text = 控股权可谈
can_control = likely
can_consolidate = unknown
transfer_flexibility_type = control_available
control_path_options_json = [equity_transfer, voting_right_delegation, capital_increase]
```

`can_control / can_consolidate / accepts_minority_investment` 建议采用三值或四值：

```text
true / false / unknown / likely
```

`transfer_flexibility_type` 建议：

| 枚举 | 中文 |
| --- | --- |
| `control_available` | 控股权可谈 |
| `consolidation_available` | 可实现并表 |
| `minority_available` | 少数股权可转让 |
| `full_sale_available` | 可整体出售 |
| `flexible` | 比例灵活 |
| `specific_range` | 明确比例区间 |
| `unknown` | 未明确 |

筛选时只硬排除明确冲突：

```text
买家必须控股 + 标的明确不能控股 => 排除
买家必须并表 + 标的明确不能并表 => 排除
双方比例区间明确且无交集，且无其他控制路径 => 排除
```

其他情况保留进入候选，并在推荐结果中标记：

```text
控股可行性待确认
并表路径待确认
股权比例需进一步沟通
```

#### 3.2.5 主表财务字段

`seller_target` 主表只存当前关键财务快照。

用途：

- 列表页展示。
- 排序。
- 初筛。
- 推荐候选池构建。

多期间明细进入 `seller_target_financial`。

#### 3.2.6 PE 字段

建议：

```text
pe_ratio
pe_source_type
pe_calculation_basis_json
```

`pe_source_type`：

| 枚举 | 含义 |
| --- | --- |
| `user_input` | 用户输入 |
| `document` | 材料明确披露 |
| `calculated` | 系统按估值 / 利润计算 |
| `research` | 联网调研获得 |
| `unknown` | 未知 |

PE 来源优先级：

```text
用户输入 PE > 材料明确披露 PE > 估值 / 利润计算 PE
```

#### 3.2.7 索引建议

高频查询索引：

```text
team_id + recommendation_status
team_id + information_status
industry_primary
industry_secondary
registered_province
registered_city
headquarter_province
headquarter_city
listed_status
current_net_profit_yuan
valuation_yuan
asking_price_yuan
pe_ratio
is_for_sale
can_control
can_consolidate
transfer_ratio_min
transfer_ratio_max
owner_user_id
updated_at
```

查重索引：

```text
target_name trigram / similarity
seller_party_id
```

### 3.3 `seller_target_financial`

用途：存储标的多期间财务明细。

关键字段：

```text
seller_target_financial
- id
- team_id
- seller_target_id
- period_type
- period_label
- period_start
- period_end

- revenue_yuan
- net_profit_yuan
- total_profit_yuan
- ebitda_yuan
- assets_yuan
- liabilities_yuan
- debt_ratio
- gross_margin
- operating_cash_flow_yuan

- audit_status
- accounting_standard
- source_type
- source_id
- evidence_id
- confidence
- review_status

- created_at / created_by
- updated_at / updated_by
```

`period_type` 建议：

```text
annual / quarterly / monthly / ttm / latest
```

`review_status` 建议：

```text
pending_review / accepted / rejected / auto_accepted
```

推荐使用规则：

- 默认使用 `seller_target` 主表当前快照。
- 当买家要求近三年、连续盈利、利润稳定时，加载 `seller_target_financial` 给 LLM 判断。

### 3.4 `seller_target_risk`

用途：结构化记录标的风险，不作为普通 tag。

关键字段：

```text
seller_target_risk
- id
- team_id
- seller_target_id
- risk_type
- risk_status
- severity
- description
- source_type
- source_id
- evidence_id
- confidence
- review_status
- detected_at
- resolved_at
- created_at / created_by
- updated_at / updated_by
```

`risk_type` 建议：

```text
litigation
environmental
debt
audit_opinion
regulatory_violation
delisting
st
goodwill_impairment
outdated_technology
overcapacity
customer_concentration
other
```

`risk_status` 建议：

| 枚举 | 中文 |
| --- | --- |
| `confirmed_present` | 确认存在 |
| `suspected` | 疑似存在 |
| `not_found` | 暂未发现 |
| `confirmed_absent` | 明确不存在 |
| `unknown` | 未知 |

`severity` 建议：

```text
low / medium / high / critical
```

推荐过滤规则示例：

```text
排除环保风险和重大诉讼
```

服务端优先转为：

```text
exclude risk_status in confirmed_present / suspected
where risk_type in environmental / litigation
and severity >= medium
```

### 3.5 `tag_dictionary`

用途：统一管理行业、赛道、产品、资质、能力、风险等可复用标签。

关键字段：

```text
tag_dictionary
- id
- team_id nullable
- domain
- canonical_key
- display_name
- parent_key
- aliases_json
- description
- is_active
- sort_order
- created_at / updated_at
```

`domain` 示例：

```text
industry
sector
product
certification
capability
customer_type
risk
transaction
```

说明：

- 一级行业、二级行业建议字典化。
- 细分赛道、产品、资质采用半结构化字典。
- 允许保留原文标签，避免早期标准化过重。
- 一期不要求行业字典全覆盖。系统应采用“LLM 原文抽取 -> 服务端按别名/相似度召回小候选集 -> 归一化或待归一化”的路径，而不是把完整大字典一次性塞进 LLM prompt。
- `team_id / workspace_id` 可以为空，代表全局默认字典；为了避免 PostgreSQL 中 `null` scope 重复，schema 使用 `coalesce` 表达式唯一索引约束 `domain + canonical_key`。

一期默认 seed：

```text
industry:
- healthcare
- new_energy
- new_materials_chemical
- digital_ai_semiconductor_software
- agriculture_food
- culture_tourism_consumer
- environmental_circular
- financial_leasing
- high_end_equipment_robotics
- automotive_parts
- marine_ocean_engineering
- engineering_infrastructure
- supply_chain_cross_border
- low_altitude_aerospace
- urban_renewal_building_materials
- bio_manufacturing
- traditional_manufacturing
- other

deal_path:
- equity_transfer
- capital_increase
- asset_acquisition
- share_swap
- cash_and_share
- backdoor_listing
- voting_right_delegation
- concert_party
- board_control
- mixed
- other

payment_method:
- cash
- share
- cash_and_share
- debt_assumption
- installment
- mixed
- other

control_path:
- equity_control
- voting_right_delegation
- concert_party
- board_control
- agreement_control
- capital_increase_plus_old_share
- other
```

### 3.5.1 `region_alias_config`

用途：管理买家意向解析时常见区域别名的展开规则，例如“长三角、江浙沪、珠三角、沿海发达地区”。

关键字段：

```text
region_alias_config
- id
- team_id nullable
- workspace_id nullable
- alias_text
- expanded_regions_json
- region_level
- description
- is_active
- sort_order
```

设计原则：

- 这是买家意向解析和筛选规则生成的辅助配置，不是 `seller_target` 的事实字段。
- `seller_target` 存的是标的真实地区，如注册省市、总部省市、经营区域、生产基地、资产所在地等。
- 如果标的来源只写“长三角”，标的侧保留 `raw_region_text = 长三角` 和 `region_granularity = region_group`，不强行扩展成精确省市。
- 如果买家说“浙江优先、长三角可接受”，LLM 可读取少量区域别名配置，把“长三角”展开成省市列表；服务端再按 hard/preference 规则过滤和排序。

### 3.6 `seller_target_tag`

用途：标的半结构化标签。

关键字段：

```text
seller_target_tag
- id
- team_id
- seller_target_id
- domain
- canonical_key
- display_name
- raw_text
- source_type
- source_id
- evidence_id
- confidence
- review_status
- created_at / created_by
```

示例：

```text
canonical_key: medical_device.ivd
display_name: 体外诊断 / IVD
raw_text: 体外诊断试剂、IVD、诊断试剂
source_type: attachment
confidence: 0.87
```

---

## 4. 买家主体与买家意向

### 4.1 `buyer_party`

用途：买家公司主体主数据。

它不是推荐核心对象，推荐核心是 `buyer_intent`。

关键字段：

```text
buyer_party
- id
- team_id
- buyer_name
- legal_name
- aliases_json
- buyer_type
- group_name
- listed_status
- region_country
- region_province
- region_city
- main_business
- capital_strength_summary
- profile_summary
- long_term_preference_json
- owner_user_id
- status
- merged_into_id
- metadata_json
- created_at / created_by
- updated_at / updated_by
- deleted_at / deleted_by
```

`buyer_type` 示例：

```text
industrial_buyer
listed_company
state_owned_platform
pe_fund
financial_investor
government_platform
other
```

状态建议：

```text
active / archived / merged
```

### 4.2 `buyer_intent`

用途：买家的具体收购意向 / 推荐任务核心对象。

已确认：

- 新建入口优先为“新建买家意向”。
- `buyer_intent.buyer_party_id` 可为空。
- 匿名推荐不自动创建 `buyer_intent`。
- 只有用户选择保存为正式意向时才进入此表。

关键字段：

```text
buyer_intent
- id
- team_id
- buyer_party_id nullable
- owner_user_id

- intent_name
- status
- pause_reason
- contact_name
- contact_info_json

- raw_requirement_text
- intent_summary
- parsed_requirement_json

- industry_primary
- industry_secondary
- region_scope_summary
- region_constraints_json
- min_revenue_yuan
- min_net_profit_yuan
- max_pe
- max_valuation_yuan
- requires_consolidation
- requires_control
- accepts_minority_investment
- desired_equity_ratio_min
- desired_equity_ratio_max
- equity_ratio_summary
- equity_requirement_type
- acceptable_control_paths_json
- preferred_listed_status
- transaction_type
- negative_summary

- last_recommendation_at
- last_business_update_at
- created_at / created_by
- updated_at / updated_by
- deleted_at / deleted_by
```

`status` 已确认两个主状态：

| 枚举 | 中文 | 含义 |
| --- | --- | --- |
| `active` | 继续推荐 | 该意向仍有效，可以继续推荐标的 |
| `paused` | 暂停推荐 | 当前不需要继续为该意向推荐标的 |

说明：

- 主表字段用于列表页展示、快速筛选和常见查询。
- 复杂规则以 `buyer_intent_constraint` 为准。
- `parsed_requirement_json` 保留 LLM 完整解析结果。

#### 4.2.1 买家意向区域要求

已确认原则：

```text
buyer_intent 存区域要求，seller_target 存区域事实。
```

买家意向中的区域表达可以由 LLM 在入库或解析时标准化展开，例如：

```text
长三角区域，尤其浙江省内
```

可解析为：

```json
{
  "region_constraints": [
    {
      "raw_text": "长三角区域",
      "scope": "operating_region",
      "expanded_regions": ["上海市", "江苏省", "浙江省", "安徽省"],
      "constraint_type": "hard"
    },
    {
      "raw_text": "尤其浙江省内",
      "scope": "operating_region",
      "expanded_regions": ["浙江省"],
      "constraint_type": "preference"
    }
  ]
}
```

这里不做复杂行政区划字典。

一期建议采用：

```text
轻量区域别名配置 + LLM 解析 + 服务端校验
```

当前 schema 草案选择落为 `region_alias_config` 表，便于后续由管理员维护团队/数据空间自己的业务口径。

用途：

- 给 LLM 解析买家意向时参考。
- 给服务端校验 LLM 输出。
- 给推荐筛选时展开区域范围。
- 给 Trace 解释“长三角为何展开成这些省市”。

示例配置：

```json
{
  "长三角": ["上海市", "江苏省", "浙江省", "安徽省"],
  "江浙沪": ["江苏省", "浙江省", "上海市"],
  "江浙": ["江苏省", "浙江省"],
  "沿海发达地区": ["上海市", "江苏省", "浙江省", "福建省", "广东省", "山东省"]
}
```

如果业务内部对“长三角”只采用“江沪浙”，也可以按内部定义配置。

关键是：

```text
LLM 可以展开，但服务端要校验；展开规则要可配置、可追踪。
```

区域要求还需要区分作用对象：

```text
registered_region
headquarter_region
operating_region
asset_region
any_business_region
relocation_region
```

一期默认：

```text
优先匹配经营地 / 总部所在地 / 资产所在地；
注册地仅作为辅助信息。
```

只有买家明确要求注册地时，才用注册地做硬筛。

#### 4.2.2 买家意向股权比例、控股与并表

买家侧也必须拆分：

```text
股权比例区间
控股要求
并表要求
参股接受度
交易结构路径
```

字段建议：

```text
desired_equity_ratio_min
desired_equity_ratio_max
equity_ratio_summary

requires_control
requires_consolidation
accepts_minority_investment

equity_requirement_type
acceptable_control_paths_json
transaction_type
```

数字比例只在表达明确时入结构化区间。

示例：

```text
51%以上      -> desired_equity_ratio_min = 51, desired_equity_ratio_max = 100
20%-30%     -> desired_equity_ratio_min = 20, desired_equity_ratio_max = 30
29.9%以下   -> desired_equity_ratio_min = 0, desired_equity_ratio_max = 29.9
```

非数字表达不强行转数字。

示例：“可并表即可”：

```json
{
  "desired_equity_ratio_min": null,
  "desired_equity_ratio_max": null,
  "equity_ratio_summary": "可并表即可",
  "requires_control": "unknown",
  "requires_consolidation": true,
  "accepts_minority_investment": "conditional",
  "acceptable_control_paths": ["voting_right_delegation", "board_control", "concert_party", "equity_transfer"]
}
```

示例：“参股也可以”：

```json
{
  "desired_equity_ratio_min": null,
  "desired_equity_ratio_max": null,
  "requires_control": false,
  "requires_consolidation": false,
  "accepts_minority_investment": true
}
```

`equity_requirement_type` 建议：

| 枚举 | 中文 |
| --- | --- |
| `control_required` | 必须控股 |
| `consolidation_required` | 必须并表 |
| `minority_acceptable` | 参股可接受 |
| `minority_only` | 只考虑少数股权 |
| `flexible` | 比例灵活 |
| `specific_range` | 明确比例区间 |
| `unknown` | 未明确 |

筛选原则：

```text
能确定冲突的才硬排除；
不能确定冲突的保留，但标记缺口或降权；
最终复杂权衡交给 LLM rerank。
```

### 4.3 `buyer_intent_constraint`

用途：结构化表达买家意向规则，支持 hard / preference / unknown。

关键字段：

```text
buyer_intent_constraint
- id
- team_id
- buyer_intent_id
- field
- operator
- value_json
- unit
- normalized_key
- constraint_type
- unknown_policy
- weight
- raw_text
- source_type
- source_id
- confidence
- review_status
- created_at / created_by
- updated_at / updated_by
```

`constraint_type` 已确认：

| 枚举 | 中文 | 含义 |
| --- | --- | --- |
| `hard` | 硬条件 | 原则上用于过滤或强约束 |
| `preference` | 偏好 | 用于排序、推荐理由和权衡 |
| `unknown` | 未明确 | 需要补问或在推荐结果中标记缺口 |

`unknown_policy` 建议：

| 枚举 | 含义 |
| --- | --- |
| `allow_but_flag_gap` | 允许进入候选，但标记信息缺口 |
| `allow_but_deprioritize` | 允许进入候选，但排序靠后 |
| `exclude` | 未知也排除 |
| `ask_user` | 需要用户进一步确认 |

示例：

```text
field: operating_region
operator: in
value_json: {
  "raw_text": "长三角",
  "expanded_regions": ["上海市", "江苏省", "浙江省", "安徽省"],
  "scope": "operating_region"
}
constraint_type: hard
```

```text
field: operating_region
operator: preferred_in
value_json: {
  "raw_text": "浙江",
  "expanded_regions": ["浙江省"],
  "scope": "operating_region"
}
constraint_type: preference
```

```text
field: net_profit_yuan
operator: >=
value_json: 20000000
unit: yuan
constraint_type: hard
unknown_policy: allow_but_deprioritize
```

### 4.4 `buyer_intent_target_exclusion`

用途：记录某买家意向对某标的的硬排除。

已确认：

```text
“不感兴趣”写入 buyer_seller_relation.status，同时写入 buyer_intent_target_exclusion。
```

关键字段：

```text
buyer_intent_target_exclusion
- id
- team_id
- buyer_intent_id
- buyer_party_id nullable
- seller_target_id
- reason
- source_relation_id
- source_update_id
- source_event_id
- active
- created_by
- created_at
- canceled_by
- canceled_at
```

推荐使用规则：

- 同一 `buyer_intent_id + seller_target_id` 存在 active exclusion 时，推荐服务硬排除。
- buyer_party_id 可冗余，便于查询。

---

## 5. 买家-标的关系与进展

### 5.1 `buyer_seller_relation`

用途：记录一个买家意向与一个标的项目的当前关系状态。

已确认：

```text
核心唯一关系 = buyer_intent_id + seller_target_id
```

建议同时冗余：

```text
buyer_party_id
```

便于按买家主体查询。

关键字段：

```text
buyer_seller_relation
- id
- team_id
- buyer_intent_id
- buyer_party_id nullable
- seller_target_id

- status
- status_reason
- owner_user_id

- first_recommended_at
- last_contact_at
- last_event_at
- last_event_summary

- created_from_session_id nullable
- created_from_report_id nullable
- metadata_json
- created_at / created_by
- updated_at / updated_by
- deleted_at / deleted_by
```

唯一约束建议：

```text
unique(team_id, buyer_intent_id, seller_target_id) where deleted_at is null
```

`status` 建议枚举：

| 枚举 | 中文 |
| --- | --- |
| `recommended` | 已推荐 |
| `interested` | 感兴趣 |
| `in_discussion` | 沟通中 |
| `due_diligence` | 尽调中 |
| `agreement` | 协议中 |
| `deal_closed` | 已成交 |
| `not_interested` | 不感兴趣 |
| `paused` | 暂停 |
| `lost` | 已流失 |

说明：

- 没有 relation 记录，表示未建立正式关系。
- “已在谈”不阻止推荐给其他买家，只在推荐卡片里展示历史接触提示。
- “不感兴趣”对当前 `buyer_intent + seller_target` 硬排除。

### 5.2 `relation_event`

用途：记录买家-标的关系的历史事件。

已确认采用：

```text
一条当前 relation + 多条 relation_event
```

关键字段：

```text
relation_event
- id
- team_id
- relation_id
- buyer_intent_id
- buyer_party_id nullable
- seller_target_id

- event_type
- event_time
- title
- content
- next_step

- source_type
- source_id
- evidence_id
- created_by
- created_at
- metadata_json
```

`event_type` 示例：

```text
recommended
buyer_interested
buyer_not_interested
meeting
call
material_sent
due_diligence_started
agreement_discussion
deal_closed
paused
internal_note
other
```

来源示例：

```text
manual
business_update
recommendation_report
ocr_screenshot
attachment
system
```

### 5.3 关系查询需求

关系表需要支持以下高频查询：

#### 为买家找标的时

- 当前买家意向已不感兴趣的标的，硬排除。
- 当前买家意向已推荐过的标的，展示提示。
- 当前买家意向正在沟通的标的，展示提示。
- 其他买家正在接触该标的，展示灰色历史接触提示。

#### 为标的找买家时

- 该买家意向已对当前标的不感兴趣，硬排除。
- 该标的已推荐给该买家意向，展示提示。
- 该买家意向近 30 天已推荐 / 在谈多个标的，展示提示。

“近期”默认：

```text
近 30 天
```

后续可配置。

---

## 6. 推荐会话、聊天、采用结果和报告

### 6.1 推荐数据状态分层

推荐流程中的状态必须分开：

| 状态 | 存储对象 | 是否更新买家-标的关系 |
| --- | --- | --- |
| 聊天中出现过 | `recommendation_message` | 否 |
| 用户加入推荐列表 | `recommendation_selected_item` | 否 |
| 用户生成报告 | `recommendation_report` | 否 |
| 用户确认已推荐 | `buyer_seller_relation` + `relation_event` | 是 |

### 6.2 `recommendation_session`

用途：一次智能推荐对话会话。

关键字段：

```text
recommendation_session
- id
- team_id
- mode

- buyer_intent_id nullable
- buyer_party_id nullable
- seller_target_id nullable
- anonymous_input_snapshot

- initial_condition_snapshot_json
- latest_condition_snapshot_json
- status
- selected_count
- report_count

- created_by
- created_at
- updated_at
- archived_at
- metadata_json
```

`mode`：

| 枚举 | 中文 |
| --- | --- |
| `buyer_to_target` | 为买家找标的 |
| `target_to_buyer` | 为标的找买家 |

说明：

- 匿名需求推荐不自动创建 `buyer_intent`，但可以保存在 `anonymous_input_snapshot`。
- 条件快照用于回看当时推荐上下文。

### 6.3 `recommendation_message`

用途：保存推荐对话记录。

关键字段：

```text
recommendation_message
- id
- team_id
- session_id
- role
- content
- content_type
- metadata_json
- created_at
- created_by nullable
```

`role`：

```text
user / assistant / system / tool
```

`metadata_json` 可保存：

- LLM 输出中的候选卡片快照，非正式结构化结果。
- 用户提到的编号映射。
- 本轮使用的条件快照 ID。
- 测试模式下的 trace id。

说明：

```text
recommendation_message 中出现的候选，不等于正式推荐结果。
```

### 6.4 `recommendation_selected_item`

用途：只保存用户采用 / 加入推荐列表的推荐项。

关键字段：

```text
recommendation_selected_item
- id
- team_id
- session_id
- mode

- seller_target_id nullable
- buyer_intent_id nullable
- buyer_party_id nullable

- selected_from_message_id nullable
- rank_at_selection
- recommendation_level

- match_summary
- risk_summary
- gap_summary
- reason_snapshot
- evidence_snapshot_json

- selected_by
- selected_at
- canceled_by nullable
- canceled_at nullable
- metadata_json
```

两种模式下的含义：

| 模式 | 当前对象 | 被选中对象 |
| --- | --- | --- |
| `buyer_to_target` | 当前买家意向 | `seller_target_id` |
| `target_to_buyer` | 当前标的 | `buyer_intent_id` |

说明：

- 用户没有加入推荐列表的候选，不写入此表。
- 取消推荐时不物理删除，写 `canceled_at`。
- 该表不直接代表“已推荐给买家”。

### 6.5 `recommendation_report`

用途：推荐报告生成记录。

关键字段：

```text
recommendation_report
- id
- team_id
- session_id
- report_type
- selected_item_ids_json
- title
- markdown_content
- file_path
- file_format
- status
- generated_by_model
- prompt_version
- created_by
- created_at
- metadata_json
```

`report_type`：

```text
buyer_facing_target_report
internal_buyer_list
```

说明：

- 报告生成不自动更新 `buyer_seller_relation`。
- 报告生成后可以提供“标记这些项目为已推荐”，用户确认后再写关系和事件。

---

## 7. 附件、解析和证据定位

### 7.1 `attachment`

用途：原始附件记录。

关键字段：

```text
attachment
- id
- team_id
- file_name
- file_type
- mime_type
- file_size
- storage_path
- uploaded_by
- uploaded_at
- parse_status
- metadata_json
```

`parse_status`：

```text
pending / parsing / parsed / failed / skipped
```

### 7.2 `attachment_link`

用途：附件可关联多个业务对象。

关键字段：

```text
attachment_link
- id
- team_id
- attachment_id
- entity_type
- entity_id
- link_type
- created_at
- created_by
```

`entity_type` 示例：

```text
seller_target
seller_party
buyer_party
buyer_intent
business_update
relation_event
```

### 7.3 `parsed_document`

用途：附件解析结果。

关键字段：

```text
parsed_document
- id
- team_id
- attachment_id
- parser_name
- parser_version
- parse_status
- text_path
- markdown_path
- manifest_path
- page_count
- token_count
- error_message
- created_at
- updated_at
```

### 7.4 `evidence_span`

用途：字段来源和推荐依据的证据定位。

关键字段：

```text
evidence_span
- id
- team_id
- source_type
- source_id
- attachment_id nullable
- parsed_document_id nullable
- page_no nullable
- slide_no nullable
- sheet_name nullable
- cell_range nullable
- bbox_json nullable
- text_excerpt
- char_start nullable
- char_end nullable
- created_at
```

来源可以是：

```text
attachment
business_update
ocr_screenshot
research
manual_input
system_calculation
```

### 7.5 `field_value_source`

用途：记录当前采用字段值的来源和证据。

关键字段：

```text
field_value_source
- id
- team_id
- entity_type
- entity_id
- field_path
- value_snapshot_json
- source_type
- source_id
- evidence_id
- confidence
- review_status
- created_at
- created_by
```

示例：

```text
entity_type: seller_target
entity_id: st_xxx
field_path: current_net_profit_yuan
value_snapshot_json: {"value": 25000000, "unit": "yuan", "period": "2024"}
source_type: attachment
evidence_id: ev_xxx
review_status: accepted
```

---

## 8. 统一业务更新与字段应用日志

### 8.1 `business_update`

用途：统一业务更新原始输入。

关键字段：

```text
business_update
- id
- team_id
- raw_text
- input_type
- processing_status

- bound_seller_target_ids_json
- bound_buyer_party_ids_json
- bound_buyer_intent_ids_json
- bound_recommendation_session_id nullable

- created_by
- created_at
- metadata_json
```

`input_type`：

```text
text / screenshot / attachment / mixed
```

`processing_status`：

```text
pending / processing / parsed / partially_applied / applied / failed
```

### 8.2 `extracted_action`

用途：AI 从业务更新中拆分出来的待处理动作。

关键字段：

```text
extracted_action
- id
- team_id
- business_update_id
- action_type
- target_entity_type
- target_entity_id
- proposed_changes_json
- raw_evidence_text
- evidence_id
- confidence
- review_status
- reviewed_by
- reviewed_at
- applied_at
- metadata_json
```

`action_type` 示例：

```text
seller_fact_update
seller_event
buyer_seller_relation_update
buyer_intent_target_exclusion
buyer_intent_suggestion
buyer_level_blacklist_suggestion
internal_note
unresolved_item
```

### 8.3 `action_application_log`

用途：记录动作应用后的字段变化。

关键字段：

```text
action_application_log
- id
- team_id
- extracted_action_id nullable
- business_update_id nullable
- entity_type
- entity_id
- field_path
- old_value_json
- new_value_json
- source_type
- source_id
- evidence_id
- applied_by
- applied_at
- edited_before_apply
- can_rollback
- rollback_at nullable
- metadata_json
```

说明：

- `seller_target` 主表只存当前快照。
- 字段变化历史主要从 `action_application_log` 查询。
- 详情页“更新记录”来自 `business_update + extracted_action + action_application_log`。

---

## 9. 检索与推荐支撑表

### 9.1 `seller_target_search_doc`

用途：为全文检索、向量召回和 LLM 证据包准备标的检索文档。

关键字段：

```text
seller_target_search_doc
- id
- team_id
- workspace_id
- seller_target_id
- doc_type
- title
- structured_summary
- tag_text
- business_text
- financial_text
- transaction_text
- risk_text
- gap_text
- full_text
- embedding
- embedding_model
- embedding_dim
- source_version
- updated_at
```

`doc_type` 示例：

```text
profile
business
transaction
risk
attachment_summary
research_summary
```

说明：

- 一期可以先每个标的生成一个 `profile` 文档。
- 后续再按内容拆分多文档。
- `embedding` 使用 pgvector。
- `full_text` 可配 PostgreSQL full-text search。

向量检索应用场景：

```text
向量检索用于语义召回和兜底召回，不用于硬条件判断。
```

适合写入 `seller_target_search_doc` 并生成 embedding 的内容：

- 标的业务摘要。
- 细分赛道 / 产品描述。
- 标签文本。
- 交易条件摘要。
- 风险摘要和信息缺口。
- 附件摘要。
- 联网调研摘要。

不适合用向量做主判断的内容：

- 利润门槛。
- PE 上限。
- 地区是否符合。
- 是否并表。
- 是否已不感兴趣。
- 是否存在重大风险硬排除。
- 权限隔离。

这些必须走结构化字段、关系表或风险表。

一期建议：

```text
每个 seller_target 先生成一个 profile search_doc。
```

示例检索文本：

```text
上海启元项目。医药健康，医疗器械，体外诊断试剂和 POCT 设备。主要客户包括三甲医院和区域经销商。经营地浙江和上海。2024年营收1.2亿，净利润2500万。报价3.5亿，PE约14。控股权可谈，并表可行性待确认。暂未发现重大诉讼，环保材料待确认。
```

embedding 模型一期建议：

```text
text-embedding-v4
dimension = 1024
```

说明：

- 阿里云 `text-embedding-v4` 支持指定维度，默认 1024。
- 一期建议固定 1024，避免同一库混用不同维度。
- 表内同时保存 `embedding_model` 和 `embedding_dim`，方便未来重建或迁移。
- 未来如需多模型、多维度，可再拆出独立 `search_doc_embedding` 表。

### 9.2 `buyer_intent_search_doc`

用途：为“为标的找买家”提供买家意向检索文档。

关键字段：

```text
buyer_intent_search_doc
- id
- team_id
- workspace_id
- buyer_intent_id
- title
- requirement_summary
- constraint_text
- preference_text
- negative_text
- history_text
- full_text
- embedding
- embedding_model
- embedding_dim
- source_version
- updated_at
```

`buyer_intent_search_doc` 用于“为标的找买家”的语义召回。

适合写入并生成 embedding 的内容：

- 买家名称。
- 意向名称。
- 行业要求。
- 区域要求。
- 财务要求。
- 交易要求。
- 负面清单。
- 偏好项。
- 历史反馈。
- 当前状态。

示例检索文本：

```text
浙江国资医药健康并表需求。寻找长三角尤其浙江省内非上市医药健康标的，细分包括医药商业、制药、中药、医疗器械、医美耗材、CXO。利润2000万以上，PE原则不超过13。要求并表。排除重大诉讼、冻结、执行、违规违法。浙江省内优先。
```

两种推荐模式中的向量使用：

| 模式 | 查询文本 | 向量检索对象 | 用途 |
| --- | --- | --- | --- |
| 为买家找标的 | `buyer_intent` / 当前对话补充需求 | `seller_target_search_doc` | 召回语义相关标的 |
| 为标的找买家 | `seller_target_search_doc` | `buyer_intent_search_doc` | 召回语义相关买家意向 |

推荐流程中，向量检索位于：

```text
结构化硬过滤
↓
标签 / 全文 / 向量多路召回
↓
候选合并去重
↓
加载最新事实和关系
↓
LLM rerank
↓
推荐列表
```

不让向量检索单独决定最终推荐结果。

---

## 10. 索引与查询策略草案

### 10.1 快速查重

标的和买家查重不调用 LLM。

建议使用：

```text
pg_trgm / similarity
名称规范化
别名匹配
统一社会信用代码匹配
地区与行业辅助排序
```

适用对象：

- `seller_party`
- `seller_target`
- `buyer_party`

### 10.2 结构化筛选

高频筛选字段使用 btree / partial index：

```text
recommendation_status
information_status
industry_primary
industry_secondary
registered_province
headquarter_province
listed_status
current_net_profit_yuan
pe_ratio
valuation_yuan
asking_price_yuan
can_control
can_consolidate
transfer_ratio_min
transfer_ratio_max
buyer_intent.status
buyer_seller_relation.status
```

### 10.3 标签检索

`tag_dictionary` + `seller_target_tag` 支持：

- 行业别名。
- 细分赛道。
- 产品。
- 资质。
- 能力标签。

建议：

```text
seller_target_tag(team_id, domain, canonical_key)
seller_target_tag(seller_target_id)
```

### 10.4 风险过滤

`seller_target_risk` 支持排除：

```text
risk_type
risk_status
severity
```

建议索引：

```text
seller_target_risk(team_id, risk_type, risk_status, severity)
seller_target_risk(seller_target_id)
```

### 10.5 向量与全文检索

建议一期：

- PostgreSQL full-text search 处理关键词。
- pgvector 处理语义召回。
- 结构化筛选先缩小范围，再做向量召回或 LLM rerank。

---

## 11. 当前确认与后续待确认

### 11.1 字段类型与枚举

当前已确认：

- 行业一级字典采用轻量非穷尽 seed；二级行业和长尾赛道允许 text / tag 半结构化归一化。
- 地区字段粒度按注册地、总部地、经营区域、生产区域、资产区域拆开；区域别名只用于买家意向解析。
- 风险类型采用 P0 风险字典 seed，但 `risk_type` 保持开放 text。
- 交易类型、支付方式、控制路径采用 `tag_dictionary` 参考字典 seed。
- 关系状态一期按当前 `buyer_seller_relation.status` / `relation_event.event_type` 枚举先落地。
- 买家类型暂不作为一期核心筛选字段，先保留在 `buyer_party.metadata_json` 或后续扩展字段。

### 11.2 来源与证据粒度

需要继续确认：

- 是否每个核心字段都必须有 `field_value_source`。
- 手动输入字段是否必须填写来源备注。
- 多来源冲突时如何展示和确认。

### 11.3 推荐结果保存边界

已确认只结构化保存用户采用结果，但仍需细化：

- assistant message 中的候选卡片是否保存完整 JSON 快照。
- 取消加入推荐列表后是否仍在报告候选中显示。
- 推荐报告编辑后是否保留版本。

### 11.4 黑名单分层

一期已确认 `buyer_intent_target_exclusion`。

后续可扩展：

```text
buyer_target_blacklist
global_blacklist
```

暂不建议一期做重。

### 11.5 合并重复对象

后续需要设计：

```text
merge_log
merged_into_id
alias 保留
历史记录迁移或跳转
```

适用对象：

- `seller_party`
- `seller_target`
- `buyer_party`
- `buyer_intent`，谨慎

---

## 12. 建议下一步讨论顺序

数据库表结构 v0.1 已足够进入工程落地讨论。建议下一步按以下顺序推进：

1. 后端工程骨架：FastAPI、SQLAlchemy、Alembic、配置、健康检查、Railway 部署基线。
2. 样本评测集：选取真实标的和买家意向，验证 LLM 字段抽取、字典归一化和候选池过滤。
3. 核心 API 草案：标的新建/更新、买家意向新建/更新、统一业务更新、推荐会话。
4. 前端信息架构：工作台、标的列表、买家意向列表、智能推荐工作台、统一业务更新确认页。
5. Trace / Dry Run：为开发测试人员记录 prompt、结构化输出、token、候选池、最终推荐理由。
