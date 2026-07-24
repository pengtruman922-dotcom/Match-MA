-- R5: multi-industry facts, consolidated supplementary sections, and a
-- compatibility-preserving backfill for records created before this model.

alter table seller_target
  add column industry_pairs_json jsonb not null default '[]'::jsonb;

alter table seller_target
  add constraint seller_target_industry_pairs_json_check
  check (jsonb_typeof(industry_pairs_json) = 'array');

-- Existing L1/L2 facts become one canonical industry pair. The old columns
-- remain as a compatibility projection during the reader migration; new
-- writes derive them from industry_pairs_json rather than treating them as an
-- independent source of truth.
update seller_target
set industry_pairs_json = case
  when nullif(industry_l1, '') is not null or nullif(industry_l2, '') is not null then
    jsonb_build_array(
      jsonb_strip_nulls(
        jsonb_build_object(
          'l1', nullif(industry_l1, ''),
          'l2', nullif(industry_l2, '')
        )
      )
    )
  else '[]'::jsonb
end
where industry_pairs_json = '[]'::jsonb;

create index idx_seller_target_industry_pairs
  on seller_target using gin (industry_pairs_json jsonb_path_ops)
  where deleted_at is null;

-- Merge the retired chain-position supplement into business/product. The
-- newest row remains current; the old business row is superseded so loading a
-- section still produces exactly one current value per code.
with active_chain as (
  select distinct on (entity_id)
    id, entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'chain_position'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
), active_business as (
  select distinct on (entity_id)
    id, entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'business_product'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
)
update entity_profile_section old_business
set deleted_at = now(), updated_at = now()
from active_business business
join active_chain chain on chain.entity_id = business.entity_id
where old_business.id = business.id;

with active_chain as (
  select distinct on (entity_id)
    id, entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'chain_position'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
), prior_business as (
  select distinct on (entity_id)
    entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'business_product'
    and deleted_at is not null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
)
update entity_profile_section chain
set section_code = 'business_product',
    content_text = case
      when coalesce(trim(prior_business.content_text), '') = '' then chain.content_text
      when trim(prior_business.content_text) = trim(chain.content_text) then chain.content_text
      else prior_business.content_text || E'\n\n产业链位置：' || chain.content_text
    end,
    updated_at = now()
from active_chain selected
left join prior_business on prior_business.entity_id = selected.entity_id
where chain.id = selected.id;

-- The same rule applies to the former seller-intent/risk supplement, now a
-- part of transaction terms. Historical revisions are retained, only their
-- current section code is consolidated.
with active_sell as (
  select distinct on (entity_id)
    id, entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'sell_intent_risk'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
), active_terms as (
  select distinct on (entity_id)
    id, entity_id
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'deal_terms'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
)
update entity_profile_section old_terms
set deleted_at = now(), updated_at = now()
from active_terms terms
join active_sell sell on sell.entity_id = terms.entity_id
where old_terms.id = terms.id;

with active_sell as (
  select distinct on (entity_id)
    id, entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'sell_intent_risk'
    and deleted_at is null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
), prior_terms as (
  select distinct on (entity_id)
    entity_id, content_text
  from entity_profile_section
  where entity_type = 'seller_target'
    and section_code = 'deal_terms'
    and deleted_at is not null
    and review_status in ('accepted', 'auto_accepted')
  order by entity_id, updated_at desc
)
update entity_profile_section sell
set section_code = 'deal_terms',
    content_text = case
      when coalesce(trim(prior_terms.content_text), '') = '' then sell.content_text
      when trim(prior_terms.content_text) = trim(sell.content_text) then sell.content_text
      else prior_terms.content_text || E'\n\n出售诉求与风险：' || sell.content_text
    end,
    updated_at = now()
from active_sell selected
left join prior_terms on prior_terms.entity_id = selected.entity_id
where sell.id = selected.id;

-- The check applies to historical soft-deleted revisions too. Keep their text
-- and audit metadata, but map their retired category code to its successor.
update entity_profile_section
set section_code = 'business_product'
where section_code = 'chain_position';

update entity_profile_section
set section_code = 'deal_terms'
where section_code = 'sell_intent_risk';

alter table entity_profile_section drop constraint if exists entity_profile_section_section_code_check;
alter table entity_profile_section
  add constraint entity_profile_section_section_code_check
  check (section_code in (
    'identity', 'business_product', 'tech_team', 'ops_quality', 'deal_terms'
  ));
