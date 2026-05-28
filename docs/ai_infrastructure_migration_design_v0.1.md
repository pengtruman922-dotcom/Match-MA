# Match-MA AI Infrastructure Migration Design v0.1

鏃ユ湡锛?026-05-28
鐘舵€侊細杩佺Щ璁捐鑽夋锛屾湭鎵ц
鍏宠仈鏂囨。锛?

- `docs/ai_task_architecture_v0.1.md`
- `docs/postgres_schema_v0.1.md`
- `docs/data_model_v0.1.md`

---

## 1. 杩佺Щ鐩爣

鏈杩佺Щ鐩爣鏄妸宸茬‘璁ょ殑 AI 鍚庣鍩虹璁炬柦钀藉埌 PostgreSQL schema 涓紝涓哄悗缁?Worker銆丩LM銆乪mbedding銆丱CR銆丏ebug Mode 鍋氬噯澶囥€?

鏈杩佺Щ鍙仛鏁版嵁搴撶粨鏋勫拰灏戦噺鍙€?seed锛屼笉鐩存帴瀹炵幇 LLM / OCR / embedding 璋冪敤閫昏緫銆?

鎷熸柊澧烇細

```text
model_provider_config
model_node_config
prompt_template
background_job
ai_trace
```

鎷熻皟鏁达細

```text
extracted_action.action_type
```

灏嗘棫 action type锛?

```text
buyer_intent_suggestion
```

璋冩暣涓猴細

```text
buyer_intent_update
```

---

## 2. Alembic 杩佺Щ鏂囦欢瑙勫垝

鐜版湁杩佺Щ锛?

```text
20260527_0001_initial_schema.py
20260527_0002_seed_defaults.py
20260527_0003_seed_reference_config.py
```

寤鸿鏂板杩佺Щ锛?

```text
alembic/versions/20260528_0004_ai_task_infrastructure.py
database/migrations/004_ai_task_infrastructure.sql
```

娌跨敤褰撳墠宸ョ▼椋庢牸锛欰lembic Python 鏂囦欢鍔犺浇 `database/migrations/*.sql` 骞舵墽琛屻€?

绀轰緥锛?

```python
"""ai task infrastructure

Revision ID: 20260528_0004
Revises: 20260527_0003
Create Date: 2026-05-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260528_0004"
down_revision: str | None = "20260527_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    for statement in split_sql_statements(load_migration_sql("004_ai_task_infrastructure.sql")):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for AI task infrastructure.")
```

---

## 3. 琛ㄥ垱寤洪『搴?

蹇呴』鎸夊紩鐢ㄥ叧绯诲垱寤猴細

```text
1. model_provider_config
2. model_node_config
3. prompt_template
4. background_job
5. ai_trace
6. alter extracted_action.action_type check
7. optional seed model provider / node / prompt
```

鍘熷洜锛?

