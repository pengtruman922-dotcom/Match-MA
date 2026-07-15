-- Buyer intent parsing v2 fields and intent-scoped follow-up records.

begin;

alter table buyer_intent
  add column if not exists min_valuation_yuan numeric(20,2),
  add column if not exists max_ps numeric(10,4),
  add column if not exists min_net_margin numeric(10,4),
  add column if not exists min_gross_margin numeric(10,4),
  add column if not exists industry_focus_tags_json jsonb not null default '[]'::jsonb;

create table if not exists buyer_intent_follow_up (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  buyer_intent_id uuid not null references buyer_intent(id),
  occurred_at timestamptz not null default now(),
  contact_name text,
  content text not null,
  next_step text,
  next_follow_up_at timestamptz,
  business_update_id uuid references business_update(id),
  extracted_action_id uuid references extracted_action(id),
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create index if not exists idx_buyer_intent_follow_up_intent
  on buyer_intent_follow_up(buyer_intent_id, occurred_at desc, created_at desc)
  where deleted_at is null;

create unique index if not exists uq_buyer_intent_follow_up_action
  on buyer_intent_follow_up(extracted_action_id)
  where extracted_action_id is not null and deleted_at is null;

alter table extracted_action
  drop constraint if exists chk_extracted_action_type;

alter table extracted_action
  add constraint chk_extracted_action_type check (action_type in (
    'seller_fact_update',
    'seller_event',
    'target_follow_up',
    'buyer_intent_follow_up',
    'buyer_seller_relation_update',
    'buyer_intent_target_exclusion',
    'buyer_intent_update',
    'buyer_level_blacklist_suggestion',
    'internal_note',
    'unresolved_item'
  ));

commit;
