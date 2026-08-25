-- 买家主体从「一个名字 + 一个负责人」变成能承载推荐维度的信息载体。
-- 生产 39 条主体里 industries_json / industry_l2_json / contact_* 全部 0%，
-- 详情接口连一个业务字段都不投影 —— 系统里没有任何地方能回答
-- 「这家买家自己是做什么的」，而那正是「为标的找买家」的第一判断依据。
--
-- 真正参与判断的只有 6 个字段：业务标签、业务说明、企业性质、市值/估值、
-- 营收、现金流。其余新增列是让「自动刷新」和「调研」成立的支撑列
-- （时间戳、股票代码、上市地），不是新的匹配维度。
--
-- 三个财务数值列都不进任何 where。它们成为列的理由不是「能被筛选」，
-- 而是「能被刷新」—— 一个带 as_of、会被定期覆盖的数必须有确定的落点，
-- 你没法去 update 一段文本里的某个数字。
--
-- 013 删掉 listed_status 是对的：那时它是没人维护、不进 where 的死列。
-- 现在重建的理由不同 —— 它决定「市值/估值该显示哪一个」以及
-- 「财务数据能不能自动刷新」。这是重建，不是恢复。
--
-- 四个财务列名与标的侧一字不差是刻意的：MONEY_YUAN_FIELDS 的万元/亿元归一、
-- 以及「核心财务事实必须带期间」的守卫（迁移 009）都能直接复用。
--
-- 注意：本文件的注释里不能出现分号。自制 splitter 按分号切语句，
-- 注释里的分号会切坏语句、部署直接挂（有过事故，见 AGENTS.md）。

alter table buyer_party
  add column if not exists location_province text,
  add column if not exists location_city text,
  add column if not exists location_district text,
  add column if not exists ownership_type text not null default 'unknown'::text,
  add column if not exists listed_status text not null default 'unknown'::text,
  add column if not exists stock_code text,
  add column if not exists listing_exchange text,
  add column if not exists our_contact_name text,
  add column if not exists business_tags_json jsonb not null default '[]'::jsonb,
  add column if not exists business_summary text,
  add column if not exists market_cap_yuan numeric(20,2),
  add column if not exists market_cap_as_of date,
  add column if not exists valuation_yuan numeric(20,2),
  add column if not exists valuation_date text,
  add column if not exists current_revenue_yuan numeric(20,2),
  add column if not exists current_operating_cash_flow_yuan numeric(20,2),
  add column if not exists financial_period_label text,
  add column if not exists supplementary_summary text;

-- 存量搬运，必须在删旧列之前。生产实测 39 条里 14 条有省份，丢了就得人工补回。
update buyer_party
set location_province = nullif(btrim(region_province), ''),
    location_city = nullif(btrim(region_city), '')
where location_province is null
  and location_city is null
  and (
    nullif(btrim(region_province), '') is not null
    or nullif(btrim(region_city), '') is not null
  );

-- 行业两列生产实测是 0%，但测试环境可能有零星数据，并进业务标签这几行很便宜。
update buyer_party
set business_tags_json = (
  select coalesce(jsonb_agg(tag_name order by tag_name), '[]'::jsonb)
  from (
    select distinct btrim(candidate.value) as tag_name
    from jsonb_array_elements_text(
      case when jsonb_typeof(buyer_party.industries_json) = 'array' then buyer_party.industries_json else '[]'::jsonb end
      || case when jsonb_typeof(buyer_party.industry_l2_json) = 'array' then buyer_party.industry_l2_json else '[]'::jsonb end
    ) as candidate(value)
    where nullif(btrim(candidate.value), '') is not null
  ) as tags
)
where business_tags_json = '[]'::jsonb
  and (
    jsonb_array_length(
      case when jsonb_typeof(industries_json) = 'array' then industries_json else '[]'::jsonb end
    ) > 0
    or jsonb_array_length(
      case when jsonb_typeof(industry_l2_json) = 'array' then industry_l2_json else '[]'::jsonb end
    ) > 0
  );

-- industries_json / industry_l2_json：生产 0%，职责被 business_tags_json +
-- business_summary 取代。行业字典只有 16 个一级行业，接不住买家的细分主业。
-- region_country / long_term_preference_json：零消费者，API 连投影都没有。
-- region_province / region_city：已搬进 location_*。
-- 删 industries_json 会连带删掉 GIN 索引 idx_buyer_party_industries，
-- 由下面 business_tags_json 的 GIN 索引替代，访问模式相同（filter-options 聚合）。
alter table buyer_party
  drop constraint if exists chk_buyer_party_industries_json,
  drop constraint if exists chk_buyer_party_industry_l2_json,
  drop constraint if exists chk_buyer_party_ownership_type,
  drop constraint if exists chk_buyer_party_listed_status,
  drop constraint if exists chk_buyer_party_listing_exchange,
  drop constraint if exists chk_buyer_party_business_tags_json,
  drop column if exists industries_json,
  drop column if exists industry_l2_json,
  drop column if exists region_country,
  drop column if exists region_province,
  drop column if exists region_city,
  drop column if exists long_term_preference_json;

-- 闭集与中文名的唯一真源是 backend/app/registry/indicators.py，这里只是 DB 兜底。
-- ownership_type 里没有「央企」：央企与地方国企的区别落到 business_summary 表达。
-- listed_status 与 listing_exchange 与标的侧共用同一个闭集，不要在别处再写一份。
-- unknown 不是 null：ownership_type / listed_status 是 not null default 'unknown'，
-- 任何判断「这个字段有没有值」的地方，两者必须等价处理。
alter table buyer_party
  add constraint chk_buyer_party_ownership_type
  check (ownership_type in ('state_owned', 'private', 'foreign', 'other', 'unknown')),
  add constraint chk_buyer_party_listed_status
  check (listed_status in ('listed', 'unlisted', 'pre_ipo', 'unknown')),
  add constraint chk_buyer_party_listing_exchange
  check (
    listing_exchange is null
    or listing_exchange in ('sse', 'szse', 'bse', 'hkex', 'nyse', 'nasdaq', 'other', 'unknown')
  ),
  add constraint chk_buyer_party_business_tags_json
  check (jsonb_typeof(business_tags_json) = 'array');

create index if not exists idx_buyer_party_business_tags
  on buyer_party using gin (business_tags_json)
  where deleted_at is null;