- `model_node_config.provider_config_id` 寮曠敤 `model_provider_config`銆?
- `ai_trace` 寮曠敤 `background_job`銆乣model_provider_config`銆乣model_node_config`銆乣prompt_template`銆?

---

## 4. 鏂板琛細model_provider_config

### 4.1 鐢ㄩ€?

淇濆瓨渚涘簲鍟嗚繛鎺ラ厤缃€?

鐪熷疄 API Key 涓嶅叆搴擄紝鍙瓨鐜鍙橀噺鍚嶏細

```text
api_key_secret_ref
```

渚嬪锛?

```text
ALIYUN_API_KEY
OPENAI_API_KEY
DEEPSEEK_API_KEY
```

### 4.2 DDL 鑽夋

```sql
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
```

### 4.3 璁捐璇存槑

- `provider_type` 涓嶅己缁戝畾鍏蜂綋鍘傚晢锛屾敮鎸?OpenAI-compatible endpoint銆?
- `base_url` 鍙负绌猴紝鐢ㄤ簬榛樿 SDK 鎴栭潪 HTTP 鏈嶅姟銆?
- `extra_config_json` 鍙繚瀛?region銆丄PI version銆丱CR 鍙傛暟绛夐潪鏍囧噯閰嶇疆銆?

---

## 5. 鏂板琛細model_node_config

### 5.1 鐢ㄩ€?

淇濆瓨涓氬姟鑺傜偣浣跨敤鐨勬ā鍨嬮厤缃€?

鍏稿瀷鑺傜偣锛?

```text
business_update_extractor
buyer_intent_parser
embedding_seller_doc
embedding_buyer_intent
recommendation_reranker
```

### 5.2 DDL 鑽夋

```sql
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
```

### 5.3 璁捐璇存槑

- `node_name` 鏄唬鐮佹煡閰嶇疆鐨勭ǔ瀹?key銆?
- `node_type` 琛ㄧず璋冪敤绫诲瀷銆?
- `response_format` 鍙繚瀛?`json_object` / `json_schema` / OpenAI-compatible response format 瀛楃涓层€?
- `embedding_dimension` 璁板綍 embedding 缁村害锛涘綋鍓?search_doc 琛ㄥ凡浣跨敤 `vector(1024)`锛屽悗缁ā鍨嬮厤缃簲涓庡畠涓€鑷存垨鍙﹁杩佺Щ search_doc 鍚戦噺缁村害銆?

---

## 6. 鏂板琛細prompt_template

### 6.1 鐢ㄩ€?

淇濆瓨 Prompt 鐗堟湰銆?

Prompt 蹇呴』鐗堟湰鍖栵紝鏀拺锛?

- Debug 鍥炴斁銆?
- Prompt A/B 瀵规瘮銆?
- 璇勬祴闆嗗鐜般€?
- 鎺ㄨ崘缁撴灉杩借矗銆?

### 6.2 DDL 鑽夋

```sql
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
```

### 6.3 璁捐璇存槑

- `system_prompt` 鍜?`user_prompt_template` 鍒嗗紑瀛橈紝鏂逛究 OpenAI-compatible messages 鐢熸垚銆?
- `output_schema_json` 淇濆瓨鏈熸湜 JSON schema銆?
- `variables_json` 璁板綍妯℃澘鍙橀噺锛屼緥濡?`context_json`銆乣raw_text`銆?

---

## 7. 鏂板琛細background_job

### 7.1 鐢ㄩ€?

淇濆瓨鍚庡彴浠诲姟闃熷垪鍜屼换鍔″彴璐︺€?

涓€鏈熶娇鐢?PostgreSQL 琛ㄥ仛闃熷垪锛涘悗缁鏋滃紩鍏?Redis/RabbitMQ锛屼粛淇濈暀璇ヨ〃浣滀负浠诲姟 source of truth銆?

### 7.2 DDL 鑽夋

```sql
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
```

### 7.3 鍏充簬骞傜瓑绱㈠紩

璁捐涓厛寤烘櫘閫氱储寮曪紝涓嶅缓鍞竴绱㈠紩銆?

鍘熷洜锛?

- 鏃╂湡寮€鍙戦樁娈靛彲鑳介渶瑕侀噸澶嶆祴璇曞悓涓€ job銆?
- 涓嶅悓鐘舵€佷笅鏄惁鍏佽閲嶅浠诲姟锛岄渶瑕佺瓑 Worker 閫昏緫鏄庣‘銆?

鍚庣画鍙互鍗囩骇涓洪儴鍒嗗敮涓€绱㈠紩锛屼緥濡傚彧闄愬埗鏈畬鎴愪换鍔★細

```sql
create unique index uq_background_job_active_idempotency
  on background_job(team_id, workspace_id, job_type, idempotency_key)
  where idempotency_key is not null
    and status in ('queued', 'running', 'retry_waiting');
```

---

## 8. 鏂板琛細ai_trace

### 8.1 鐢ㄩ€?

