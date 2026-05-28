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

### 4.3 business_update_extract_actions 占位处理器

当前已实现第一个业务 handler：

```text
business_update_extract_actions
```

它暂不调用真实 LLM，行为是：

1. 读取 `business_update` 原始输入和绑定对象。
2. 写入一条 `ai_trace`，`node_name = business_update_extractor`，`trace_type = parser`。
3. `parsed_output_json.actions = []`，明确标记 `extraction_status = placeholder`。
4. 将 `business_update.processing_status` 更新为 `parsed`。
5. 不创建 `extracted_action`，避免在真实抽取上线前产生误导性动作。

当前 result_json 类似：

```json
{
  "handled": true,
  "job_type": "business_update_extract_actions",
  "business_update_id": "uuid",
  "actions_created": 0,
  "trace_created": true,
  "message": "Placeholder handler completed; real LLM extraction is not implemented yet."
}
```

后续会把不同 job_type 路由到真实 handler，例如：

```text
business_update_extract_actions -> real LLM extractor
buyer_intent_parse -> LLM parser
embedding_generate -> embedding service
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
python -m backend.app.worker --queue ocr
```
