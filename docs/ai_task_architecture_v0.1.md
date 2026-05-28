# Match-MA AI Task Architecture v0.1

日期：2026-05-28
状态：已确认架构草案
范围：background_job、Worker、ai_trace、模型配置、Prompt 配置、Debug Mode、buyer_intent_update action type。

---

## 1. 结论摘要

Match-MA 一期 AI 后端基础设施采用以下方案：

```text
1. 先落地 background_job 表，使用 PostgreSQL 作为第一版任务队列。
2. 同时落地 Worker 进程，避免 OCR / LLM / embedding 等慢任务阻塞 API。
3. 同时落地 ai_trace，支撑管理员 Debug Mode。
4. 同时落地 model_provider_config / model_node_config / prompt_template。
5. extracted_action 新增 buyer_intent_update，移除 buyer_intent_suggestion。
6. 一期做 Debug Mode，不做 Dry Run。
```

核心原则：

```text
API Service 只接收请求、创建业务记录和 background_job；
Worker Service 领取任务并执行 OCR / LLM / embedding / research / rerank；
PostgreSQL 保存任务台账、AI Trace、业务结果和应用日志；
Debug Mode 展示 AI 过程细节，不改变写入逻辑。
```

---

## 2. 服务架构

### 2.1 一期服务组成

```text
API Service
PostgreSQL
Worker Service
```

- API Service：FastAPI HTTP 服务。
- PostgreSQL：业务数据、任务队列、Trace、日志、向量数据。
- Worker Service：后台任务执行进程。

### 2.2 为什么一期先不引入 Redis / RabbitMQ

当前确认：一期使用 PostgreSQL job table 做队列，不立即引入 Redis / RabbitMQ。

原因：

- 当前系统已强依赖 PostgreSQL，减少额外基础设施。
- 一期任务吞吐量预计 PostgreSQL + Worker 足够覆盖。
- PostgreSQL 队列更容易和业务事务保持一致。
- Redis / RabbitMQ 会增加部署、调试、本地开发和运维复杂度。
- 一期更重要的是任务可观测和业务链路跑通，而不是极限吞吐。

### 2.3 后续迁移策略

`background_job` 长期作为任务台账和 source of truth 保留。

现在：

```text
API 创建 background_job
Worker 从 PostgreSQL 领取 job
Worker 更新 job 状态
```

未来如引入 Redis / RabbitMQ：

```text
API 创建 background_job
API 向 Redis/RabbitMQ 投递 job_id
Worker 从 Redis/RabbitMQ 消费 job_id
Worker 读取 background_job 详情
Worker 更新 background_job 状态
```

后续迁移时，只替换任务分发层，不重做业务表、Trace 表、Prompt 表和模型配置表。

代码层面应预留 Queue Adapter：

```text
JobQueue.enqueue(job)
JobQueue.fetch_next(queue_name)
JobQueue.ack(job)
JobQueue.fail(job)
```

---

## 3. background_job

### 3.1 业务作用

`background_job` 是后台任务队列和任务台账。

以下任务不应在 HTTP 请求中直接执行：

- 附件解析。
- OCR。
- 业务更新 LLM 拆解。
- 买家意向 LLM 解析。
- seller_target search_doc 重建。
- buyer_intent search_doc 重建。
- embedding 生成。
- 联网调研。
- 推荐候选池生成。
- 推荐 rerank。
- 推荐报告生成。

API 创建 job 后立即返回：

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

Worker 异步执行。

### 3.2 建议表结构

```sql
create table background_job (
  id uuid primary key default gen_random_uuid(),

  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  job_type text not null,
  status text not null default 'queued',

  priority int not null default 100,
  queue_name text not null default 'default',

  entity_type text,
  entity_id uuid,

  idempotency_key text,

  payload_json jsonb not null default '{}'::jsonb,
  result_json jsonb not null default '{}'::jsonb,

  error_code text,
  error_message text,
  error_detail_json jsonb not null default '{}'::jsonb,

  attempt_count int not null default 0,
  max_attempts int not null default 3,

  run_after timestamptz not null default now(),

  locked_by text,
  locked_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,

  parent_job_id uuid references background_job(id),
  correlation_id uuid,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  metadata_json jsonb not null default '{}'::jsonb,

  check (status in (
    'queued',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'retry_waiting'
  ))
);
```

