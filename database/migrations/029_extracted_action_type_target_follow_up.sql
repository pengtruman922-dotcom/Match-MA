-- Match-MA extracted_action type check with target_follow_up
-- Purpose: allow the extractor to store dated target follow-up notes; the
-- previous check constraint rejected the new action type and failed the whole
-- business_update_extract_actions job.

begin;

alter table extracted_action
  drop constraint if exists chk_extracted_action_type;

alter table extracted_action
  add constraint chk_extracted_action_type check (action_type in (
    'seller_fact_update',
    'seller_event',
    'target_follow_up',
    'buyer_seller_relation_update',
    'buyer_intent_target_exclusion',
    'buyer_intent_update',
    'buyer_level_blacklist_suggestion',
    'internal_note',
    'unresolved_item'
  ));

commit;
