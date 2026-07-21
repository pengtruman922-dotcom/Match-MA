-- Match-MA matching profile sections (accuracy plan batch 5)
-- Purpose: hold the qualitative judgements screening cannot express — chain
-- position, market standing, technology and team, deal flexibility, sell-side
-- intent. seller_target already carries 81 columns; adding six more would both
-- repeat the "one field, eleven edit sites" problem and fail to hold the
-- source, evidence and as-of date every researched claim needs.
--
-- Rows are not unique per section on purpose: competing values from different
-- periods or sources coexist, and the context builder picks the most recent
-- accepted one. That is where the research agent's conflict handling lands.

begin;

create table if not exists entity_profile_section (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  entity_type text not null check (entity_type in ('seller_target', 'buyer_intent')),
  entity_id uuid not null,
  section_code text not null check (section_code in (
    'business_product',
    'chain_position',
    'tech_team',
    'ops_quality',
    'deal_terms',
    'sell_intent_risk'
  )),
  -- 显式区分"没查到"与"不适用"：深评必须分得清缺信息和不相关，
  -- 空字符串两者都表达不了。
  info_status text not null default 'filled'
    check (info_status in ('filled', 'not_found', 'not_applicable')),
  content_text text,
  source_type text,
  source_url text,
  source_title text,
  source_excerpt text,
  as_of_date date,
  confidence numeric(5,4),
  review_status text not null default 'accepted'
    check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),
  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz
);

create index if not exists idx_entity_profile_section_entity
  on entity_profile_section (team_id, entity_type, entity_id, section_code)
  where deleted_at is null;

create index if not exists idx_entity_profile_section_review
  on entity_profile_section (team_id, review_status)
  where deleted_at is null and review_status = 'pending_review';

commit;