淇濆瓨 AI / 妫€绱?/ 瑙ｆ瀽 / OCR / embedding / rerank 鎵ц璇︽儏锛屾敮鎾?Debug Mode銆?

### 8.2 DDL 鑽夋

```sql
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
```

### 8.3 璁捐璇存槑

`ai_trace` 鍚屾椂淇濈暀寮曠敤 ID 鍜屽啑浣欏悕绉帮細

- `provider_config_id` / `provider_name`
- `node_config_id` / `model_name`
- `prompt_template_id` / `prompt_version`

鍘熷洜锛氬嵆浣垮悗缁厤缃鍋滅敤鎴栦慨鏀癸紝鍘嗗彶 trace 浠嶈兘灞曠ず褰撴椂浣跨敤鐨勬ā鍨嬪拰 prompt 鐗堟湰銆?

---

## 9. 璋冩暣 extracted_action.action_type check

### 9.1 褰撳墠鐘舵€?

褰撳墠鍒濆 schema 涓細

```sql
action_type text not null check (action_type in (
  'seller_fact_update',
  'seller_event',
  'buyer_seller_relation_update',
  'buyer_intent_target_exclusion',
  'buyer_intent_suggestion',
  'buyer_level_blacklist_suggestion',
  'internal_note',
  'unresolved_item'
))
```

鏈€鏂板彛寰勶細

```text
buyer_intent_suggestion -> buyer_intent_update
```

### 9.2 杩佺Щ姝ラ

鍥犱负鍘?check constraint 娌℃湁鏄惧紡鍛藉悕锛孭ostgreSQL 浼氳嚜鍔ㄧ敓鎴愮被浼硷細

```text
extracted_action_action_type_check
```

杩佺Щ鏃跺缓璁樉寮忓鐞嗭細

```sql
update extracted_action
set action_type = 'buyer_intent_update'
where action_type = 'buyer_intent_suggestion';

alter table extracted_action
  drop constraint if exists extracted_action_action_type_check;

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
```

### 9.3 鍏煎鎬ц鏄?

褰撳墠绾夸笂娴嬭瘯鏁版嵁澶ф鐜囨病鏈?`buyer_intent_suggestion`锛屼絾 migration 浠嶅簲鍖呭惈 update 璇彞锛屼繚璇佸吋瀹广€?

鍚庣 Pydantic 褰撳墠涓嶉檺鍒?action_type 鏋氫妇锛屼絾鏁版嵁搴撲細闄愬埗锛屽洜姝ゅ繀椤昏縼绉?check constraint銆?

---

## 10. 鍙€?seed锛氶粯璁ゆā鍨嬮厤缃?

### 10.1 鏄惁鏈杩佺Щ seed

寤鸿鏈杩佺Щ鍙互 seed 鏈€灏忛粯璁ゆā鍨嬮厤缃紝浣嗕笉鍐欑湡瀹?key銆?

鍘熷洜锛?

- 鍚庣画 API / Worker 鍙互鐩存帴鎸?`node_name` 鎵惧埌榛樿閰嶇疆銆?
- 鐪熷疄 key 浠嶆斁鐜鍙橀噺锛屼笉杩涘叆鏁版嵁搴撱€?

### 10.2 榛樿 provider seed 鑽夋

```sql
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
```

### 10.3 榛樿 node seed 鑽夋

寤鸿鍏?seed 浠ヤ笅鑺傜偣锛?

```text
business_update_extractor
buyer_intent_parser
embedding_seller_doc
embedding_buyer_intent
recommendation_reranker
recommendation_report_writer
```

妯″瀷鍚嶅厛鐢ㄥ崰浣嶄絾鍙厤缃€硷紝渚嬪锛?

```text
qwen3.6-flash
text-embedding-v4
```

