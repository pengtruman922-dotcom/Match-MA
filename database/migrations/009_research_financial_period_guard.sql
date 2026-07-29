-- 0728: add a machine-comparable period for the current financial snapshot.
--
-- financial_period_label remains the consultant-facing wording.  This date is
-- internal metadata used by research writeback to prevent an older report from
-- overwriting a newer snapshot and to keep one research batch on one period.

alter table seller_target
  add column if not exists financial_period_end_date date;

comment on column seller_target.financial_period_end_date is
  'Internal end date of the current financial snapshot; financial_period_label remains the display value.';
