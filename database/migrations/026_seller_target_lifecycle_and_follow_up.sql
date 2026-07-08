-- Match-MA seller target lifecycle status and follow-up log v0.1
-- Purpose: track manual deal lifecycle (active/sold/off_market) separately from
-- system-driven recommendation/information statuses, and store dated follow-up
-- notes per target with optional buyer references.

begin;

alter table seller_target
  add column if not exists lifecycle_status text not null default 'active'
    check (lifecycle_status in ('active', 'sold', 'off_market'));

create table if not exists target_follow_up (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  seller_target_id uuid not null references seller_target(id),
  occurred_on date not null default current_date,
  content text not null,
  related_buyer_party_ids_json jsonb not null default '[]'::jsonb,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create index if not exists idx_target_follow_up_target
  on target_follow_up(seller_target_id, occurred_on desc, created_at desc)
  where deleted_at is null;

commit;
