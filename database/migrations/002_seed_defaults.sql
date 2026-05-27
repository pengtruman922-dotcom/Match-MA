-- Match-MA phase 1 seed data v0.1
-- Purpose: provide a default team/workspace/admin user so phase 1 data can be inserted.
-- Broad reference dictionaries are seeded in 003_seed_reference_config.sql.

begin;

-- Stable deterministic UUIDs for local/dev baseline data.
-- Replace names/emails in production if needed, but keep one default workspace for phase 1 inserts.
insert into team (id, name, status)
values ('00000000-0000-0000-0000-000000000001', 'Match-MA 默认团队', 'active')
on conflict (id) do update set
  name = excluded.name,
  status = excluded.status,
  updated_at = now();

insert into workspace (id, team_id, name, workspace_type, status)
values ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000001', '默认数据空间', 'data_space', 'active')
on conflict (id) do update set
  team_id = excluded.team_id,
  name = excluded.name,
  workspace_type = excluded.workspace_type,
  status = excluded.status,
  updated_at = now();

insert into app_user (id, team_id, default_workspace_id, name, email, role, status)
values ('00000000-0000-0000-0000-000000000201', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000101', '系统管理员', 'admin@match-ma.local', 'admin', 'active')
on conflict (id) do update set
  team_id = excluded.team_id,
  default_workspace_id = excluded.default_workspace_id,
  name = excluded.name,
  email = excluded.email,
  role = excluded.role,
  status = excluded.status,
  updated_at = now();

-- Minimal global fallback tags. Detailed reference dictionaries live in later seed files.
insert into tag_dictionary (id, team_id, workspace_id, domain, canonical_key, display_name, parent_key, aliases_json, description, is_active, sort_order)
values
  ('00000000-0000-0000-0000-000000001001', null, null, 'industry', 'other', '其他行业', null, '["其他", "暂未归类"]'::jsonb, 'Fallback industry for pending classification.', true, 9999),
  ('00000000-0000-0000-0000-000000001002', null, null, 'sector', 'other', '其他赛道', null, '["其他", "暂未归类"]'::jsonb, 'Fallback sector for pending normalization.', true, 9999),
  ('00000000-0000-0000-0000-000000001003', null, null, 'product', 'other', '其他产品/服务', null, '["其他", "暂未归类"]'::jsonb, 'Fallback product/service for pending normalization.', true, 9999),
  ('00000000-0000-0000-0000-000000001004', null, null, 'certification', 'other', '其他资质', null, '["其他", "暂未归类"]'::jsonb, 'Fallback certification for pending normalization.', true, 9999)
on conflict (id) do update set
  team_id = excluded.team_id,
  workspace_id = excluded.workspace_id,
  domain = excluded.domain,
  canonical_key = excluded.canonical_key,
  display_name = excluded.display_name,
  parent_key = excluded.parent_key,
  aliases_json = excluded.aliases_json,
  description = excluded.description,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order,
  updated_at = now();

commit;
