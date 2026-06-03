# Match-MA Background Job API and Worker v0.1

日期：2026-05-28
状态：已实现第一版 Worker + business_update 占位处理器

---

## 1. 目标

第一版目标是跑通后台任务基础链路：

```text
API 创建 background_job
前端 / 调试人员查询 job 状态
Worker 从 PostgreSQL 领取 job
Worker 标记 succeeded / failed / retry_waiting
```

本版不接真实 LLM / OCR / embedding，先证明队列、Worker、业务更新处理链路和 `ai_trace` 写入可运行。

---

## 2. Job API

### 2.1 创建 job

```text
POST /api/v1/background-jobs
```

请求示例：

```json
{
  "job_type": "business_update_extract_actions",
  "queue_name": "llm",
  "entity_type": "business_update",
  "entity_id": "uuid",
  "payload_json": {
    "business_update_id": "uuid"
  }
}
```

### 2.2 查询 job 列表

```text
GET /api/v1/background-jobs
GET /api/v1/background-jobs?status=queued
GET /api/v1/background-jobs?job_type=business_update_extract_actions
GET /api/v1/background-jobs?queue_name=llm
GET /api/v1/background-jobs?entity_type=business_update&entity_id={id}
```

### 2.3 查询 job 详情

```text
GET /api/v1/background-jobs/{job_id}
```

### 2.4 取消 job

```text
POST /api/v1/background-jobs/{job_id}/cancel
```

当前限制：running job 暂不允许由 API 取消。

### 2.5 重试 job

```text
POST /api/v1/background-jobs/{job_id}/retry
```

当前仅允许重试：

```text
failed
cancelled
```

### 2.6 查询 job trace

```text
GET /api/v1/background-jobs/{job_id}/traces
```

当前可查 `ai_trace`。`business_update_extract_actions` 已会生成一条占位 trace，用于验证 Debug Mode 的数据链路。

---


### 2.7 Queue summary

```text
GET /api/v1/background-jobs/summary/queues
GET /api/v1/background-jobs/summary/queues?include_empty=true&lookback_hours=24
```

Purpose:

- Give frontend workbench and Debug Mode one endpoint to display worker queue health.
- Avoid requiring the frontend to issue separate list queries for `llm`, `ocr`, `embedding`, and `rerank`.

Response highlights:

```json
{
  "generated_at": "2026-06-03 ...",
  "totals": {
    "active_queue_count": 1,
    "failed_queue_count": 0,
    "active_job_count": 3,
    "queued_job_count": 2,
    "running_job_count": 1
  },
  "queues": [
    {
      "queue_name": "ocr",
      "health_status": "idle | active | has_failures",
      "active_count": 0,
      "counts": {
        "queued": 0,
        "retry_waiting": 0,
        "running": 0,
        "failed": 0,
        "recent_created": 5,
        "recent_succeeded": 5,
        "recent_failed": 0
      },
      "next_job": null,
      "latest_failed_job": null
    }
  ]
}
```

Default queues shown when `include_empty=true`:

```text
llm, ocr, embedding, rerank, default
```


### 2.8 Failure summary

```text
GET /api/v1/background-jobs/summary/failures
GET /api/v1/background-jobs/summary/failures?lookback_hours=168&limit=20
```

Purpose:

- Show failed jobs grouped by queue and job type.
- Give workbench and Debug Mode a compact list of recent failed jobs with `debug_ref` and related entity links.

Response highlights:

```json
{
  "totals": {
    "failed_job_count": 3,
    "failed_queue_count": 1,
    "failed_job_type_count": 1,
    "recent_failure_count": 3
  },
  "by_queue": [{ "queue_name": "llm", "failed_count": 3 }],
  "by_job_type": [{ "job_type": "business_update_extract_actions", "queue_name": "llm", "failed_count": 3 }],
  "recent_failures": [{ "id": "uuid", "job_type": "...", "debug_ref": {}, "related_entity_ref": {}, "can_retry": true, "retry_route": "/background-jobs/{id}/retry", "recommended_actions": [] }]
}
```

## 3. Business Update Process API

为了业务更新入口更方便创建任务，新增：

```text
POST /api/v1/business-updates/{business_update_id}/process
```

作用：

- 检查 business_update 是否存在。
- 如果已有未完成的 `business_update_extract_actions` job，则返回已有 job。
- 否则创建新的 `background_job`。
- 将 `business_update.processing_status` 从 `pending` / `failed` 更新为 `processing`。

返回示例：

```json
{
  "job_id": "uuid",
  "job_type": "business_update_extract_actions",
  "status": "queued",
  "queue_name": "llm",
  "business_update_id": "uuid"
}
```


### 3.1 Object Parse APIs

Buyer intent parse:

```text
POST /api/v1/buyer-intents/{buyer_intent_id}/parse
GET /api/v1/buyer-intents/{buyer_intent_id}/parse-status
```

