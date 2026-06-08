-- Match-MA buyer intent requirement fields v0.1
-- Purpose: split listing requirements and add key structured buyer intent filters.

begin;

alter table buyer_intent
  add column if not exists min_market_cap_yuan numeric(20,2),
  add column if not exists max_market_cap_yuan numeric(20,2),
  add column if not exists listing_board_requirement_summary text,
  add column if not exists financing_stage_requirement_summary text,
  add column if not exists premium_tolerance_summary text,
  add column if not exists max_premium_rate numeric(10,4),
  add column if not exists max_debt_ratio numeric(10,4),
  add column if not exists debt_ratio_requirement_summary text,
  add column if not exists major_risk_tolerance_summary text,
  add column if not exists buyer_industry_advantage_summary text,
  add column if not exists transaction_types_json jsonb not null default '[]'::jsonb;

alter table buyer_intent
  drop constraint if exists buyer_intent_preferred_listed_status_check;

alter table buyer_intent
  add constraint buyer_intent_preferred_listed_status_check
  check (preferred_listed_status in ('listed', 'preparing_listing', 'pre_ipo', 'unlisted', 'any', 'unknown'));

alter table buyer_intent
  drop constraint if exists buyer_intent_market_cap_range_check;

alter table buyer_intent
  add constraint buyer_intent_market_cap_range_check
  check (
    min_market_cap_yuan is null
    or max_market_cap_yuan is null
    or min_market_cap_yuan <= max_market_cap_yuan
  );

commit;
