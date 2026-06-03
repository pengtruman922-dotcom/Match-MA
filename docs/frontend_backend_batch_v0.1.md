# Frontend / Backend Batch v0.1

本批次目标：安全接入 Bolt 前端草稿，并补齐前端当前最需要的后端查询与 Debug 能力。

## 1. 前端接入边界

- Bolt 草稿只合并 `frontend/` 目录。
- 不合并 Bolt 根目录 `.env`、`.gitignore`、`package.json`、`package-lock.json`、`.bolt/`。
- 不提交 `frontend/node_modules/` 和 `frontend/dist/`。
- 前端 API Base URL 由 `frontend/.env.example` 中的 `VITE_API_BASE_URL` 控制。

## 2. 后端新增接口

### 工作台

```text
GET /api/v1/workbench
```

返回：

- `groups`：待复核动作分组。
- `recent_updates`：最近业务更新。
- `recent_relations`：最近买家-标的关系进展。
- `overview`：待复核、最近更新、失败任务、运行任务、关系总数。

```text
GET /api/v1/workbench/task-board
```

前端工作台任务板优先使用该聚合接口，返回：

- `groups`：按业务动作分组的待复核任务，包含 `task_title`、`task_subtitle`、`task_priority`、`review_route`、`debug_ref`。
- `auto_applied_recent`：最近自动应用、待用户复核/回看的动作。
- `exception_items`：失败后台任务，方便从工作台进入 Debug Mode。
- `recent_activity`：业务更新、关系事件、后台任务混合时间线。
- `quick_actions`：工作台右侧快捷操作配置。
- `overview.mode`：固定为 `auto_apply_then_review`，对应“先自动应用，再复核/回退”的产品口径。

### 关系与跟进

```text
GET /api/v1/relations
GET /api/v1/relations/{relation_id}
GET /api/v1/relations/{relation_id}/events
GET /api/v1/relation-events
GET /api/v1/buyer-intent-target-exclusions
```

用途：

- 标的详情页展示“关系/跟进”。
- 买家详情页展示相关标的关系。
- 推荐、沟通、尽调、终止等事件进入 `relation_event`。
- “不感兴趣/硬排除”进入 `buyer_intent_target_exclusion`。

### Debug Mode

```text
GET /api/v1/debug/business-updates/{business_update_id}
GET /api/v1/debug/recommendation-sessions/{session_id}
GET /api/v1/debug/entities/{entity_type}/{entity_id}
GET /api/v1/debug/center
```

`/debug/entities/{entity_type}/{entity_id}` 是统一入口，当前支持：

- `business_update`
- `recommendation_session`
- `background_job`
- `model_node_config`
- `recommendation_report`

业务更新 Debug 返回同一业务更新下的：

- `business_update`
- `jobs`
- `traces`
- `actions`
- `application_logs`

推荐会话 Debug 返回会话、候选生成/重排/报告相关的 jobs、traces、messages、selected_items、reports、relations、relation_events。

后台任务 Debug 返回单个 job、同 job traces、同 correlation/entity 的 related_jobs。

模型节点 Debug 返回单个 node、最近节点测试 jobs、节点相关 traces；用于设置页调试每个 LLM / embedding / rerank 节点。

推荐报告 Debug 返回单个 report、所属 session、报告生成 jobs、报告生成 traces、报告消息；用于定位“生成报告”按钮后的 LLM 输出、fallback 内容或错误。

`/debug/center` 是 Debug Mode 首页聚合接口，前端不需要自行拼装任务、Trace、业务更新和推荐会话：

- `overview`：失败任务、运行任务、失败 Trace、近 24 小时 Trace、近 7 天业务更新/推荐会话等计数，并带 `health_level`。
- `failed_jobs` / `running_jobs`：后台任务卡片列表，带 `debug_ref` 和关联业务对象 `related_entity_ref`。
- `recent_traces` / `failed_traces`：最近 AI Trace 和异常 Trace，包含模型、节点、token、延迟、原始输出预览。
- `recent_business_updates`：最近业务更新的处理状态、动作数、应用日志数、任务数、Trace 数。
- `recent_recommendation_sessions`：最近推荐会话的状态、已选数、报告数、任务数、Trace 数。
- `model_node_test_failures`：模型节点测试失败列表，便于从设置页/Debug Mode 追踪某个节点。
- `quick_actions`：前端右侧快捷入口配置。

这些接口用于测试人员查看 LLM 原始输出、JSON、错误、应用日志和自动应用结果。

## 3. 动作应用能力

`POST /api/v1/extracted-actions/{id}/apply` 当前支持：

- `seller_fact_update`
- `buyer_intent_update`
- `buyer_seller_relation_update`
- `buyer_intent_target_exclusion`