娉ㄦ剰锛氬綋鍓?search_doc 琛ㄦ槸 `vector(1024)`锛宔mbedding 鑺傜偣鐨?`embedding_dimension` 寤鸿鍏堣涓?`1024`锛岄櫎闈炲悗缁‘璁ら樋閲屼簯 text-embedding-v4 浣跨敤鍏朵粬缁村害骞跺悓姝ヨ縼绉?search_doc 鍚戦噺鍒椼€?

### 10.4 榛樿 prompt seed

寤鸿鏈鍙?seed prompt 鍗犱綅鐗堟湰锛?

```text
node_name = business_update_extractor, version = v0.1.0
node_name = buyer_intent_parser, version = v0.1.0
```

Prompt 鍙互鐢ㄥ畨鍏ㄥ崰浣嶆枃鏈紝鍚庣画鍦ㄢ€滆缃?妯″瀷涓庢彁绀鸿瘝鈥濅腑瀹屽杽銆?

涓嶅缓璁湪 migration 閲屽啓澶嶆潅闀?prompt锛岄伩鍏嶅悗缁绻佹敼 migration銆傛寮?prompt 鐗堟湰鍙互鐢卞悗缁鐞?API 鎴?seed 鑴氭湰缁存姢銆?

---

## 11. 鐜鍙橀噺瑙勫垝

鏈杩佺Щ涓嶄細鍒涘缓鐜鍙橀噺锛屼絾鍚庣画 Worker 璋冩ā鍨嬪墠闇€瑕佸湪 Railway 閰嶇疆锛?

```text
ALIYUN_API_KEY
```

鍚庣画鍙€夛細

```text
OPENAI_API_KEY
DEEPSEEK_API_KEY
```

娉ㄦ剰锛?

- 鏁版嵁搴撳彧瀛?`api_key_secret_ref`銆?
- 鍚庣杩愯鏃堕€氳繃璇ュ瓧娈佃鍙栧搴旂幆澧冨彉閲忋€?
- 涓嶈鎶婄湡瀹?key 鍐欏叆 migration銆乻eed 鎴栧墠绔?`.env`銆?

---

## 12. 楠岃瘉鏂规

杩佺Щ鎵ц鍚庯紝寤鸿澧炲姞鎴栦汉宸ラ獙璇佷互涓嬫鏌ャ€?

### 12.1 琛ㄥ瓨鍦ㄦ鏌?

```sql
select to_regclass('public.background_job');
select to_regclass('public.ai_trace');
select to_regclass('public.model_provider_config');
select to_regclass('public.model_node_config');
select to_regclass('public.prompt_template');
```

### 12.2 action_type check 楠岃瘉

搴旇鎴愬姛锛?

```sql
insert into extracted_action (
  team_id, workspace_id, business_update_id, action_type
)
values (..., 'buyer_intent_update');
```

搴旇澶辫触锛?

```sql
insert into extracted_action (
  team_id, workspace_id, business_update_id, action_type
)
values (..., 'buyer_intent_suggestion');
```

瀹為檯娴嬭瘯鍙€氳繃 API 鍒涘缓 `business_update` 鍚庡啀鍒涘缓 `extracted_action`銆?

### 12.3 seed 妫€鏌?

```sql
select provider_name, provider_type, api_key_secret_ref
from model_provider_config;

select node_name, node_type, model_name, is_default
from model_node_config;

select node_name, version, is_default
from prompt_template;
```

### 12.4 Railway 楠岃瘉

鎺ㄩ€佸悗 Railway 浼氭墽琛岋細

```text
alembic upgrade head
```

楠岃瘉姝ラ锛?

1. 鏌ョ湅 Railway deploy logs锛岀‘璁?migration 鎴愬姛銆?
2. 璋冪敤鐜版湁鍋ュ悍妫€鏌ワ細
   ```text
   GET /api/v1/health
   GET /api/v1/health/db
   ```
3. 鍚庣画鏂板 meta 鎺ュ彛鏃讹紝鍐嶅姞鍏?AI infra 妫€鏌ャ€?

---

## 13. 椋庨櫓涓庡鐞?

