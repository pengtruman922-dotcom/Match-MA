# Match-MA 一期最小业务 API v0.1

日期：2026-05-27

范围：定义并落地最小可用业务 API，用于验证核心对象可以通过人工输入创建、列表查询和详情查询。当前不接 LLM，不做去重、附件、业务更新和推荐。

---

## 1. 设计目标

本阶段只解决三件事：

1. `seller_target` 可以人工创建和查询。
2. `buyer_intent` 可以人工创建和查询。
3. `seller_target` 和 `buyer_intent` 可以通过 PATCH 维护，通过 DELETE 软删除测试数据。
4. Railway + PostgreSQL + Alembic + FastAPI 能支持真实业务表读写。

暂不实现：

- 标的查重。
- 买家主体创建。
- 附件上传和解析。
- LLM 意向解析。
- 统一业务更新。
- 推荐候选池和推荐结果。
- 权限系统。

---

## 2. 默认数据空间

当前最小 API 默认写入 seed 中的默认数据空间：

```text
team_id      = 00000000-0000-0000-0000-000000000001
workspace_id = 00000000-0000-0000-0000-000000000101
created_by  = 00000000-0000-0000-0000-000000000201
updated_by  = 00000000-0000-0000-0000-000000000201
```

这是一期开发测试策略，不代表最终权限模型。

---

## 3. 标的 API

### 3.1 新建标的

```text
POST /api/v1/seller-targets
```

最小请求：

```json
{
  "target_name": "上海启元项目"
}
```

可选字段：

```json
{
  "target_name": "上海启元项目",
  "target_type": "company",
  "industry_primary": "healthcare",
  "industry_secondary": "medical_device",
  "headquarter_province": "浙江省",
  "headquarter_city": "杭州市",
  "listed_status": "unlisted",
  "current_revenue_yuan": 500000000,
  "current_net_profit_yuan": 25000000,
  "valuation_yuan": 320000000,
  "pe_ratio": 12.8,
  "is_for_sale": "yes",
  "can_control": "unknown",
  "can_consolidate": "unknown",
  "business_summary": "医疗器械相关标的，利润约2500万。"
}
```

说明：

- `target_name` 是唯一必填业务字段。
- 新建后默认 `recommendation_status = recommendable`。
- 新建后默认 `information_status = insufficient`，符合“一句话建档，后续完善”的产品原则。

### 3.2 标的列表

```text
GET /api/v1/seller-targets?limit=50&offset=0
GET /api/v1/seller-targets?q=启元
```

当前支持：

- 按更新时间倒序。
- 简单关键词搜索 `target_name / business_summary`。
- 默认只查默认 `team/workspace`。

### 3.3 标的详情

```text
GET /api/v1/seller-targets/{seller_target_id}
```

---

## 4. 买家意向 API

### 4.1 新建买家意向

```text
POST /api/v1/buyer-intents
```

最小请求：

```json
{
  "intent_name": "浙江国资医药健康并表需求"
}
```

可选字段：

```json
{
  "intent_name": "浙江国资医药健康并表需求",
  "raw_requirement_text": "浙江省内非上市公司，医药健康相关，利润2000万元以上，PE原则不超过13倍，要并表，长三角可接受。",
  "industry_primary": "healthcare",
  "region_scope_summary": "浙江优先，长三角可接受",
  "min_net_profit_yuan": 20000000,
  "max_pe": 13,
  "requires_consolidation": "yes",
  "preferred_listed_status": "unlisted",
  "negative_summary": "排除重大违法违规和明显无法并表项目。"
}
```

说明：

- 当前先人工填写结构化字段。
- 后续 LLM 意向解析会把 `raw_requirement_text` 解析为主表字段和 `buyer_intent_constraint`。

### 4.2 买家意向列表

```text
GET /api/v1/buyer-intents?limit=50&offset=0
GET /api/v1/buyer-intents?q=医药
```

当前支持：

- 按更新时间倒序。
- 简单关键词搜索 `intent_name / raw_requirement_text`。

### 4.3 买家意向详情

```text
GET /api/v1/buyer-intents/{buyer_intent_id}
```

---

### 3.4 标的更新

```text
PATCH /api/v1/seller-targets/{seller_target_id}
```

示例：

```json
{
  "target_name": "杭州启元三号项目",
  "information_status": "normal",
  "business_summary": "医疗器械相关标的，利润约2500万，信息已人工确认。"
}
```

说明：

- 只更新请求体里显式传入的字段。
- 直接 API 更新会写入基础 `action_application_log`，用于后续详情页更新记录。

### 3.5 标的软删除

```text
DELETE /api/v1/seller-targets/{seller_target_id}
```

说明：

- 不物理删除。
- 写入 `deleted_at / deleted_by`。
- 列表和详情默认不返回软删除数据。

---

### 4.4 买家意向更新

```text
PATCH /api/v1/buyer-intents/{buyer_intent_id}
```

示例：

```json
{
  "status": "paused",
  "pause_reason": "买家阶段性暂停收购",
  "preference_summary": "后续如恢复收购，仍优先关注浙江医药健康标的。"
}
```

说明：

- 只更新请求体里显式传入的字段。
- 直接 API 更新会写入基础 `action_application_log`。

### 4.5 买家意向软删除

```text
DELETE /api/v1/buyer-intents/{buyer_intent_id}
```

说明：

- 不物理删除。
- 写入 `deleted_at / deleted_by`。
- 列表和详情默认不返回软删除数据。

---

## 5. 下一步

建议下一步继续：

1. 增加 `buyer_party` 最小 API，或把新建买家意向扩展为“可选创建买家主体”。
2. 增加统一错误码和字段枚举校验。
3. 增加详情页更新记录 API，读取 `action_application_log`。
4. 进入统一业务更新 API 设计。
