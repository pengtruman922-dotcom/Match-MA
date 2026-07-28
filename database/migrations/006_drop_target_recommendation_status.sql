-- 0727 phase B: remove the retired seller_target recommendation status after
-- every Railway API and worker service has switched to phase A (033fa0e).
--
-- The phase-A application no longer reads or writes this column. Its Prompt
-- producers were also updated before this migration. Keep the order explicit:
-- remove dependent legacy objects first, remove the column, then give the
-- lifecycle-first replacement index the stable historical name.

drop index if exists idx_seller_target_scope;

alter table seller_target
  drop constraint if exists seller_target_recommendation_status_check;

alter table seller_target
  drop column if exists recommendation_status;

alter index if exists idx_seller_target_lifecycle_scope
  rename to idx_seller_target_scope;
