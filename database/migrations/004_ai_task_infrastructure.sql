-- Match-MA AI task infrastructure v0.1
-- Purpose: add background jobs, AI trace, model configuration, prompt templates,
-- and replace buyer_intent_suggestion with buyer_intent_update.

begin;

create table if not exists model_provider_config (
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

  constraint chk_model_provider_type check (provider_type in (
    'openai_compatible',
    'dashscope',
    'deepseek',
    'azure_openai',
    'ocr',
    'embedding',
    'custom'
  )),

  constraint chk_model_provider_auth_type check (auth_type in (
    'none',
    'bearer',
    'api_key_header',
    'custom'
  ))
);

create index if not exists idx_model_provider_active
  on model_provider_config(team_id, workspace_id, is_active);

create unique index if not exists uq_model_provider_name
  on model_provider_config(team_id, workspace_id, provider_name);

create table if not exists model_node_config (
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

  constraint chk_model_node_type check (node_type in (
    'llm',
    'embedding',
    'ocr',
    'rerank',
    'research',
    'parser'
  )),

  constraint chk_model_node_output_mode check (output_mode in (
    'text',
    'json',
    'embedding',
    'file',
    'mixed'
  ))
);

create index if not exists idx_model_node_active
  on model_node_config(team_id, workspace_id, node_name, is_active);

create unique index if not exists uq_model_node_default
  on model_node_config(team_id, workspace_id, node_name)
  where is_default = true;

create table if not exists prompt_template (
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

  constraint chk_prompt_template_engine check (template_engine in (
    'jinja',
    'plain',
    'custom'
  )),

  constraint uq_prompt_template_version unique (team_id, workspace_id, node_name, version)
);

create index if not exists idx_prompt_template_active
  on prompt_template(team_id, workspace_id, node_name, is_active);

create unique index if not exists uq_prompt_template_default
  on prompt_template(team_id, workspace_id, node_name)
  where is_default = true;

create table if not exists background_job (
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

  constraint chk_background_job_status check (status in (
    'queued',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'retry_waiting'
  ))
);

create index if not exists idx_background_job_fetch
  on background_job(queue_name, status, run_after, priority, created_at);

create index if not exists idx_background_job_entity
  on background_job(entity_type, entity_id, created_at desc);

create index if not exists idx_background_job_scope
  on background_job(team_id, workspace_id, status, created_at desc);

create index if not exists idx_background_job_correlation
  on background_job(correlation_id);

create index if not exists idx_background_job_idempotency
  on background_job(team_id, workspace_id, job_type, idempotency_key)
  where idempotency_key is not null;

create table if not exists ai_trace (
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

  constraint chk_ai_trace_type check (trace_type in (
    'llm',
    'embedding',
    'ocr',
    'parser',
    'retrieval',
    'rerank',
    'research',
    'system'
  )),

  constraint chk_ai_trace_status check (status in (
    'started',
    'succeeded',
    'failed',
    'skipped'
  ))
);

create index if not exists idx_ai_trace_job
  on ai_trace(job_id, started_at desc);

create index if not exists idx_ai_trace_entity
  on ai_trace(entity_type, entity_id, started_at desc);

create index if not exists idx_ai_trace_scope
  on ai_trace(team_id, workspace_id, started_at desc);

create index if not exists idx_ai_trace_correlation
  on ai_trace(correlation_id, started_at desc);

create index if not exists idx_ai_trace_node
  on ai_trace(node_name, started_at desc);

update extracted_action
set action_type = 'buyer_intent_update'
where action_type = 'buyer_intent_suggestion';

alter table extracted_action
  drop constraint if exists extracted_action_action_type_check;

alter table extracted_action
  drop constraint if exists chk_extracted_action_type;

alter table extracted_action
  add constraint chk_extracted_action_type check (action_type in (
    'seller_fact_update',
    'seller_event',
    'buyer_seller_relation_update',
    'buyer_intent_target_exclusion',
    'buyer_intent_update',
    'buyer_level_blacklist_suggestion',
    'internal_note',
    'unresolved_item'
  ));

insert into model_provider_config (
  id, team_id, workspace_id, provider_name, provider_type,
  base_url, api_key_secret_ref, auth_type, is_active, is_default, created_by
)
values (
  '00000000-0000-0000-0000-000000004001',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'aliyun_dashscope',
  'openai_compatible',
  'https://dashscope.aliyuncs.com/compatible-mode/v1',
  'ALIYUN_API_KEY',
  'bearer',
  true,
  true,
  '00000000-0000-0000-0000-000000000201'
)
on conflict (team_id, workspace_id, provider_name) do update set
  provider_type = excluded.provider_type,
  base_url = excluded.base_url,
  api_key_secret_ref = excluded.api_key_secret_ref,
  auth_type = excluded.auth_type,
  is_active = excluded.is_active,
  is_default = excluded.is_default,
  updated_at = now();

insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
values
  (
    '00000000-0000-0000-0000-000000004101',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'business_update_extractor',
    'llm',
    '00000000-0000-0000-0000-000000004001',
    'qwen3.6-flash',
    0.100,
    0.900,
    4096,
    90,
    'json_object',
    'json',
    null,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Extract structured actions from business updates."}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000004102',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'buyer_intent_parser',
    'llm',
    '00000000-0000-0000-0000-000000004001',
    'qwen3.6-flash',
    0.100,
    0.900,
    4096,
    90,
    'json_object',
    'json',
    null,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Parse buyer requirements into structured intent fields."}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000004103',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'embedding_seller_doc',
    'embedding',
    '00000000-0000-0000-0000-000000004001',
    'text-embedding-v4',
    null,
    null,
    null,
    60,
    null,
    'embedding',
    1024,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Generate seller target search document embeddings."}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000004104',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'embedding_buyer_intent',
    'embedding',
    '00000000-0000-0000-0000-000000004001',
    'text-embedding-v4',
    null,
    null,
    null,
    60,
    null,
    'embedding',
    1024,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Generate buyer intent search document embeddings."}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000004105',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'recommendation_reranker',
    'rerank',
    '00000000-0000-0000-0000-000000004001',
    'qwen3.6-flash',
    0.200,
    0.900,
    4096,
    120,
    'json_object',
    'json',
    null,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Rerank recommendation candidates and produce structured rationale."}'::jsonb
  ),
  (
    '00000000-0000-0000-0000-000000004106',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'recommendation_report_writer',
    'llm',
    '00000000-0000-0000-0000-000000004001',
    'qwen3.6-flash',
    0.300,
    0.900,
    8192,
    180,
    null,
    'text',
    null,
    true,
    true,
    '00000000-0000-0000-0000-000000000201',
    '{"purpose":"Draft recommendation reports from selected candidates."}'::jsonb
  )
on conflict (team_id, workspace_id, node_name) where is_default = true do update set
  node_type = excluded.node_type,
  provider_config_id = excluded.provider_config_id,
  model_name = excluded.model_name,
  temperature = excluded.temperature,
  top_p = excluded.top_p,
  max_tokens = excluded.max_tokens,
  timeout_seconds = excluded.timeout_seconds,
  response_format = excluded.response_format,
  output_mode = excluded.output_mode,
  embedding_dimension = excluded.embedding_dimension,
  is_active = excluded.is_active,
  metadata_json = excluded.metadata_json,
  updated_at = now();

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by
)
values
  (
    '00000000-0000-0000-0000-000000004201',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'business_update_extractor',
    'v0.1.0',
    'Business update extractor baseline',
    'Placeholder prompt for extracting structured actions from business updates.',
    '你是 Match-MA 并购撮合平台的业务更新解析助手。请根据上下文和原始输入，抽取可执行的结构化业务动作。',
    '上下文：{{ context_json }}\n原始输入：{{ raw_text }}\n请输出 JSON，顶层字段为 actions。',
    '{"type":"object","required":["actions"],"properties":{"actions":{"type":"array"}}}'::jsonb,
    '[]'::jsonb,
    'jinja',
    '["context_json","raw_text"]'::jsonb,
    true,
    true,
    '00000000-0000-0000-0000-000000000201'
  ),
  (
    '00000000-0000-0000-0000-000000004202',
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000101',
    'buyer_intent_parser',
    'v0.1.0',
    'Buyer intent parser baseline',
    'Placeholder prompt for parsing buyer acquisition requirements.',
    '你是 Match-MA 并购撮合平台的买家意向解析助手。请把自然语言收购需求解析为结构化字段，并区分 hard、preference、unknown。',
    '买家原始需求：{{ raw_requirement_text }}\n已有买家画像：{{ buyer_profile_json }}\n请输出 JSON。',
    '{"type":"object"}'::jsonb,
    '[]'::jsonb,
    'jinja',
    '["raw_requirement_text","buyer_profile_json"]'::jsonb,
    true,
    true,
    '00000000-0000-0000-0000-000000000201'
  )
on conflict (team_id, workspace_id, node_name, version) do update set
  name = excluded.name,
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  few_shot_examples_json = excluded.few_shot_examples_json,
  template_engine = excluded.template_engine,
  variables_json = excluded.variables_json,
  is_active = excluded.is_active,
  is_default = excluded.is_default,
  updated_at = now();

commit;