建议索引：

```sql
create index idx_background_job_fetch
  on background_job(queue_name, status, run_after, priority, created_at);

create index idx_background_job_entity
  on background_job(entity_type, entity_id, created_at desc);

create index idx_background_job_scope
  on background_job(team_id, workspace_id, status, created_at desc);

create index idx_background_job_correlation
  on background_job(correlation_id);

create index idx_background_job_idempotency
  on background_job(team_id, workspace_id, job_type, idempotency_key)
  where idempotency_key is not null;
```

### 3.3 字段解释

| 字段 | 说明 |
| --- | --- |
| `job_type` | 任务类型，例如 `business_update_extract_actions` |
| `status` | 任务状态 |
| `priority` | 优先级，数字越小越优先 |
| `queue_name` | 队列名，例如 `default` / `llm` / `ocr` / `embedding` |
| `entity_type/entity_id` | 任务主要关联的业务对象 |
| `idempotency_key` | 幂等键，避免同一对象重复创建同类任务 |
| `payload_json` | 任务输入 |
| `result_json` | 任务输出摘要 |
| `error_*` | 错误信息 |
| `attempt_count/max_attempts` | 重试控制 |
| `run_after` | 延迟执行或失败后重试时间 |
| `locked_by/locked_at` | Worker 领取任务锁 |
| `parent_job_id` | 父子任务关系 |
| `correlation_id` | 串联一次完整流程 |

### 3.4 一期 job_type

先定义：

```text
business_update_extract_actions
buyer_intent_parse
seller_profile_extract
seller_search_doc_rebuild
buyer_intent_search_doc_rebuild
embedding_generate
attachment_parse
ocr_parse
research_seller_target
recommendation_candidate_generate
recommendation_rerank
recommendation_report_generate
```

一期优先实现：

```text
business_update_extract_actions
buyer_intent_parse
embedding_generate
```

---

## 4. Worker 进程

### 4.1 Worker 领取任务

PostgreSQL 队列通过 `for update skip locked` 实现多 Worker 并发安全领取：

```sql
select *
from background_job
where queue_name = :queue_name
  and status in ('queued', 'retry_waiting')
  and run_after <= now()
order by priority asc, created_at asc
limit 1
for update skip locked;
```

领取后更新：

```text
status = running
locked_by = worker id
locked_at = now()
started_at = now()
attempt_count = attempt_count + 1
```

### 4.2 并发控制

建议第一版 Worker 支持按队列限制并发：

```text
ocr: 1-2
llm: 3-5
embedding: 5-10
research: 1-3
default: 3-5
```

这样即使同时发生：

```text
3 个 OCR
10 个 embedding
5 个 LLM
```

API 也不会被阻塞，只会由 Worker 按队列并发和优先级执行。

### 4.3 失败与重试

失败时：

- 如果 `attempt_count < max_attempts`：设置 `status = retry_waiting`，`run_after = now() + backoff`。
- 如果达到最大次数：设置 `status = failed`。
- 错误写入 `error_code`、`error_message`、`error_detail_json`。
- 关联写入 `ai_trace`。

---

## 5. ai_trace

### 5.1 业务作用

`ai_trace` 支撑管理员 Debug Mode。

它不是只记录 LLM，而是记录所有 AI / 检索 / 解析相关节点：

```text
LLM
embedding
OCR
parser
retrieval
rerank
research
system
```

Debug Mode 需要展示：

- prompt。
- 模型。
- 输入。
- 原始输出。
- 解析 JSON。
- schema 校验结果。
- 检索候选池。
- token。
- 耗时。
- 费用。
- 错误。

### 5.2 建议表结构

