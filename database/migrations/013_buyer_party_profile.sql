-- 买家主体只保留顾问实际维护、且应在同一主体的所有需求间共享的资料。
-- 历史主体列中的 legal_name 仍可参与查重：先并入 aliases_json，再删除旧列。
alter table buyer_party
  add column if not exists industries_json jsonb not null default '[]'::jsonb,
  add column if not exists industry_l2_json jsonb not null default '[]'::jsonb,
  add column if not exists contact_name text,
  add column if not exists contact_info_json jsonb not null default '{}'::jsonb;

update buyer_party
set aliases_json = (
  select coalesce(jsonb_agg(alias_name order by lower(alias_name)), '[]'::jsonb)
  from (
    select distinct btrim(candidate.value) as alias_name
    from jsonb_array_elements_text(
      coalesce(buyer_party.aliases_json, '[]'::jsonb)
      || jsonb_build_array(buyer_party.legal_name)
    ) as candidate(value)
    where nullif(btrim(candidate.value), '') is not null
      and lower(btrim(candidate.value)) <> lower(btrim(buyer_party.buyer_name))
  ) as aliases
)
where nullif(btrim(legal_name), '') is not null;

alter table buyer_party
  drop constraint if exists buyer_party_buyer_type_check,
  drop constraint if exists buyer_party_listed_status_check,
  drop column if exists legal_name,
  drop column if exists buyer_type,
  drop column if exists group_name,
  drop column if exists listed_status,
  drop column if exists main_business,
  drop column if exists capital_strength_summary,
  drop column if exists profile_summary;

alter table buyer_party
  add constraint chk_buyer_party_industries_json
  check (jsonb_typeof(industries_json) = 'array'),
  add constraint chk_buyer_party_industry_l2_json
  check (jsonb_typeof(industry_l2_json) = 'array'),
  add constraint chk_buyer_party_contact_info_json
  check (jsonb_typeof(contact_info_json) = 'object');

create index if not exists idx_buyer_party_industries
  on buyer_party using gin (industries_json)
  where deleted_at is null;
