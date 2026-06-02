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

### 4.3 ??? job handlers

?? Worker ???????????????

```text
business_update_extract_actions -> llm queue, node_name=business_update_extractor
buyer_intent_parse -> llm queue, node_name=buyer_intent_parser
seller_search_doc_rebuild -> embedding queue fan-out
buyer_intent_search_doc_rebuild -> embedding queue fan-out
embedding_generate -> embedding queue, node_name=*_embedding
recommendation_rerank -> rerank queue, node_name=recommendation_reranker
recommendation_report_generate -> llm queue, node_name=recommendation_report_writer
model_node_test -> llm / embedding / rerank queue by node type
```

`business_update_extract_actions` ????? LLM???????? `extracted_action`?????????????/???????? `action_application_log`?

`buyer_intent_parse` ????? LLM????????????? `buyer_intent` ?????

1. ?? `buyer_intent.raw_requirement_text` ????????
2. ?? `buyer_intent_parser` ?? Prompt?
3. ?? LLM????? `{"fields": {...}}` JSON?
4. ?????????PE??????????/??/??????????????????????? JSON?
5. ???? `buyer_intent` ?????
6. ????????? `action_application_log`?`source_type = buyer_intent_parse`?
7. ?? `buyer_intent_search_doc_rebuild`????? search_doc / embedding?
8. ?? `ai_trace`?Debug Mode ?????????? JSON?????????

?? result_json ???

```json
{
  "handled": true,
  "job_type": "buyer_intent_parse",
  "buyer_intent_id": "uuid",
  "applied_fields": ["intent_summary", "min_net_profit_yuan", "requires_consolidation"],
  "field_count": 3,
  "trace_created": true,
  "model_name": "qwen3.6-flash",
  "prompt_version": "v0.2.0",
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
