-- Match-MA search providers and research proposals (accuracy plan batch 6)
-- Purpose: let a search API be configured exactly like a model provider —
-- same encrypted-key handling, same masked display, same Settings surface —
-- and give the research agent a place to park proposed facts for review.
--
-- Search providers reuse model_provider_config rather than getting their own
-- table: secret_mode / api_key_encrypted / key_display already solve key
-- storage and masking, and duplicating that for a second kind of credential is
-- how secrets end up handled two slightly different ways.

begin;

alter table model_provider_config
  drop constraint if exists chk_model_provider_type;

alter table model_provider_config
  add constraint chk_model_provider_type check (provider_type in (
    'openai_compatible',
    'dashscope',
    'deepseek',
    'azure_openai',
    'ocr',
    'embedding',
    'search',
    'custom'
  ));

-- Researched facts never land directly on the entity. Each proposal keeps the
-- evidence that produced it, the anchor features that proved the page is about
-- this company, and a conflict verdict, so a reviewer can act on it later.
create table if not exists research_proposal (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  entity_type text not null check (entity_type in ('seller_target', 'buyer_intent')),
  entity_id uuid not null,
  job_id uuid,
  proposal_kind text not null check (proposal_kind in ('profile_section', 'structured_fact')),
  section_code text,
  field_path text,
  proposed_value_json jsonb not null default '{}'::jsonb,
  current_value_json jsonb not null default '{}'::jsonb,
  -- 冲突四分类：一致只加证据；补充可自动写入；时序两期并存；同期冲突必须人工。
  conflict_kind text not null default 'supplement'
    check (conflict_kind in ('consistent', 'supplement', 'temporal_update', 'same_period_conflict')),
  period_label text,
  as_of_date date,
  source_type text,
  source_url text,
  source_title text,
  source_excerpt text,
  anchor_matches_json jsonb not null default '[]'::jsonb,
  confidence numeric(5,4),
  review_status text not null default 'pending_review'
    check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),
  reviewed_by uuid references app_user(id),
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists idx_research_proposal_entity
  on research_proposal (team_id, entity_type, entity_id, review_status)
  where deleted_at is null;

create index if not exists idx_research_proposal_pending
  on research_proposal (team_id, created_at desc)
  where deleted_at is null and review_status = 'pending_review';

-- Public information on small unlisted targets is often simply absent. Recording
-- that a sweep found nothing, and when to try again, stops the agent from
-- burning the same budget on the same empty target every run.
alter table seller_target
  add column if not exists research_last_outcome text,
  add column if not exists research_retry_after timestamptz;

do $do$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'chk_seller_target_research_outcome'
  ) then
    alter table seller_target add constraint chk_seller_target_research_outcome check (
      research_last_outcome is null
      or research_last_outcome in ('found', 'no_public_information', 'failed')
    );
  end if;
end
$do$;

commit;
