-- Match-MA multi-scenario buyer requirements (accuracy plan batch 4)
-- Purpose: real requirements are disjunctions — "已上市且市值≤50亿" OR "未上市且
-- PE≤13且可控股". A single flat field set collapses them into one incoherent
-- filter. Scenarios are AND within a group, OR between groups, and always
-- combine with the intent's global conditions.
--
-- Scenario conditions live in fields_json rather than mirrored columns: the
-- field whitelist and type coercion already exist in code
-- (recommendation_conditions.OVERRIDE_FIELD_KINDS), and duplicating 40 columns
-- would reintroduce the "one field, eleven edit sites" problem this plan is
-- trying to remove.

begin;

create table if not exists buyer_intent_scenario (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  buyer_intent_id uuid not null references buyer_intent(id),
  label text not null,
  sort_order integer not null default 0,
  active boolean not null default true,
  fields_json jsonb not null default '{}'::jsonb,
  source text not null default 'parser' check (source in ('parser', 'manual', 'chat')),
  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz
);

-- Existing intents keep zero scenario rows on purpose: the recommendation flow
-- treats "no scenarios" as a single implicit scenario made of the intent's own
-- fields, so screening stays byte-identical until a scenario is actually added.
create index if not exists idx_buyer_intent_scenario_intent
  on buyer_intent_scenario (team_id, buyer_intent_id, sort_order)
  where deleted_at is null and active = true;

commit;
