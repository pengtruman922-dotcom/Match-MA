# Match-MA Extracted Action API v0.1

日期：2026-05-28

范围：实现 `extracted_action` 的非 AI 版本，用于先跑通“业务更新 -> 动作队列 -> 人工复核状态”的数据链路。

---

## 1. 目标

`business_update` 保存用户原始输入。

`extracted_action` 表示从原始输入中拆出来的一条待处理动作。

一期 v0.1 先允许人工创建动作，后续再由 LLM 自动生成。

---

## 2. 创建动作

```text
POST /api/v1/business-updates/{business_update_id}/extracted-actions
```

请求示例：

```json
{
  "action_type": "seller_event",
  "target_entity_type": "seller_target",
  "target_entity_id": "26d78a25-961c-4763-8002-e8baedb8fa40",
  "proposed_changes_json": {
    "event_summary": "周二下午已与项目方见面沟通，无锡某上市公司计划近期进场。"
  },
  "raw_evidence_text": "周二下午已与项目方见面沟通。无锡某上市公司仍在联系中，计划近期进场。",
  "confidence": 1,
  "metadata_json": {
    "source": "manual_test"
  }
}
```

创建后：

- `review_status` 默认 `pending_review`。
- 如果业务更新状态是 `pending / processing`，会更新为 `parsed`。
- 不会自动改标的、买家意向或关系表。

---

## 3. 查询动作列表

```text
GET /api/v1/extracted-actions
GET /api/v1/extracted-actions?business_update_id={id}
GET /api/v1/extracted-actions?review_status=pending_review
GET /api/v1/extracted-actions?target_entity_type=seller_target&target_entity_id={id}
```

---

## 4. 查询动作详情

```text
GET /api/v1/extracted-actions/{extracted_action_id}
```

---

## 5. 更新复核状态

```text
PATCH /api/v1/extracted-actions/{extracted_action_id}
```

请求示例：

```json
{
  "review_status": "accepted"
}
```

更新复核状态本身不执行应用动作。

允许状态沿用数据库枚举：

```text
pending_review
accepted
rejected
auto_accepted
ignored
```

---

## 6. 后续演进

## 6. 应用动作

```text
POST /api/v1/extracted-actions/{extracted_action_id}/apply
```

当前只支持：

```text
action_type = seller_fact_update
target_entity_type = seller_target
```

应用逻辑：

1. 要求 `review_status` 为 `accepted` 或 `auto_accepted`。
2. 读取 `proposed_changes_json`。
3. 只允许更新标的的白名单字段。
4. 更新 `seller_target`。
5. 写入 `action_application_log`。
6. 写入 `extracted_action.applied_at`。
7. 刷新 `business_update.processing_status` 为 `applied` 或 `partially_applied`。

响应示例：

```json
{
  "status": "applied",
  "extracted_action_id": "uuid",
  "business_update_id": "uuid",
  "entity_type": "seller_target",
  "entity_id": "uuid",
  "applied_fields": ["business_summary", "information_status"]
}
```

---

## 7. 后续演进

下一步：

1. 支持 `seller_event` 生成事件时间线。
2. 支持 `buyer_intent_suggestion` 只生成显眼 suggestion，不自动改买家意向。
3. 支持 `buyer_seller_relation_update` 更新买家-标的关系。
4. 后续接入 LLM，由 LLM 根据 `business_update.raw_text` 自动生成 `extracted_action`。
