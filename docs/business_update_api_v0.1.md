# Match-MA 统一业务更新 API v0.1

日期：2026-05-28

范围：实现统一业务更新入口的第一版，只保存用户原始输入和可选绑定对象，暂不接 LLM 拆解，不生成 `extracted_action`。

---

## 1. 目标

统一业务更新入口用于承接营销顾问的混合更新信息，例如：

```text
上海启元项目：周二下午已与项目方见面沟通，预计明天小毕团队能拿到4月份的时间表。同步寻找其他买方，避免单一依赖。无锡某上市公司仍在联系中，计划近期进场。下周继续催促协议签署，并确认具体进场时间。
```

一期 v0.1 先解决：

- 保存原始文本。
- 记录输入类型。
- 允许绑定一个或多个标的。
- 允许绑定一个或多个买家意向。
- 返回业务更新记录。

暂不解决：

- AI 自动拆分。
- 自动更新标的字段。
- 自动更新买家意向。
- 自动更新买家-标的关系。
- 待复核动作队列。

---

## 2. 新建业务更新

```text
POST /api/v1/business-updates
```

请求示例：

```json
{
  "raw_text": "上海启元项目：周二下午已与项目方见面沟通。无锡某上市公司仍在联系中，计划近期进场。",
  "input_type": "text",
  "bound_seller_target_ids": ["26d78a25-961c-4763-8002-e8baedb8fa40"],
  "bound_buyer_intent_ids": ["64c9995b-6d1d-42c1-9f95-e8792cf0131a"],
  "metadata_json": {
    "source": "manual_test"
  }
}
```

返回：

```json
{
  "id": "uuid",
  "raw_text": "...",
  "input_type": "text",
  "processing_status": "pending",
  "bound_seller_target_ids_json": ["..."],
  "bound_buyer_party_ids_json": [],
  "bound_buyer_intent_ids_json": ["..."],
  "bound_recommendation_session_id": null,
  "created_by": "00000000-0000-0000-0000-000000000201",
  "created_at": "2026-05-28 ...",
  "metadata_json": {
    "source": "manual_test"
  }
}
```

---

## 3. 查询业务更新列表

```text
GET /api/v1/business-updates
```

可选过滤：

```text
GET /api/v1/business-updates?processing_status=pending
GET /api/v1/business-updates?seller_target_id={id}
GET /api/v1/business-updates?buyer_intent_id={id}
```

---

## 4. 查询业务更新详情

```text
GET /api/v1/business-updates/{business_update_id}
```

---

## 5. 后续演进

下一步可以在此基础上增加：

1. `POST /api/v1/business-updates/{id}/extracted-actions`：人工创建或后续由 LLM 生成 `extracted_action`。
2. `GET /api/v1/extracted-actions?business_update_id={id}`：查看待复核动作。
3. `POST /api/v1/extracted-actions/{id}/apply`：人工确认并写入业务表与 `action_application_log`。
4. 支持截图/附件输入，接入 OCR 和附件解析。
