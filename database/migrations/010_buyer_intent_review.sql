alter table buyer_intent
  add column if not exists needs_confirmation_json jsonb not null default '[]'::jsonb,
  add column if not exists reviewed_at timestamp with time zone,
  add column if not exists reviewed_by uuid;

alter table buyer_intent
  drop constraint if exists buyer_intent_reviewed_by_fkey;

alter table buyer_intent
  add constraint buyer_intent_reviewed_by_fkey
  foreign key (reviewed_by) references app_user(id);

alter table buyer_intent_scenario
  add column if not exists needs_confirmation_json jsonb not null default '[]'::jsonb;

create index if not exists idx_buyer_intent_review_pending
  on buyer_intent (team_id, workspace_id, updated_at desc)
  where deleted_at is null and jsonb_array_length(needs_confirmation_json) > 0;
