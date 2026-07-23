-- R4e: manual relation events are editable/soft-deletable, while system
-- timeline entries remain immutable audit history.

alter table relation_event
  add column updated_at timestamp with time zone not null default now(),
  add column updated_by uuid,
  add column deleted_at timestamp with time zone,
  add column deleted_by uuid;

alter table relation_event
  add constraint relation_event_updated_by_fkey foreign key (updated_by) references app_user(id),
  add constraint relation_event_deleted_by_fkey foreign key (deleted_by) references app_user(id);

alter table relation_event drop constraint if exists relation_event_event_type_check;
alter table relation_event
  add constraint relation_event_event_type_check
  check (event_type in (
    'recommended', 'buyer_interested', 'buyer_not_interested',
    'meeting', 'call', 'message', 'email', 'material_sent', 'quote_update',
    'nda_signed', 'management_meeting', 'due_diligence_started',
    'due_diligence_progress', 'agreement_discussion', 'exclusivity',
    'deal_closed', 'paused', 'internal_note', 'other'
  ));

create index idx_relation_event_active_timeline
  on relation_event (relation_id, event_time desc, created_at desc)
  where deleted_at is null;
