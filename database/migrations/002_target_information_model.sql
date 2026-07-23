-- R4a: simplify seller target location/industry facts and profile supplements.
-- This migration intentionally does not modify 001_baseline.sql: 001 remains
-- the deployed floor, while fresh installations reach this final schema via
-- `alembic upgrade head`.

alter table seller_target
  add column location_province text,
  add column location_city text,
  add column location_district text;

-- Preserve the previously preferred practical location. Historical HQ is the
-- closest semantic match; registration location is only the fallback. The old
-- model contains no district-level data, so location_district remains null.
update seller_target
set location_province = coalesce(nullif(headquarter_province, ''), nullif(registered_province, '')),
    location_city = coalesce(nullif(headquarter_city, ''), nullif(registered_city, ''))
where location_province is null
  and location_city is null;

do $migration$
declare
  migrated_count bigint;
begin
  select count(*) into migrated_count
  from seller_target
  where location_province is not null or location_city is not null;
  raise notice 'R4a seller_target location backfill rows: %', migrated_count;
end
$migration$;

-- Preserve any raw industry values that can be resolved by the existing
-- taxonomy before removing the raw columns. A second-level alias is resolved
-- to its canonical L2 term; an unmapped phrase remains only in the immutable
-- business-update/evidence audit trail rather than becoming a fake screening
-- value.
update seller_target st
set industry_l1 = coalesce(
      st.industry_l1,
      (
        select tax.l1_name
        from industry_taxonomy tax
        where tax.team_id = st.team_id and tax.workspace_id = st.workspace_id
          and tax.active = true
          and lower(tax.term) in (lower(coalesce(st.industry_secondary, '')), lower(coalesce(st.industry_primary, '')))
        order by case when lower(tax.term) = lower(coalesce(st.industry_secondary, '')) then 0 else 1 end
        limit 1
      )
    ),
    industry_l2 = coalesce(
      st.industry_l2,
      (
        select coalesce(canonical.term, tax.term)
        from industry_taxonomy tax
        left join industry_taxonomy canonical on canonical.id = tax.canonical_term_id
        where tax.team_id = st.team_id and tax.workspace_id = st.workspace_id
          and tax.active = true
          and (
            tax.level = 'l2'
            or (tax.level = 'alias' and canonical.level = 'l2' and canonical.active = true)
          )
          and lower(tax.term) in (lower(coalesce(st.industry_secondary, '')), lower(coalesce(st.industry_primary, '')))
        order by case when lower(tax.term) = lower(coalesce(st.industry_secondary, '')) then 0 else 1 end
        limit 1
      )
    )
where st.industry_l1 is null or st.industry_l2 is null;

do $migration$
declare
  l1_count bigint;
  l2_count bigint;
begin
  select count(*) into l1_count from seller_target where industry_l1 is not null;
  select count(*) into l2_count from seller_target where industry_l2 is not null;
  raise notice 'R4a normalized industry rows: l1 %, l2 %', l1_count, l2_count;
end
$migration$;

drop index if exists idx_seller_target_industry;
drop index if exists idx_seller_target_region;
alter table seller_target drop constraint if exists seller_target_region_granularity_check;
alter table seller_target
  drop column industry_primary,
  drop column industry_secondary,
  drop column registered_province,
  drop column registered_city,
  drop column headquarter_province,
  drop column headquarter_city,
  drop column raw_region_text,
  drop column region_granularity;

create index idx_seller_target_industry_l1_l2
  on seller_target (team_id, industry_l1, industry_l2)
  where deleted_at is null;
create index idx_seller_target_location
  on seller_target (team_id, location_province, location_city, location_district)
  where deleted_at is null;

alter table entity_profile_section drop constraint if exists entity_profile_section_section_code_check;
alter table entity_profile_section
  add constraint entity_profile_section_section_code_check
  check (section_code in (
    'identity', 'business_product', 'chain_position', 'tech_team',
    'ops_quality', 'deal_terms', 'sell_intent_risk'
  ));
alter table entity_profile_section drop column confidence;
alter table research_proposal drop column confidence;
