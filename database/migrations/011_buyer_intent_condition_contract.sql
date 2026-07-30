alter table buyer_intent
  add column if not exists acceptable_listed_status_json jsonb not null default '[]'::jsonb,
  add column if not exists condition_effects_json jsonb not null default '{}'::jsonb;

alter table buyer_intent_scenario
  add column if not exists condition_effects_json jsonb not null default '{}'::jsonb;

update buyer_intent
set preferred_listed_status = 'pre_ipo'
where preferred_listed_status = 'preparing_listing';

update buyer_intent
set acceptable_listed_status_json = case
  when preferred_listed_status in ('listed', 'unlisted', 'pre_ipo')
    then jsonb_build_array(preferred_listed_status)
  else '[]'::jsonb
end
where jsonb_array_length(acceptable_listed_status_json) = 0;

alter table buyer_intent
  drop constraint if exists buyer_intent_preferred_listed_status_check;

alter table buyer_intent
  add constraint buyer_intent_preferred_listed_status_check
  check (
    preferred_listed_status is null
    or preferred_listed_status = any (array['listed'::text, 'unlisted'::text, 'pre_ipo'::text, 'any'::text, 'unknown'::text])
  ),
  add constraint chk_buyer_intent_acceptable_listed_status_json
  check (jsonb_typeof(acceptable_listed_status_json) = 'array'),
  add constraint chk_buyer_intent_condition_effects_json
  check (jsonb_typeof(condition_effects_json) = 'object');

alter table buyer_intent_scenario
  add constraint chk_buyer_intent_scenario_condition_effects_json
  check (jsonb_typeof(condition_effects_json) = 'object');
