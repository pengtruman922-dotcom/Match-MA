# Match-MA 买家意向 Constraint 白名单 v0.1

状态：一期建议方案  
范围：定义 `buyer_intent_constraint.field`、`operator`、`value_json`、`unknown_policy` 的一期白名单，用于约束 LLM 买家意向解析输出，并支撑服务端生成候选池、推荐解释与评测。

---

## 1. 设计目标

### 1.1 为什么需要白名单

`buyer_intent_constraint` 是买家意向规则库。

白名单用于确保：

- LLM 不能随便输出字段名。
- LLM 不能直接写 SQL。
- 服务端可以稳定校验和转换规则。
- 推荐候选池生成逻辑可复现。
- 推荐理由可以解释到具体规则。
- 后续评测可以判断解析是否正确。

整体流程：

```text
买家自然语言需求
↓
LLM 解析成白名单内 constraint
↓
服务端校验 field / operator / value_json
↓
服务端转结构化筛选、标签检索、风险过滤、向量召回参数
↓
候选池 + evidence pack
↓
LLM 最终推荐和解释
```

### 1.2 constraint.field 是业务概念，不一定等于数据库列

例如：

```text
field = industry
```

可能映射到：

```text
seller_target.industry_primary
seller_target.industry_secondary
seller_target_tag.domain = sector
seller_target_search_doc.tag_text
```

服务端负责把业务规则字段映射到实际查询逻辑。

### 1.3 一期白名单不要过宽

一期只支持最影响推荐的字段。

过宽风险：

- LLM 输出不稳定。
- 服务端转查询复杂。
- 推荐解释不可复现。
- 评测困难。

---

## 2. P0 field 白名单

P0 含义：只要买家提到了，一期系统就应该能稳定解析、保存、校验、查询和解释。

### 2.1 标的类型与上市状态

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `target_type` | 标的类型 | `=` / `in` / `exclude` | `target_type` |
| `listed_status` | 上市 / 非上市 | `=` / `in` / `exclude` | `listed_status` |
| `listing_board` | 上市板块 | `in` / `exclude` | `listing_board` |
| `market_cap_yuan` | 市值范围 | `<=` / `>=` / `between` | `market_cap_yuan` |

示例：

```json
{
  "field": "listed_status",
  "operator": "=",
  "value_json": "unlisted",
  "constraint_type": "hard"
}
```

适用需求：

```text
非上市公司
上市公司标的
主板 / 创业板 / 科创板 / 北交所
市值 50 亿以内，可放宽到 100 亿
```

### 2.2 行业、赛道、产品、资质

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `industry` | 一级 / 二级行业 | `in` / `preferred_in` / `exclude` | `industry_primary / industry_secondary` |
| `sector` | 细分赛道 | `in` / `preferred_in` / `exclude` | `seller_target_tag` |
| `product` | 产品 / 服务 | `in` / `preferred_in` / `exclude` | `seller_target_tag / search_doc` |
| `certification` | 资质认证 | `in` / `preferred_in` | `seller_target_tag` |

示例：

```json
{
  "field": "industry",
  "operator": "in",
  "value_json": {
    "canonical_keys": ["healthcare"],
    "raw_terms": ["医药健康"],
    "include_descendants": true
  },
  "constraint_type": "hard"
}
```

适用需求：

```text
医药健康相关
医疗器械、医药商业、制药、中药、CXO
物联网、AI、集成电路、软件信息
新能源、新材料、综合能源
```

默认建议：

```text
industry 更适合硬筛；
sector / product 更适合召回和偏好排序。
```

### 2.3 区域与落地

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `operating_region` | 经营地要求 | `in` / `preferred_in` / `exclude` | `operating_regions_json` |
| `headquarter_region` | 总部所在地要求 | `in` / `preferred_in` | `headquarter_province/city` |
| `registered_region` | 注册地要求 | `in` / `preferred_in` | `registered_province/city` |
| `asset_region` | 资产所在地要求 | `in` / `preferred_in` | `asset_regions_json` |
| `relocation` | 是否迁址 | `=` | `accepts_relocation` |
| `return_investment` | 是否返投 / 固投 | `=` | `accepts_return_investment` |

