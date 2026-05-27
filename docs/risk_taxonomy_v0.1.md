# Match-MA 风险枚举与负面清单 v0.1

状态：一期建议方案  
范围：定义 `seller_target_risk.risk_type`、`risk_status`、`severity`、风险过滤规则，以及买家意向负面清单到 `buyer_intent_constraint` 的映射。本文用于后续 PostgreSQL schema、买家意向解析、推荐候选池过滤和推荐解释。

---

## 1. 设计原则

### 1.1 风险必须结构化，不只做标签

风险不同于普通标签。

普通标签回答：

```text
这个标的有什么特征？
```

风险字段回答：

```text
这个标的是否存在会影响推荐、交易或合规判断的问题？
```

风险需要表达：

- 风险类型。
- 风险状态。
- 风险等级。
- 证据来源。
- 是否待确认。
- 是否已解除。

因此风险使用独立表：

```text
seller_target_risk
```

不只放入 `seller_target_tag`。

### 1.2 unknown 不等于无风险

已确认：

```text
风险 unknown 默认不硬排除，但必须提示信息缺口。
```

默认推荐逻辑：

```text
confirmed_present / suspected => 可按买家要求排除或降权
not_found => 暂未发现，可提示“未发现”
confirmed_absent => 明确无该风险
unknown => 未知，不等于安全
```

除非买家明确要求：

```text
必须有材料证明无风险
```

否则 unknown 默认：

```text
allow_but_flag_gap
```

### 1.3 风险过滤只排除明确冲突

示例：

```text
买家排除重大诉讼
```

应排除：

```text
risk_type = litigation
risk_status in confirmed_present / suspected
severity >= medium
```

不应因为“诉讼未知”直接排除，除非买家明确要求证明无诉讼。

---

## 2. seller_target_risk 建议字段

```text
seller_target_risk
- id
- team_id
- seller_target_id
- risk_type
- risk_status
- severity
- title
- description
- amount_yuan nullable
- occurred_at nullable
- resolved_at nullable
- source_type
- source_id
- evidence_id
- confidence
- review_status
- created_at / created_by
- updated_at / updated_by
```

说明：

| 字段 | 说明 |
| --- | --- |
| `risk_type` | 风险类型，使用本文枚举 |
| `risk_status` | 风险状态：确认存在、疑似、暂未发现等 |
| `severity` | 风险等级 |
| `amount_yuan` | 涉及金额，如诉讼金额、执行金额 |
| `occurred_at` | 风险发生时间 |
| `resolved_at` | 风险解除时间 |
| `source_type` | 来源：附件、用户输入、公开调研等 |
| `evidence_id` | 证据片段 |
| `review_status` | 待确认 / 已确认 / 忽略等 |

---

## 3. risk_status 枚举

| 枚举 | 中文 | 说明 | 推荐默认处理 |
| --- | --- | --- | --- |
| `confirmed_present` | 确认存在 | 有明确证据表明风险存在 | 按买家规则排除或降权 |
| `suspected` | 疑似存在 | 有迹象但未完全确认 | 按买家规则排除或降权 |
| `not_found` | 暂未发现 | 调研或材料中暂未发现 | 可推荐，但说明“暂未发现” |
| `confirmed_absent` | 明确不存在 | 有材料或确认信息证明不存在 | 可作为正向说明 |
| `unknown` | 未知 | 没有足够信息判断 | 保留但标记缺口 |

---

## 4. severity 枚举

| 枚举 | 中文 | 说明 |
| --- | --- | --- |
| `low` | 低 | 不太影响交易判断，或金额/影响较小 |
| `medium` | 中 | 需要提示，可能影响推荐优先级 |
| `high` | 高 | 明显影响推荐或交易推进 |
| `critical` | 严重 | 原则上应排除或需要特别审批 |
| `unknown` | 未知 | 风险等级暂不明确 |

默认建议：