```sql
create table ai_trace (
  id uuid primary key default gen_random_uuid(),

  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  trace_type text not null,
  node_name text not null,

  job_id uuid references background_job(id),
  correlation_id uuid,

  entity_type text,
  entity_id uuid,

  provider_config_id uuid references model_provider_config(id),
  node_config_id uuid references model_node_config(id),
  prompt_template_id uuid references prompt_template(id),

  provider_name text,
  model_name text,
  prompt_version text,

  status text not null default 'started',

  input_json jsonb not null default '{}'::jsonb,
  prompt_messages_json jsonb not null default '[]'::jsonb,
  raw_output_text text,
  parsed_output_json jsonb,
  output_schema_json jsonb,
  schema_validation_json jsonb not null default '{}'::jsonb,

  retrieval_input_json jsonb not null default '{}'::jsonb,
  retrieval_output_json jsonb not null default '{}'::jsonb,
  tool_calls_json jsonb not null default '[]'::jsonb,

  error_code text,
  error_message text,
  error_detail_json jsonb not null default '{}'::jsonb,

  latency_ms int,
  prompt_tokens int,
  completion_tokens int,
  total_tokens int,
  cost_json jsonb not null default '{}'::jsonb,

  started_at timestamptz not null default now(),
  finished_at timestamptz,

  created_by uuid references app_user(id),
  metadata_json jsonb not null default '{}'::jsonb,

  check (trace_type in (
    'llm',
    'embedding',
    'ocr',
    'parser',
    'retrieval',
    'rerank',
    'research',
    'system'
  )),

  check (status in (
    'started',
    'succeeded',
    'failed',
    'skipped'
  ))
);
```

建议索引：

```sql
create index idx_ai_trace_job on ai_trace(job_id, started_at desc);
create index idx_ai_trace_entity on ai_trace(entity_type, entity_id, started_at desc);
create index idx_ai_trace_scope on ai_trace(team_id, workspace_id, started_at desc);
create index idx_ai_trace_correlation on ai_trace(correlation_id, started_at desc);
create index idx_ai_trace_node on ai_trace(node_name, started_at desc);
```

### 5.3 字段解释

| 字段 | 说明 |
| --- | --- |
| `trace_type` | trace 类型：llm / embedding / ocr / retrieval 等 |
| `node_name` | 业务节点名，例如 `business_update_extractor` |
| `job_id` | 所属后台任务 |
| `correlation_id` | 串联一次完整流程 |
| `provider_config_id` | 使用的供应商配置 |
| `node_config_id` | 使用的模型节点配置 |
| `prompt_template_id` | 使用的 prompt 版本 |
| `prompt_messages_json` | 实际发送给模型的 messages |
| `raw_output_text` | 模型原始输出 |
| `parsed_output_json` | 解析后的结构化 JSON |
| `schema_validation_json` | JSON schema 校验结果 |
| `retrieval_*` | 检索输入输出、候选池信息 |
| `tool_calls_json` | 工具调用过程 |
| `token/cost/latency` | 计量与排错信息 |

---

## 6. model_provider_config

### 6.1 业务作用

`model_provider_config` 管供应商连接信息。

示例供应商：

- 阿里云 DashScope。
- OpenAI-compatible endpoint。
- DeepSeek。
- Azure OpenAI。
- OCR 服务。
- 自定义模型服务。

API Key 不入库。数据库只保存环境变量名：

```text
api_key_secret_ref = ALIYUN_API_KEY
```

真实 key 放 Railway 环境变量或本地 `.env`。

### 6.2 建议表结构

```sql
create table model_provider_config (
  id uuid primary key default gen_random_uuid(),

  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  provider_name text not null,
  provider_type text not null,

  base_url text,
  api_key_secret_ref text,

  auth_type text not null default 'bearer',
  extra_headers_json jsonb not null default '{}'::jsonb,
  extra_config_json jsonb not null default '{}'::jsonb,

  is_active boolean not null default true,
  is_default boolean not null default false,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  metadata_json jsonb not null default '{}'::jsonb,

  check (provider_type in (
    'openai_compatible',
    'dashscope',
    'deepseek',
    'azure_openai',
    'ocr',
    'embedding',
    'custom'
  ))
);
```

建议索引：

```sql
create index idx_model_provider_active
  on model_provider_config(team_id, workspace_id, is_active);

create unique index uq_model_provider_name
  on model_provider_config(team_id, workspace_id, provider_name);
```

### 6.3 示例