Worker 自动应用策略已扩展到上述安全动作。所有应用都会写入 `action_application_log`，并刷新 `business_update.processing_status`。

## 4. 前端 API 层

前端 API 入口已整理为：

```text
frontend/src/lib/api/client.ts
frontend/src/lib/api/index.ts
frontend/src/types/api.ts
```

业务更新抽屉提交后会自动：

1. `POST /business-updates`
2. `POST /business-updates/{id}/process`

这符合“一录入即进入 AI 拆解，用户后续复核”的一期口径。

## 5. 业务更新复核页

```text
GET /api/v1/business-updates/{business_update_id}/review-page
```

前端 `/updates/:id` 优先使用该聚合接口，返回：

- `business_update`：原始录入文本、处理状态、绑定对象、文本预览。
- `overview`：动作数、待复核数、自动应用数、应用日志数、失败任务/Trace 数，`mode` 固定为 `auto_apply_then_review`。
- `action_groups`：按“标的更新 / 买家意向更新 / 关系跟进 / 异常备注”分组后的复核卡片。
- `actions`：完整动作列表，包含 `target_ref`、`target_display`、`change_preview`、`can_accept`、`can_reject`、`can_apply`。
- `application_logs`：自动应用或人工应用后的字段级变更记录，用于展示“已改了什么”和后续回退入口。
- `jobs` / `traces`：当前业务更新相关后台任务和 AI Trace 的轻量卡片。
- `bound_entities`：当前业务更新和动作涉及的标的、买家、意向、关系、推荐会话摘要。
- `quick_actions`：重新解析、聚焦待复核、查看 Debug。

该接口不替代动作操作接口；前端仍使用：

```text
PATCH /api/v1/extracted-actions/{id}
POST /api/v1/extracted-actions/{id}/apply
POST /api/v1/business-updates/{id}/process
```

## 6. 更新记录与回退

```text
GET /api/v1/update-logs?entity_type={entity_type}&entity_id={entity_id}
POST /api/v1/update-logs/{log_id}/rollback
POST /api/v1/update-logs/actions/{extracted_action_id}/rollback
```

回退接口用于“自动应用后复核”的闭环：

- 单条回退按 `action_application_log` 把某个字段恢复到 `old_value_json`。
- 按动作回退会回退同一 `extracted_action_id` 下所有仍可回退的字段，并把动作标记为 `rejected`。
- 当前支持 `seller_target`、`buyer_intent`、`buyer_party`、`buyer_seller_relation` 的白名单字段。
- 已回退的原日志会写入 `rollback_at`；系统同时插入一条 `source_type=rollback` 的新日志，便于前端展示“谁把什么改回去了”。
- 若当前字段值已经不等于原日志的 `new_value_json`，接口默认返回 `409`，避免覆盖后续人工修改；确需覆盖时请求体传 `{ "force": true }`。
- 标的和买家意向回退后会自动创建 search_doc / embedding 重建任务，保证推荐检索数据后续同步。

## 7. Buyer Intent / Seller Target Parse

```text
POST /api/v1/buyer-intents/{buyer_intent_id}/parse
GET /api/v1/buyer-intents/{buyer_intent_id}/parse-status
POST /api/v1/seller-targets/{seller_target_id}/parse
GET /api/v1/seller-targets/{seller_target_id}/parse-status
```

### Buyer intent parse

`POST /api/v1/buyer-intents/{buyer_intent_id}/parse` parses natural-language buyer requirements into standard `buyer_intent` fields.

Request example:

```json
{
  "raw_requirement_text": "Unlisted healthcare company in Zhejiang, net profit above CNY 20m, PE no more than 13, consolidation required, Yangtze River Delta acceptable.",
  "force": false
}
```

- If `raw_requirement_text` is empty, backend falls back to `buyer_intent.raw_requirement_text`.
- If `force=false` and a queued/running/retry_waiting `buyer_intent_parse` job exists, backend returns that existing job.
- Worker writes `ai_trace`, auto-applies fields, writes `action_application_log`, and triggers buyer intent search_doc / embedding rebuild.
- `GET /parse-status` returns the current `buyer_intent`, latest_job, latest_trace, recent_update_logs, and debug_ref.

### Seller target parse

`POST /api/v1/seller-targets/{seller_target_id}/parse` parses natural-language target descriptions or attachment summaries into standard `seller_target` fields.

Request example:

```json
{
  "raw_target_text": "Hangzhou medical device company, unlisted, net profit about CNY 25m, valuation about CNY 320m, PE about 12.8, control stake negotiable, consolidation possible, minority investment also negotiable.",
  "force": false
}
```