示例：长三角 hard。

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

示例：浙江 preference。

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

默认规则：

```text
买家没明确说注册地时，不用注册地做硬筛；
优先匹配经营地 / 总部所在地 / 资产所在地；
注册地只作为辅助信息。
```

### 2.4 财务与经营规模

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `revenue_yuan` | 营收 | `>=` / `<=` / `between` | `current_revenue_yuan` |
| `net_profit_yuan` | 净利润 | `>=` / `<=` / `between` | `current_net_profit_yuan` |
| `total_profit_yuan` | 利润总额 | `>=` / `<=` / `between` | `current_total_profit_yuan` |
| `assets_yuan` | 资产总额 | `>=` / `<=` / `between` | `current_assets_yuan` |
| `debt_ratio` | 负债率 | `<=` / `between` | `current_debt_ratio` |
| `operating_cash_flow_yuan` | 经营现金流 | `>=` / `between` | `current_operating_cash_flow_yuan` |
| `profitability_status` | 盈利状态 | `=` / `in` | `profitability_status` |

示例：

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

适用需求：

```text
利润 2000 万以上
利润总额 1 亿以上
营收 30 亿以上
近三年净利润为正
不能亏损
现金流稳定
资产总额 30 亿以上
负债率不超过 50%
```

一期建议：

```text
明确不符合的排除；
未知的保留但降权或标记缺口。
```

### 2.5 估值、报价、PE、溢价

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `valuation_yuan` | 估值 | `<=` / `>=` / `between` | `valuation_yuan` |
| `asking_price_yuan` | 报价 | `<=` / `>=` / `between` | `asking_price_yuan` |
| `pe_ratio` | PE 倍数 | `<=` / `>=` / `between` | `pe_ratio` |
| `premium_rate` | 溢价率 | `<=` / `between` | `premium_rate` |

示例：

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

适用需求：

```text
PE 原则不超过 13
PE 一般不高于 15
估值 10-15 亿
市值 50 亿以内
可接受一定溢价
```

默认规则：

```text
“原则上不超过”默认作为 preference，而不是 hard；
“必须不超过 / 绝对不超过”才作为 hard。
```

### 2.6 交易结构、控股、并表、比例

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `can_control` | 是否可控股 | `=` | `can_control` |
| `can_consolidate` | 是否可并表 | `=` | `can_consolidate` |
| `equity_ratio` | 股权比例区间 | `>=` / `<=` / `between` | `transfer_ratio_min/max` |
| `deal_path` | 交易路径 | `in` / `preferred_in` | `deal_paths_json` |
| `payment_method` | 支付方式 | `in` / `preferred_in` | `accepted_payment_methods_json` |
| `minority_investment` | 是否接受参股 | `=` | `accepts_minority_investment` |
| `control_path` | 控制路径 | `in` / `preferred_in` | `control_path_options_json` |

示例：必须并表。

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

示例：51% 以上。

```json
{
  "field": "equity_ratio",
  "operator": ">=",
  "value_json": 51,
  "unit": "percent",
  "constraint_type": "hard"
}
```

非数字比例表达，不强转数字。

例如：

```text
控股权可谈
参股也可以
可并表即可
少数股权可接受
```

应该拆为：

```text
can_control
can_consolidate
minority_investment
control_path
equity_ratio_summary
```

而不是都转成：

```text
equity_ratio >= 51
```

### 2.7 风险与负面清单

| field | 业务含义 | 常用 operator | seller_target 对应 |
| --- | --- | --- | --- |
| `risk` | 风险排除 | `exclude` / `in` | `seller_target_risk` |
| `audit_status` | 审计意见 | `=` / `exclude` | `audit_status` |
| `st_or_delisting_risk` | ST / 退市风险 | `exclude` | `seller_target_risk` |
| `operation_stability` | 经营稳定性 | `=` / `preferred` | `operation_stability_status` |

