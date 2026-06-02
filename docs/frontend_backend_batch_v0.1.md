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
```

`/debug/entities/{entity_type}/{entity_id}` 是统一入口，当前支持：

- `business_update`
- `recommendation_session`
- `background_job`
- `model_node_config`

业务更新 Debug 返回同一业务更新下的：

- `business_update`
- `jobs`
- `traces`
- `actions`
- `application_logs`

推荐会话 Debug 返回会话、候选生成/重排/报告相关的 jobs、traces、messages、selected_items、reports、relations、relation_events。

后台任务 Debug 返回单个 job、同 job traces、同 correlation/entity 的 related_jobs。

模型节点 Debug 返回单个 node、最近节点测试 jobs、节点相关 traces；用于设置页调试每个 LLM / embedding / rerank 节点。

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
