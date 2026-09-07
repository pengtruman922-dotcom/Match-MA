-- 外部 Agent 只读访问（2026-09-07）：API key 与 Agent 调用日志。
--
-- 背景：wegent 上的 Agent 通过 MCP 端点查询买家库与标的库。凭证以前是管理员 JWT
-- 明文放在 skill 目录里（7 天过期、能写全库）。现在换成服务端签发的 API key：
-- 明文只在签发那一刻返回一次，库里只存 sha256，可单独停用，权限范围由 scopes 限定。
--
-- agent_call_log 是「回写」留的口子：现在只记谁在什么时候调了哪个工具、参数是什么、
-- 命中几条。将来「推荐记录 / 创建撮合关系」的写工具就从这张表的旁边长出来。
--
-- 硬规则：注释里不能出现分号（自制 splitter 按分号切语句）。

create table if not exists api_key (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  name text not null,
  key_prefix text not null,
  key_hash text not null,
  scopes jsonb not null default '[]'::jsonb,
  created_by uuid,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid,
  constraint api_key_key_hash_key unique (key_hash),
  constraint chk_api_key_scopes_array check (jsonb_typeof(scopes) = 'array'),
  constraint chk_api_key_prefix_nonempty check (length(key_prefix) > 0)
);

create index if not exists idx_api_key_workspace_live
  on api_key (team_id, workspace_id, created_at desc)
  where revoked_at is null;

create table if not exists agent_call_log (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null,
  workspace_id uuid not null,
  api_key_id uuid,
  actor_label text not null,
  tool_name text not null,
  arguments_json jsonb not null default '{}'::jsonb,
  matched integer,
  returned integer,
  duration_ms integer,
  error_text text,
  created_at timestamptz not null default now()
);

create index if not exists idx_agent_call_log_created_at
  on agent_call_log (team_id, workspace_id, created_at desc);

create index if not exists idx_agent_call_log_api_key
  on agent_call_log (api_key_id, created_at desc);