Seller target parse:

```text
POST /api/v1/seller-targets/{seller_target_id}/parse
GET /api/v1/seller-targets/{seller_target_id}/parse-status
```

Both parse APIs use the same flow: API creates a background job, Worker calls LLM, supported fields are auto-applied, action_application_log and ai_trace are written, and search_doc rebuild is triggered.

---

## 4. Worker

### 4.1 启动命令

运行一次轮询后退出：

```text
python -m backend.app.worker --queue llm --once
```

持续轮询：

```text
python -m backend.app.worker --queue llm --sleep 2
```

### 4.2 当前行为

第一版 Worker：

1. 从 `background_job` 中用 `for update skip locked` 领取一个 job。
2. 标记为 `running`。
3. 调用对应 handler。
4. 标记为 `succeeded`。

### 4.3 Current job handlers

Worker currently supports these business jobs:

```text
business_update_extract_actions -> llm queue, node_name=business_update_extractor
buyer_intent_parse -> llm queue, node_name=buyer_intent_parser
seller_target_parse -> llm queue, node_name=seller_target_parser
seller_search_doc_rebuild -> embedding queue fan-out
buyer_intent_search_doc_rebuild -> embedding queue fan-out
embedding_generate -> embedding queue, node_name=*_embedding
recommendation_rerank -> rerank queue, node_name=recommendation_reranker
recommendation_report_generate -> llm queue, node_name=recommendation_report_writer
attachment_ocr_parse -> ocr queue, node_name=ocr_attachment_parser
model_node_test -> llm / embedding / rerank queue by node type
```

`business_update_extract_actions` calls LLM, extracts `extracted_action` rows from business updates, auto-applies safe actions, and writes `action_application_log`.

`buyer_intent_parse` calls LLM and parses natural-language buyer requirements into `buyer_intent` fields.

1. Use request `raw_requirement_text`, or fall back to `buyer_intent.raw_requirement_text`.
2. Use the default `buyer_intent_parser` node and prompt.
3. Expect LLM JSON output in the shape `{"fields": {...}}`.
4. Normalize money, PE, percentages, yes/no-like fields, listed status, and equity requirement fields.
5. Auto-update the `buyer_intent` snapshot.
6. Write one `action_application_log` row per field change with `source_type = buyer_intent_parse`.
7. Create `buyer_intent_search_doc_rebuild`; embedding workers refresh search_doc / embedding.
8. Write `ai_trace`; Debug Mode can inspect raw JSON, schema validation, tokens, latency, and errors.

`seller_target_parse` calls LLM and parses natural-language seller target descriptions into `seller_target` fields.

1. Use request `raw_target_text`, or fall back to target name, business summary, transaction summary, and risk summary.
2. Use the default `seller_target_parser` node and prompt.
3. Expect LLM JSON output in the shape `{"fields": {...}}`.
4. Normalize money, percentages, yes/no-like fields, listed status, and transfer flexibility.
5. Auto-update the `seller_target` snapshot.
6. Write one `action_application_log` row per field change with `source_type = seller_target_parse`.
7. Create `seller_search_doc_rebuild`; embedding workers refresh search_doc / embedding.
8. Write `ai_trace`; Debug Mode can inspect raw JSON, schema validation, tokens, latency, and errors.

`attachment_ocr_parse` is the v0.1 attachment/OCR skeleton.

1. Use `attachment.metadata_json.mock_extracted_text` or job `payload_json.mock_extracted_text` if provided.
2. Create a `parsed_document` row with `parser_name=ocr_attachment_parser`.
3. If mock text exists, mark attachment and parsed document as `parsed`, create an `evidence_span`, and write a succeeded OCR trace.
4. If no mock text exists, mark attachment and parsed document as `skipped`, create no evidence, and write a skipped OCR trace.
5. Debug Mode can inspect `/debug/entities/attachment/{attachment_id}`.

Example result_json:

```json
{
  "handled": true,
  "job_type": "seller_target_parse",
  "seller_target_id": "uuid",
  "applied_fields": ["business_summary", "current_net_profit_yuan", "can_consolidate"],
  "field_count": 3,
  "trace_created": true,
  "model_name": "qwen3.6-flash",
  "prompt_version": "v0.1.0",
  "schema_valid": true
}
```

---

## 5. Railway Worker 服务

当前代码已经具备 Worker 启动命令。由于 `business_update_extract_actions` 已能写入占位 trace，可以在 Railway 新增 Worker Service 来验证从 API 到后台任务再到 Debug Trace 的完整链路。

建议后续 Worker Service start command：

```text
python -m backend.app.worker --queue llm --sleep 2
```

后续也可以拆多个队列：

```text
python -m backend.app.worker --queue llm
python -m backend.app.worker --queue embedding
python -m backend.app.worker --queue rerank
python -m backend.app.worker --queue ocr
```