```json
{
  "provider_name": "aliyun_dashscope",
  "provider_type": "openai_compatible",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_secret_ref": "ALIYUN_API_KEY",
  "auth_type": "bearer"
}
```

---

## 7. model_node_config

### 7.1 业务作用

`model_node_config` 管每个业务节点使用哪个模型。

不是所有节点都使用同一个模型。

示例：

```text
business_update_extractor -> 结构化 LLM
buyer_intent_parser -> 结构化 LLM
recommendation_reranker -> 推理能力更强的 LLM
embedding_seller_doc -> textembedding-v4
embedding_buyer_intent -> textembedding-v4
ocr_attachment_parser -> OCR 服务或视觉模型
```

### 7.2 建议表结构

```sql
create table model_node_config (
  id uuid primary key default gen_random_uuid(),

  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  node_name text not null,
  node_type text not null,

  provider_config_id uuid not null references model_provider_config(id),

  model_name text not null,

  temperature numeric(4,3),
  top_p numeric(4,3),
  max_tokens int,
  timeout_seconds int not null default 60,

  response_format text,
  output_mode text not null default 'text',

  embedding_dimension int,

  is_active boolean not null default true,
  is_default boolean not null default false,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  metadata_json jsonb not null default '{}'::jsonb,

  check (node_type in (
    'llm',
    'embedding',
    'ocr',
    'rerank',
    'research',
    'parser'
  )),

  check (output_mode in (
    'text',
    'json',
    'embedding',
    'file',
    'mixed'
  ))
);
```

建议索引：

```sql
create index idx_model_node_active
  on model_node_config(team_id, workspace_id, node_name, is_active);

create unique index uq_model_node_default
  on model_node_config(team_id, workspace_id, node_name)
  where is_default = true;
```

### 7.3 一期 node_name

```text
business_update_extractor
buyer_intent_parser
seller_profile_extractor
recommendation_query_parser
recommendation_reranker
recommendation_answer_writer
recommendation_report_writer
embedding_seller_doc
embedding_buyer_intent
ocr_attachment_parser
research_seller_target
```

---

## 8. prompt_template

### 8.1 业务作用

`prompt_template` 管 Prompt 版本。

Prompt 必须版本化，因为后续会持续优化：

- 业务更新抽取 prompt。
- 买家意向解析 prompt。
- 标的画像提取 prompt。
- 推荐 query parser prompt。
- 推荐 rerank prompt。
- 推荐报告 prompt。

版本化后才能进行评测和回溯。

### 8.2 建议表结构

```sql
create table prompt_template (
  id uuid primary key default gen_random_uuid(),

  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  node_name text not null,
  version text not null,

  name text,
  description text,

  system_prompt text,
  user_prompt_template text,

  output_schema_json jsonb not null default '{}'::jsonb,
  few_shot_examples_json jsonb not null default '[]'::jsonb,

  template_engine text not null default 'jinja',
  variables_json jsonb not null default '[]'::jsonb,

  is_active boolean not null default true,
  is_default boolean not null default false,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  metadata_json jsonb not null default '{}'::jsonb,

  unique (team_id, workspace_id, node_name, version)
);
```

建议索引：

```sql
create index idx_prompt_template_active
  on prompt_template(team_id, workspace_id, node_name, is_active);

create unique index uq_prompt_template_default
  on prompt_template(team_id, workspace_id, node_name)
  where is_default = true;
```

### 8.3 示例

```json
{
  "node_name": "business_update_extractor",
  "version": "v0.1.0",
  "system_prompt": "你是并购撮合平台的业务更新解析助手...",
  "user_prompt_template": "上下文：{{ context_json }}\n原始输入：{{ raw_text }}",
  "output_schema_json": {
    "type": "object",
    "required": ["actions"],
    "properties": {
      "actions": {
        "type": "array"
      }
    }
  },
  "variables_json": ["context_json", "raw_text"]
}
```

---

## 9. extracted_action 调整

### 9.1 action_type 调整

当前旧值：

```text
buyer_intent_suggestion
```

不再符合最新产品原则。

最新原则：买家意向更新应自动应用，然后支持查看、编辑、回退。

因此 action_type 改为：

