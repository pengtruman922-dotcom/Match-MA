-- 0728: entity-level follow-up records are replaced by relation_event.
--
-- Product scope is now always an existing buyer-intent x seller-target
-- relation. Historical entity follow-up rows are intentionally discarded;
-- they cannot be mapped to a relation without inventing business meaning.

delete from action_application_log
where field_path = 'follow_up_record'
   or extracted_action_id in (
     select id
     from extracted_action
     where action_type = any (
       array['seller_event'::text, 'target_follow_up'::text, 'buyer_intent_follow_up'::text]
     )
   );

drop table if exists buyer_intent_follow_up;

drop table if exists target_follow_up;

delete from extracted_action
where action_type = any (
  array['seller_event'::text, 'target_follow_up'::text, 'buyer_intent_follow_up'::text]
);

alter table extracted_action
  drop constraint if exists chk_extracted_action_type;

alter table extracted_action
  add constraint chk_extracted_action_type
  check (action_type in (
    'seller_fact_update',
    'buyer_seller_relation_update',
    'buyer_intent_target_exclusion',
    'buyer_intent_update',
    'buyer_level_blacklist_suggestion',
    'internal_note',
    'unresolved_item'
  ));