示例：

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

适用需求：

```text
不能有涉诉、冻结、执行、违规违法
无退市风险
无重大偿债风险
无环保风险
不能有非标审计意见
不接受无法解决实际经营问题的标的
```

默认规则：

```text
confirmed_present / suspected 才硬排除；
unknown 默认不排除，但必须提示缺口。
```

除非买家明确说：

```text
必须材料齐全证明无风险
```

这时 unknown 可以使用：

```text
exclude / ask_user
```

---

## 3. P1 field 白名单

P1 含义：一期可以解析，但主要用于 rerank 和推荐解释，不一定做强 SQL 过滤。

| field | 业务含义 | 主要用途 |
| --- | --- | --- |
| `customer_type` | 客户类型 | 推荐理由 / 协同判断 |
| `customer_quality` | 客户质量 | rerank |
| `technology_barrier` | 技术壁垒 | rerank |
| `export_capability` | 出口能力 | rerank |
| `production_capacity` | 产能 | rerank |
| `team_stability` | 团队稳定性 | rerank |
| `management_retention` | 是否保留团队 | 交易可行性 |
| `earnout_dependency` | 对赌依赖 | 风险提示 |
| `synergy` | 产业协同 | rerank |
| `landing_value` | 招商落地价值 | rerank |
| `urgency` | 交易紧迫度 | 推荐解释 |

说明：

```text
这些字段重要，但通常不适合一期硬筛；
更适合给 LLM 做排序和理由生成。
```

---

## 4. operator 白名单

一期仅允许以下 operator：

| operator | 含义 | 适合字段 |
| --- | --- | --- |
| `=` | 等于 | 枚举 / 布尔 / 四值状态 |
| `!=` | 不等于 | 少量枚举 |
| `in` | 在集合中 | 行业、区域、交易方式 |
| `preferred_in` | 偏好在集合中 | 区域、赛道、产品 |
| `exclude` | 排除 | 风险、行业、赛道 |
| `>=` | 大于等于 | 数值 |
| `<=` | 小于等于 | 数值 |
| `between` | 区间 | 数值、比例 |
| `exists` | 有该信息 | 资质、风险、附件等 |
| `not_exists` | 无该信息 | 风险、负面项 |

一期不开放：

```text
regex
raw_sql
complex_expression
```

原因：

- 安全风险高。
- 输出不可控。
- 服务端难以验证。
- 评测和复现困难。

---

## 5. value_json 结构

### 5.1 数值型

简单值：

```json
20000000
```

区间：

```json
{
  "min": 20000000,
  "max": null,
  "unit": "yuan"
}
```

### 5.2 枚举型

```json
["unlisted", "pre_ipo"]
```

### 5.3 区域型

```json
{
  "raw_text": "长三角",
  "expanded_regions": ["上海市", "江苏省", "浙江省", "安徽省"],
  "scope": "operating_region"
}
```

### 5.4 标签型

```json
{
  "canonical_keys": ["healthcare.medical_device", "healthcare.cxo"],
  "raw_terms": ["医疗器械", "CXO"],
  "include_descendants": true
}
```

### 5.5 风险型

```json
{
  "risk_types": ["litigation", "environmental"],
  "risk_status": ["confirmed_present", "suspected"],
  "min_severity": "medium"
}
```

### 5.6 交易路径型

```json
{
  "paths": ["equity_transfer", "capital_increase", "voting_right_delegation"],
  "raw_text": "老股转让、定增、表决权委托均可"
}
```

---

## 6. 默认 unknown_policy

