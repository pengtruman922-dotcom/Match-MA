# Match-MA Background Job API and Worker v0.1

日期：2026-05-28
状态：已实现第一版骨架

---

## 1. 目标

第一版目标是跑通后台任务基础链路：

```text
API 创建 background_job
前端 / 调试人员查询 job 状态
Worker 从 PostgreSQL 领取 job
Worker 标记 succeeded / failed / retry_waiting
```

本版不接真实 LLM / OCR / embedding，只证明队列和 Worker 机制可运行。

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

当前可查 `ai_trace`，但本版 Worker 尚未生成真实 trace。

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
3. 调用占位 handler。
4. 标记为 `succeeded`。

当前 result_json 类似：

```json
{
  "handled": false,
  "job_type": "business_update_extract_actions",
  "message": "No real job handler is implemented yet."
}
```

后续会把不同 job_type 路由到真实 handler，例如：

```text
business_update_extract_actions -> LLM extractor
buyer_intent_parse -> LLM parser
embedding_generate -> embedding service
```

---

## 5. Railway Worker 服务

当前代码已经具备 Worker 启动命令，但是否在 Railway 新增 Worker Service 可以等真实 handler 接入前后再决定。

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
