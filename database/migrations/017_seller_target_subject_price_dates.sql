-- Match-MA seller target subject and price dates v0.1
-- Purpose: support target subject display and lightweight price/valuation time labels.

begin;

alter table seller_target
  add column if not exists target_subject_name text,
  add column if not exists valuation_date text,
  add column if not exists asking_price_date text;

update seller_target
set target_subject_name = target_name
where target_subject_name is null
  and target_type = 'company'
  and deleted_at is null;

commit;