| 字段类型 | 默认 unknown_policy | 说明 |
| --- | --- | --- |
| 行业 | `allow_but_flag_gap` | 行业未知可保留，但提示 |
| 区域 hard | `allow_but_flag_gap` | 区域未知保留但靠后 |
| 利润 / 营收 hard | `allow_but_deprioritize` | 符合 > 未知 > 不符合 |
| PE | `allow_but_deprioritize` | PE 未知保留但降权 |
| 并表 / 控股 hard | `allow_but_flag_gap` | 未知保留但必须提示 |
| 风险排除 | `allow_but_flag_gap` | 未发现 / 未知不等于无风险 |
| 上市状态 hard | `allow_but_flag_gap` | 未知保留但提示 |
| 明确“必须证明”的要求 | `exclude` 或 `ask_user` | 如必须无环保风险证明 |

这符合已确认原则：

```text
符合 > 未知 > 不符合
```

---

## 7. 完整示例

原始需求：

```text
浙江省内非上市公司标的，医药健康相关，利润 2000 万以上，PE 原则不超过 13，要并表，标的地址长三角区域尤其浙江省内。
```

LLM 输出 constraint 应类似：

```json
[
  {
    "field": "industry",
    "operator": "in",
    "value_json": {
      "canonical_keys": ["healthcare"],
      "raw_terms": ["医药健康"],
      "include_descendants": true
    },
    "constraint_type": "hard"
  },
  {
    "field": "listed_status",
    "operator": "=",
    "value_json": "unlisted",
    "constraint_type": "hard"
  },
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
  },
  {
    "field": "operating_region",
    "operator": "preferred_in",
    "value_json": {
      "raw_text": "浙江省内",
      "expanded_regions": ["浙江省"],
      "scope": "operating_region"
    },
    "constraint_type": "preference",
    "weight": 0.8
  },
  {
    "field": "net_profit_yuan",
    "operator": ">=",
    "value_json": 20000000,
    "unit": "yuan",
    "constraint_type": "hard",
    "unknown_policy": "allow_but_deprioritize"
  },
  {
    "field": "pe_ratio",
    "operator": "<=",
    "value_json": 13,
    "constraint_type": "preference",
    "unknown_policy": "allow_but_deprioritize",
    "raw_text": "PE 原则不超过 13"
  },
  {
    "field": "can_consolidate",
    "operator": "=",
    "value_json": true,
    "constraint_type": "hard",
    "unknown_policy": "allow_but_flag_gap",
    "raw_text": "要并表"
  }
]
```

服务端据此：

```text
1. 排除明确非医药健康、明确非长三角、明确上市、明确利润低于 2000 万的标的。
2. 保留利润未知、PE 未知、并表未知的标的，但降权或标记缺口。
3. 浙江标的加分。
4. PE 达标加分，PE 超出但不严重可交给 LLM 判断。
5. 最终由 LLM 给推荐 list、理由、风险和信息缺口。
```

---

## 8. 已确认倾向

一期按以下倾向执行：

1. P0 白名单先覆盖当前买家意向样本，不追求无限扩展。
2. `operation_stability / team_stability / synergy` 等先放 P1，不做强硬筛。
3. PE 里的“原则不超过”默认作为 `preference`，不是 `hard`。
4. 风险 unknown 默认不排除，只提示缺口。
5. 区域默认用 `operating_region`，注册地只在买家明确要求时使用。
6. LLM 输出必须经服务端白名单校验。
7. 不允许 LLM 输出 SQL。

---

## 9. 下一步

当前确认：

1. `risk_type` 一期保持开放 text，同时 seed P0 风险字典用于归一化和解析参考。
2. `industry_primary / industry_secondary` 一期先用 text，辅以非穷尽一级行业字典和标签归一化。
3. `deal_path / payment_method / control_path` 一期已定义参考枚举并进入 seed。
4. `yes / no / unknown / likely` 作为交易状态类字段的统一四值表达。
5. LLM 只输出白名单 filter DSL / constraint，不直接写 SQL。

下一步建议：结合真实标的和买家意向样本做解析评测，验证字段覆盖率、误归一化率和推荐候选池质量。