```text
buyer_intent_update
```

建议 action_type 清单：

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

### 9.2 buyer_intent_update 示例

用户输入：

```text
浙江国资现在不看上市公司了，只看浙江省内非上市医药标的，利润最好3000万以上。
```

AI 输出：

```json
{
  "action_type": "buyer_intent_update",
  "target_entity_type": "buyer_intent",
  "target_entity_id": "uuid",
  "proposed_changes_json": {
    "preferred_listed_status": "unlisted",
    "region_scope_summary": "浙江省内",
    "min_net_profit_yuan": 30000000,
    "preference_summary": "优先浙江省内非上市医药健康标的，利润最好3000万元以上"
  },
  "confidence": 0.91
}
```

系统自动应用后：

- 更新 `buyer_intent` 当前快照。
- 写入 `action_application_log`。
- 工作台展示“买家意向自动更新待复核”。
- 用户可查看、编辑、回退。

---

## 10. review_status 新语义

当前字段名仍使用：

```text
review_status
```

短期不改字段名，避免迁移面过大。

但语义从“确认后应用”调整为“自动应用后的复核”。

一期沿用现有枚举：

```text
pending_review
auto_accepted
accepted
rejected
ignored
```

建议临时语义：

| 值 | 新语义 |
| --- | --- |
| `pending_review` | 待复核，可能尚未应用或无法自动应用 |
| `auto_accepted` | 系统已自动应用，待用户复核 |
| `accepted` | 用户已复核并接受 |
| `rejected` | 用户认为错误，待回退或已回退 |
| `ignored` | 用户忽略，无需处理 |

后续可考虑扩展为更直观的状态：

```text
auto_applied
reviewed
failed
```

---

## 11. Debug Mode

### 11.1 定义

Debug Mode 是管理员可见的 AI 调试模式。

它的作用是展示 AI 细节，而不是阻止写入。

```text
Debug Mode != Dry Run
```

一期不做 Dry Run。

### 11.2 Debug Mode 展示内容

基于 `background_job` 和 `ai_trace` 展示：

- job_id。
- job_type。
- job status。
- node_name。
- provider。
- model。
- prompt version。
- input_json。
- prompt_messages_json。
- raw_output_text。
- parsed_output_json。
- schema_validation_json。
- retrieval_output_json。
- tool_calls_json。
- token。
- latency。
- cost。
- error_message。

---

## 12. 典型流程

### 12.1 统一业务更新

```text
用户提交 business_update
  -> API 创建 business_update
  -> API 创建 background_job: business_update_extract_actions
  -> Worker 领取 job
  -> Worker 调用 business_update_extractor
  -> 写 ai_trace
  -> 生成 extracted_action
  -> 可明确定位的动作自动 apply
  -> 写 action_application_log
  -> 标记 auto_accepted / pending_review
  -> 工作台展示待复核
```

### 12.2 买家意向解析

```text
用户新建 buyer_intent
  -> API 保存原始需求文本
  -> API 创建 background_job: buyer_intent_parse
  -> Worker 调用 buyer_intent_parser
  -> 写 ai_trace
  -> 更新 buyer_intent 结构化字段
  -> 写 action_application_log 或 field_value_source
  -> 标记待复核
```

### 12.3 embedding 生成

```text
seller_target / buyer_intent 更新
  -> 创建 search_doc_rebuild job
  -> 生成 search_doc 文本
  -> 创建 embedding_generate job
  -> 调用 embedding node
  -> 写 ai_trace
  -> 写入 pgvector 字段
```

---

## 13. 后续开发顺序建议

1. 新增数据库迁移：`background_job`、`ai_trace`、`model_provider_config`、`model_node_config`、`prompt_template`。
2. 修改 `extracted_action.action_type` check：`buyer_intent_suggestion` -> `buyer_intent_update`。
3. 新增基础 API：模型配置、Prompt 配置、job 查询、trace 查询。
4. 新增 Worker 进程骨架。
5. 实现 PostgreSQL job fetcher。
6. 实现第一个 AI 节点：`buyer_intent_parser` 或 `business_update_extractor`。
7. 接入 Debug Mode 数据读取。