```text
买家说“重大风险”时，默认 severity >= medium。
买家说“任何涉诉都不要”时，不设 severity 门槛。
```

---

## 5. P0 risk_type 枚举

P0 含义：一期必须支持，买家需求和负面清单中高频出现。

### 5.1 法律与司法风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `litigation` | 诉讼风险 | 未决诉讼、重大诉讼、合同纠纷等 | 涉诉、重大诉讼、无诉讼 |
| `arbitration` | 仲裁风险 | 仲裁案件 | 仲裁纠纷 |
| `enforcement` | 被执行风险 | 被执行人、执行案件 | 被执行、执行风险 |
| `dishonest_debtor` | 失信被执行 | 失信被执行人 | 失信、老赖 |
| `asset_freeze` | 资产冻结 | 股权、账户、资产冻结 | 冻结、查封 |
| `equity_pledge` | 股权质押 | 股权质押比例较高或异常 | 股权质押、高质押 |

### 5.2 合规与监管风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `regulatory_violation` | 违法违规 | 行政处罚、重大违法违规 | 违规违法、行政处罚 |
| `environmental` | 环保风险 | 环评、排污、环保处罚 | 环保风险、环保处罚 |
| `safety_production` | 安全生产风险 | 安全事故、安全生产处罚 | 安全生产事故 |
| `tax` | 税务风险 | 税务处罚、欠税、税务争议 | 税务风险、欠税 |
| `data_compliance` | 数据合规风险 | 数据安全、隐私合规 | 数据合规、隐私风险 |
| `license_or_permit` | 资质许可风险 | 关键资质缺失、到期、被吊销 | 资质不全、许可证问题 |

### 5.3 财务与偿债风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `high_debt_ratio` | 高负债 | 负债率高于买家容忍范围 | 高负债、负债率高 |
| `debt_repayment` | 偿债风险 | 到期债务、流动性压力 | 重大偿债风险 |
| `cash_flow` | 现金流风险 | 经营现金流不稳定或为负 | 现金流差、现金流不稳定 |
| `loss_making` | 亏损风险 | 连续亏损或利润为负 | 不接受亏损 |
| `audit_opinion` | 审计意见异常 | 非标、保留、无法表示等 | 非标审计意见 |
| `financial_fraud` | 财务造假风险 | 财务真实性存疑 | 财务造假、报表不实 |
| `goodwill_impairment` | 商誉减值风险 | 大额商誉减值风险 | 商誉减值 |

### 5.4 上市公司与资本市场风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `st_status` | ST 风险 | 已 ST 或可能 ST | ST、*ST |
| `delisting` | 退市风险 | 退市风险、退市整理 | 退市风险 |
| `share_price_abnormal` | 股价异常风险 | 股价异常波动、操纵疑虑 | 股价异常 |
| `major_shareholder_risk` | 大股东风险 | 控股股东质押、占款、违规等 | 大股东风险 |

### 5.5 经营与业务风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `operation_stability` | 经营稳定性风险 | 经营不稳定、业务不可持续 | 经营不稳定 |
| `customer_concentration` | 客户集中风险 | 单一客户依赖过高 | 客户集中 |
| `supplier_concentration` | 供应商集中风险 | 关键供应商依赖 | 供应链风险 |
| `technology_obsolescence` | 技术过时风险 | 技术路线落后 | 技术过时 |
| `overcapacity` | 产能过剩风险 | 行业或企业产能过剩 | 产能过剩 |
| `cyclical_industry` | 周期行业风险 | 行业周期性强 | 周期行业 |
| `market_decline` | 市场下滑风险 | 下游需求下滑 | 市场下滑 |

### 5.6 交易可行性与治理风险