### 13.1 椋庨櫓锛歝heck constraint 鍚嶇О涓嶄竴鑷?

褰撳墠鍒濆 schema 娌℃湁鏄惧紡鍛藉悕 action_type check銆侾ostgreSQL 榛樿閫氬父鏄細

```text
extracted_action_action_type_check
```

浣嗕负绋冲Ε锛屽彲浠ュ湪 migration 涓厛鏌ョ郴缁熻〃鎴栦娇鐢?`drop constraint if exists extracted_action_action_type_check`銆?

濡傛灉绾夸笂鍚嶇О涓嶅悓锛岄渶瑕佷汉宸ユ煡锛?

```sql
select conname
from pg_constraint
where conrelid = 'extracted_action'::regclass;
```

寤鸿鍚庣画鎵€鏈?check constraint 閮芥樉寮忓懡鍚嶃€?

### 13.2 椋庨櫓锛歴eed 榛樿 provider 閫犳垚璇В

榛樿 provider 鍙繚瀛樼幆澧冨彉閲忓悕锛屼笉淇濆瓨鐪熷疄 key銆?

濡傛灉 Railway 鏈厤缃?`ALIYUN_API_KEY`锛屾ā鍨嬭皟鐢ㄤ粛浼氬け璐ワ紝浣嗕笉褰卞搷 migration銆?

### 13.3 椋庨櫓锛歟mbedding 缁村害

褰撳墠 search_doc 琛ㄤ负锛?

```text
embedding vector(1024)
```

濡傛灉鏈€缁堥€夌敤鐨?embedding 妯″瀷缁村害涓嶆槸 1024锛岄渶瑕佸崟鐙縼绉?search_doc 琛紝鎴栨柊寤哄缁村害 embedding 琛ㄣ€?

鏈杩佺Щ涓嶈皟鏁?search_doc embedding 缁村害銆?

### 13.4 椋庨櫓锛歛i_trace 淇濆瓨鏁忔劅淇℃伅

`ai_trace` 浼氫繚瀛?prompt 鍜屽師濮嬭緭鍑猴紝鍙兘鍖呭惈鏁忔劅鍟嗕笟淇℃伅銆?

涓€鏈熷厛鎸夊唴閮ㄧ郴缁熷鐞嗭紝鍚庣画闇€瑕侀厤鍚堟潈闄愬拰鑴辨晱绛栫暐銆?

---

## 14. 鏈杩佺Щ涓嶅仛鐨勪簨

鏈涓嶅仛锛?

- 涓嶅疄鐜?Worker 浠ｇ爜銆?
- 涓嶅疄鐜?LLM 璋冪敤銆?
- 涓嶅疄鐜?OCR銆?
- 涓嶅疄鐜?embedding 鐢熸垚銆?
- 涓嶅疄鐜?Debug Mode API銆?
- 涓嶈縼绉?search_doc embedding 缁村害銆?
- 涓嶅紩鍏?Redis / RabbitMQ銆?
- 涓嶅仛 Dry Run銆?

---

## 15. 寤鸿纭椤?

杩涘叆瀹為檯杩佺Щ鍓嶅缓璁‘璁わ細

1. 鏄惁鍚屾剰鏈 migration seed 鏈€灏忛粯璁?provider / node / prompt銆?
2. 榛樿 provider 鏄惁閲囩敤 `aliyun_dashscope` + `ALIYUN_API_KEY`銆?
3. 榛樿 LLM 妯″瀷鍚嶆槸鍚﹀厛鐢?`qwen3.6-flash`銆?
4. 榛樿 embedding 妯″瀷鍚嶆槸鍚﹀厛鐢?`text-embedding-v4`锛岀淮搴︽殏鎸夌幇鏈?`1024`銆?
5. 鏄惁纭鏈鍙皟鏁?`extracted_action.action_type` check锛屼笉鏀?`review_status` 鏋氫妇銆?
