-- 买家需求页按模块重构：每个模块配一块「其他」，四条跨模块散文列下线。
--
-- priority_summary / preference_summary / negative_summary 的内容跨模块，
-- 自动分不了，所以按列整体归到一个模块的「其他」并打来源标签，顾问事后可自行搬运。
-- unknown_summary 的内容与 needs_confirmation_json 完全重复，后者有自己的界面，故丢弃。

alter table entity_profile_section drop constraint if exists entity_profile_section_section_code_check;
alter table entity_profile_section
  add constraint entity_profile_section_section_code_check
  check (section_code in (
    'identity', 'business_product', 'chain_position', 'tech_team',
    'ops_quality', 'deal_terms', 'sell_intent_risk',
    'intent_scope', 'intent_financial', 'intent_deal'
  ));

-- 行业与地区·其他 收「优先条件」与「排除项」
insert into entity_profile_section (
  team_id, workspace_id, entity_type, entity_id, section_code,
  info_status, content_text, source_type, review_status, created_by, updated_by
)
select
  bi.team_id, bi.workspace_id, 'buyer_intent', bi.id, 'intent_scope',
  'filled',
  concat_ws(
    E'\n',
    nullif('【优先条件】' || coalesce(nullif(btrim(bi.priority_summary), ''), ''), '【优先条件】'),
    nullif('【排除项】' || coalesce(nullif(btrim(bi.negative_summary), ''), ''), '【排除项】')
  ),
  'migrated_from_buyer_intent_columns', 'accepted', bi.updated_by, bi.updated_by
from buyer_intent bi
where bi.deleted_at is null
  and (nullif(btrim(bi.priority_summary), '') is not null
       or nullif(btrim(bi.negative_summary), '') is not null)
  and not exists (
    select 1 from entity_profile_section eps
    where eps.entity_type = 'buyer_intent'
      and eps.entity_id = bi.id
      and eps.section_code = 'intent_scope'
      and eps.deleted_at is null
  );

-- 经营与财务·其他 收「其他偏好」
insert into entity_profile_section (
  team_id, workspace_id, entity_type, entity_id, section_code,
  info_status, content_text, source_type, review_status, created_by, updated_by
)
select
  bi.team_id, bi.workspace_id, 'buyer_intent', bi.id, 'intent_financial',
  'filled',
  '【其他偏好】' || btrim(bi.preference_summary),
  'migrated_from_buyer_intent_columns', 'accepted', bi.updated_by, bi.updated_by
from buyer_intent bi
where bi.deleted_at is null
  and nullif(btrim(bi.preference_summary), '') is not null
  and not exists (
    select 1 from entity_profile_section eps
    where eps.entity_type = 'buyer_intent'
      and eps.entity_id = bi.id
      and eps.section_code = 'intent_financial'
      and eps.deleted_at is null
  );

alter table buyer_intent
  drop column if exists priority_summary,
  drop column if exists preference_summary,
  drop column if exists negative_summary,
  drop column if exists unknown_summary;

-- 存量 condition_effects_json 里可能留着 deep_eval。规则取值收成必须/优先之后
-- 它不再是合法值，留着会让「这个字段不参与打分」这件事继续静默生效。
update buyer_intent
set condition_effects_json = coalesce(
  (
    select jsonb_object_agg(key, value)
    from jsonb_each_text(condition_effects_json)
    where value in ('required', 'preferred')
  ),
  '{}'::jsonb
)
where exists (
  select 1 from jsonb_each_text(condition_effects_json)
  where value not in ('required', 'preferred')
);

update buyer_intent_scenario
set condition_effects_json = coalesce(
  (
    select jsonb_object_agg(key, value)
    from jsonb_each_text(condition_effects_json)
    where value in ('required', 'preferred')
  ),
  '{}'::jsonb
)
where exists (
  select 1 from jsonb_each_text(condition_effects_json)
  where value not in ('required', 'preferred')
);