| risk_type | 中文 | 说明 | 常见买家表达 |
| --- | --- | --- | --- |
| `control_uncertainty` | 控制权不确定 | 控股、表决权、董事会控制不确定 | 控制权不清晰 |
| `consolidation_uncertainty` | 并表不确定 | 会计并表路径不明确 | 无法并表 |
| `ownership_dispute` | 权属纠纷 | 股权、资产、土地、知识产权权属争议 | 权属不清、产权纠纷 |
| `related_party_transaction` | 关联交易风险 | 关联交易占比高或不透明 | 关联交易风险 |
| `earnout_dependency` | 对赌依赖风险 | 需要依赖对赌解决经营或估值问题 | 依赖对赌、对赌风险 |
| `management_instability` | 管理团队不稳定 | 核心团队可能流失 | 团队不稳定 |

### 5.7 其他

| risk_type | 中文 | 说明 |
| --- | --- | --- |
| `other` | 其他风险 | 无法归入以上类别 |

---

## 6. P1 risk_type 枚举

P1 含义：一期可以保留在文本或 `other`，后续再细化；如果数据源明确，也可以提前使用。

| risk_type | 中文 | 说明 |
| --- | --- | --- |
| `ip_dispute` | 知识产权纠纷 | 专利、商标、软件著作权争议 |
| `land_property` | 土地房产风险 | 土地证、房产证、租赁、抵押等问题 |
| `labor_dispute` | 劳动争议 | 劳动仲裁、欠薪、员工安置 |
| `product_quality` | 产品质量风险 | 质量事故、召回、投诉 |
| `food_drug_safety` | 食品药品安全风险 | 食药监处罚、产品安全问题 |
| `export_control` | 出口管制风险 | 制裁、出口限制、海外合规 |
| `foreign_exchange` | 外汇风险 | 跨境结算、外汇合规 |
| `government_subsidy_dependency` | 政府补贴依赖 | 利润依赖补贴 |
| `single_project_dependency` | 单项目依赖 | 收入利润高度依赖单一项目 |
| `key_person_dependency` | 关键人依赖 | 高度依赖创始人或核心个人 |

---

## 7. 买家意向负面清单映射

买家自然语言中的负面清单应映射到 `buyer_intent_constraint`。

### 7.1 示例：涉诉、冻结、执行、违规违法

原文：

```text
不能接受标的公司存在重大风险，如涉诉、冻结、执行、违规违法。
```

