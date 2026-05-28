# Match-MA Extracted Action API v0.1

日期：2026-05-28
状态：过渡版 API 文档，已按最新产品口径修订

> 口径说明：早期文档中的 `buyer_intent_suggestion` / `buyer_intent_update_suggestion` 已废弃。最新口径为 `buyer_intent_update`。业务更新流程从“确认后应用”调整为“明确动作先自动应用，再复核 / 编辑 / 回退”。当前已部署后端仍处于最小可验证阶段，数据库迁移完成后以后续 API 文档为准。

---

## 1. 目标

`business_update` 保存用户原始输入。

`extracted_action` 表示从原始输入中拆出的业务动作。

一期后续目标：

```text
business_update -> background_job -> LLM/OCR/解析 -> extracted_action -> 自动应用 -> action_application_log -> 待复核
```

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
  "confidence": 0.9,
  "metadata_json": {
    "source": "manual_test"
  }
}
```

---

## 3. action_type 最新清单

```text
seller_fact_update
seller_event
buyer_seller_relation_update
buyer_intent_target_exclusion
buyer_intent_update
buyer_level_blacklist_suggestion
internal_note
unresolved_item
```

废弃：

```text
buyer_intent_suggestion
buyer_intent_update_suggestion
```

---

## 4. 查询动作列表

```text
GET /api/v1/extracted-actions
GET /api/v1/extracted-actions?business_update_id={id}
GET /api/v1/extracted-actions?review_status=pending_review
GET /api/v1/extracted-actions?target_entity_type=seller_target&target_entity_id={id}
```

---

## 5. 查询动作详情

```text
GET /api/v1/extracted-actions/{extracted_action_id}
```

---

## 6. 复核状态

```text
PATCH /api/v1/extracted-actions/{extracted_action_id}
```

请求示例：

```json
{
  "review_status": "accepted"
}
```

当前沿用字段名 `review_status`，但语义已调整为自动应用后的复核状态。

| 值 | 新语义 |
| --- | --- |
| `pending_review` | 待复核，可能尚未应用或无法自动应用 |
| `auto_accepted` | 系统已自动应用，待用户复核 |
| `accepted` | 用户已复核并接受 |
| `rejected` | 用户认为错误，待回退或已回退 |
| `ignored` | 用户忽略 |

---

## 7. 应用动作

```text
POST /api/v1/extracted-actions/{extracted_action_id}/apply
```

当前已部署最小版只支持：

```text
action_type = seller_fact_update
target_entity_type = seller_target
```

后续目标：

- `buyer_intent_update` 自动更新 `buyer_intent`。
- `buyer_seller_relation_update` 更新 `buyer_seller_relation` / `relation_event`。
- 所有应用动作写入 `action_application_log`。
- 自动应用后进入待复核。
- 支持编辑和回退。

---

## 8. 与 Debug Mode 的关系

后续 LLM 自动拆解时，每次解析应写入：

```text
background_job
ai_trace
extracted_action
action_application_log
```

管理员开启 Debug Mode 后，可以查看：

- job 状态。
- prompt。
- 模型配置。
- 原始输出。
- parsed JSON。
- schema 校验错误。
- token / 耗时 / 费用。
- 应用日志和错误信息。
