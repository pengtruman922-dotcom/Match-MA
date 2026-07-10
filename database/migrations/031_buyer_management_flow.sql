-- Match-MA buyer management flow refinements
-- Purpose: add manual buyer notes and allow buyer intents to be closed.

begin;

alter table buyer_party
  add column if not exists notes text;

alter table buyer_intent
  drop constraint if exists buyer_intent_status_check;

alter table buyer_intent
  add constraint buyer_intent_status_check
  check (status in ('active', 'paused', 'closed'));

update prompt_template
set user_prompt_template = replace(
      user_prompt_template,
      'pause_reason.',
      'pause_reason. For buyer_intent.status use exactly one of: active (ongoing recommendation), paused (temporarily paused), closed (ended/completed/terminated need).'
    ),
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'buyer_intent_closed_status_source', 'migration_031_buyer_management_flow'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'business_update_extractor'
  and is_default = true
  and user_prompt_template not like '%buyer_intent.status use exactly one of%';

update prompt_template
set user_prompt_template = replace(
      user_prompt_template,
      'Never place target/seller attributes in buyer_party. Use Chinese for region and main business. Omit buyer_party entirely when there is no clear buyer self-description.',
      'Never place target/seller attributes in buyer_party. Use Chinese for region and main business. Do not output or overwrite manual buyer notes. Omit buyer_party entirely when there is no clear buyer self-description.'
    ),
    metadata_json = coalesce(metadata_json, '{}'::jsonb) || jsonb_build_object(
      'buyer_party_notes_boundary_source', 'migration_031_buyer_management_flow'
    ),
    updated_at = now()
where team_id = '00000000-0000-0000-0000-000000000001'
  and workspace_id = '00000000-0000-0000-0000-000000000101'
  and node_name = 'buyer_intent_parser'
  and is_default = true
  and user_prompt_template not like '%manual buyer notes%';

commit;