constraint：

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
  "unknown_policy": "allow_but_flag_gap",
  "raw_text": "不能接受涉诉、冻结、执行、违规违法"
}
```

### 7.2 示例：无退市风险

```json
{
  "field": "risk",
  "operator": "exclude",
  "value_json": {
    "risk_types": ["delisting", "st_status"],
    "risk_status": ["confirmed_present", "suspected"],
    "min_severity": "medium"
  },
  "constraint_type": "hard",
  "unknown_policy": "allow_but_flag_gap",
  "raw_text": "无退市风险"
}
```

### 7.3 示例：不接受高负债

```json
{
  "field": "risk",
  "operator": "exclude",
  "value_json": {
    "risk_types": ["high_debt_ratio", "debt_repayment"],
    "risk_status": ["confirmed_present", "suspected"],
    "min_severity": "medium"
  },
  "constraint_type": "hard",
  "unknown_policy": "allow_but_flag_gap",
  "raw_text": "不接受高负债或重大偿债风险"
}
```

如果买家明确给出负债率阈值，例如：

```text
负债率不超过 50%
```

应优先解析为：

```text
field = debt_ratio
operator = <=
value_json = 0.5
```

而不是只做风险标签。

### 7.4 示例：不接受亏损

```json
{
  "field": "risk",
  "operator": "exclude",
  "value_json": {
    "risk_types": ["loss_making"],
    "risk_status": ["confirmed_present", "suspected"],
    "min_severity": "low"
  },
  "constraint_type": "hard",
  "unknown_policy": "allow_but_deprioritize",
  "raw_text": "不接受亏损"
}
```

如果买家明确要求利润大于 0，也可同时解析为：

```text
field = net_profit_yuan
operator = >
value_json = 0
```

一期 operator 白名单未开放 `>`，可以用：

```text
field = net_profit_yuan
operator = >=
value_json = 1
unit = yuan
```

---

## 8. 风险写入规则

### 8.1 来源

风险可来自：

- 附件解析。
- 用户手动输入。
- 统一业务更新。
- 聊天截图 OCR。
- 联网调研。
- 系统计算，例如负债率过高。

### 8.2 是否自动写入

建议：

| 风险来源 | 默认处理 |
| --- | --- |
| 用户明确输入 | 可进入待确认，重要风险不自动应用 |
| 附件明确披露 | 进入待确认或高置信自动写入，保留来源 |
| 联网调研发现 | 进入待确认，避免误伤 |
| 系统计算风险 | 可自动标记，但保留计算依据 |
| LLM 推测 | 不直接写正式风险，只作为待确认 |

### 8.3 风险冲突

同一风险可能多来源冲突。

示例：

```text
公开调研：暂未发现重大诉讼
用户输入：存在合同纠纷
```

处理：

- 不直接覆盖。
- 保留多条风险记录或来源记录。
- 当前摘要中提示冲突。
- 进入待确认。

---

## 9. 推荐过滤规则

### 9.1 默认规则

当买家有风险排除 constraint：

```text
operator = exclude
```

服务端按以下逻辑处理：

```text
risk_status in confirmed_present / suspected
and risk_type 命中
and severity >= min_severity
=> 排除或强降权
```

### 9.2 unknown 处理

默认：

```text
risk_status = unknown
=> 不排除，但在推荐结果中提示缺口
```

示例推荐提示：

```text
风险缺口：暂未确认是否存在环保处罚，建议推进前补充核查。
```

### 9.3 not_found 处理

```text
risk_status = not_found
=> 不排除，可提示“公开调研暂未发现”
```

但文案不能写成“无风险”，除非：

```text
risk_status = confirmed_absent
```

### 9.4 severity 处理

如果买家说：

```text
重大风险
```

默认：

```text
min_severity = medium
```

如果买家说：

```text
任何诉讼都不要
```

则：

```text
min_severity = low
```

---

## 10. 风险在 UI 中的展示

### 10.1 标的详情页

风险区建议展示：

```text
风险标签：诉讼疑似 / 环保未知 / 审计意见正常
风险摘要：公开调研暂未发现重大诉讼；环保材料未上传，待核查。
```

风险明细：

```text
风险类型       状态        等级     来源                  操作
诉讼风险       暂未发现    -        联网调研 2026-05-26    查看来源
环保风险       未知        -        材料缺失               补充材料
高负债         确认存在    中       2024审计报告 P12       查看证据
```

### 10.2 推荐卡片

推荐卡片折叠态只展示摘要：

```text
风险：负债率 58% 接近上限；环保材料待确认
```

展开或报告中展示：

```text
风险与缺口：
- 负债率 58%，高于买家偏好 50%，但未达绝对排除条件。
- 环保合规材料未上传，建议推荐前补充核查。
```

---

## 11. 当前确认与后续评测

当前确认：

1. P0 risk_type 先不压缩，作为一期推荐过滤和负面清单解析的参考字典。
2. `seller_target_risk.risk_type` 一期保持开放 text，不加数据库 check constraint，避免真实业务样本无法入库。
3. `equity_pledge` 仍作为 P0，但推荐规则可按上市/非上市、严重程度和买家要求决定是否触发。
4. `data_compliance` 仍作为 P0，不并入 `regulatory_violation`，避免数字经济/医疗数据类项目丢失重要风险语义。
5. 风险金额 `amount_yuan` 一期先存储，不作为核心硬筛字段。
6. 风险状态冲突一期通过来源、置信度和 review_status 处理，不单独增加“当前采用风险状态”字段。
7. 行业差异化风险权重留到推荐评测阶段再调优，不在一期 schema 中固化。