- If `raw_target_text` is empty, backend falls back to target name, business summary, transaction summary, and risk summary.
- If `force=false` and a queued/running/retry_waiting `seller_target_parse` job exists, backend returns that existing job.
- Worker writes `ai_trace`, auto-applies fields, writes `action_application_log`, and triggers seller search_doc / embedding rebuild.
- `GET /parse-status` returns the current `seller_target`, latest_job, latest_trace, recent_update_logs, and debug_ref.
- Frontend can use `latest_trace.raw_output_preview`, `parsed_output_json`, and `schema_validation_json` for Debug Mode, and `recent_update_logs` to display AI-applied field changes and rollback entry points.

## 8. Attachment / OCR Skeleton

```text
POST /api/v1/attachments
GET /api/v1/attachments
GET /api/v1/attachments/{attachment_id}
POST /api/v1/attachments/{attachment_id}/ocr
GET /api/v1/attachments/{attachment_id}/ocr-status
GET /api/v1/debug/entities/attachment/{attachment_id}
```

一期前端可以先用 JSON 创建附件元数据，不做真实文件上传：

```json
{
  "file_name": "target-teaser.pdf",
  "file_type": "pdf",
  "mime_type": "application/pdf",
  "storage_path": "mock://target-teaser.pdf",
  "metadata_json": {
    "mock_extracted_text": "Text used by the v0.1 OCR skeleton."
  },
  "links": [
    {
      "entity_type": "seller_target",
      "entity_id": "uuid",
      "link_type": "source_document"
    }
  ]
}
```

`POST /ocr` creates an `attachment_ocr_parse` job in the `ocr` queue. The worker writes:

- `parsed_document`
- `evidence_span` when mock text exists
- `ai_trace` with `trace_type=ocr`
- terminal `attachment.parse_status`

If no mock text exists, v0.1 returns a successful job with skipped OCR status, so the frontend can still verify task, trace, and debug display without waiting for real OCR integration.

## Latest field source contract for review UI

- Business update review page now returns `evidence_id` on actions and `evidence_span` on application logs when evidence exists.
- `field_value_source` is no longer limited to OCR-driven parser jobs; extracted-action apply also writes field sources.
- Frontend detail tabs can call `GET /api/v1/field-sources?entity_type=seller_target&entity_id={id}` or `buyer_intent` to render "字段来源 / 证据".
- Rollback keeps the update log history and marks matching field-source rows as `ignored`, so evidence panels should visually de-emphasize ignored sources instead of deleting them.

## Latest business update attachment contract

The business update drawer can submit text and attachment metadata in one call:

```text
POST /api/v1/business-updates
POST /api/v1/business-updates/{business_update_id}/attachments
GET /api/v1/business-updates/{business_update_id}/review-page
```

Recommended first-phase frontend payload:

```json
{
  "raw_text": "Manual business update text",
  "bound_seller_target_ids": ["uuid"],
  "attachments": [
    {
      "file_name": "teaser.pdf",
      "file_type": "pdf",
      "mime_type": "application/pdf",
      "storage_path": "mock://teaser.pdf",
      "mock_extracted_text": "Only used while real upload/OCR is not implemented."
    }
  ],
  "auto_start_ocr": true,
  "process_after_ocr": true,
  "include_attachment_text": true
}
```

Frontend expectations:

- If `auto_start_ocr=true`, show OCR/background-job progress from review page `attachments[*].latest_job` and `jobs`.
- If `process_after_ocr=true`, the OCR worker enqueues the LLM extraction job; keep polling the review page until actions/logs appear or a job fails.
- `review-page.attachments` contains latest parsed document and evidence snippet cards, so `/updates/:id` does not need to call `/attachments/{id}/ocr-status` in the normal review flow.
- Debug Mode can open `attachments[*].debug_ref` or `attachments[*].latest_job.debug_ref` when OCR/extraction is wrong.

## Latest attachment upload contract

Frontend can now upload a file before or instead of manually creating attachment JSON:

```text
POST /api/v1/attachments/upload
multipart/form-data: file, optional entity_type/entity_id/link_type, optional auto_start_ocr
```

Recommended first frontend behavior:

- For text-like files (`.txt`, `.md`, `.csv`, `.json`, `text/*`), call `/attachments/upload?auto_start_ocr=true` or send `auto_start_ocr=true` as form data; the OCR skeleton will use captured text metadata even when API and worker run as separate Railway services.
- For PDF/image/Office files, upload will create an attachment record and link it, but OCR will be `skipped` until the real OCR provider/object storage integration is added.
- If a user attaches files inside the business update drawer, the frontend can either:
  1. upload first, then pass returned `attachment.id` via `attachment_ids` to `POST /business-updates`; or
  2. continue using inline JSON attachments with `mock_extracted_text` in development/testing.
- Use `GET /business-updates/{id}/review-page` for normal progress display; use `/attachments/{id}/ocr-status` for attachment-specific debug pages.
