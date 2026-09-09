-- 标的行业改自由标签，与买家两侧同口径（方案 0908，阶段 A）。
--
-- 阿里云 94 个标的里 52 个的行业就是「制造与工业」四个字，字典没有在承担信息。
-- 唯一的跨侧契约（买家行业词对标的 industry_pairs_json）0828 已解散，
-- 留着字典等于维护一个没有对手方的闭集。
--
-- 本文件只加列、回填、加索引。三个旧列（industry_pairs_json / industry_l1 /
-- industry_l2）与 industry_taxonomy 表的 drop 在阶段 B，等两套部署都跑上本轮
-- 代码并完成存量收敛之后另开迁移（026）。
--
-- 注意：本文件的注释里不能出现分号。自制 splitter 按分号切语句，
-- 注释里的分号会切坏语句、部署直接挂（有过事故，见 AGENTS.md）。

alter table seller_target
  add column if not exists business_tags_json jsonb not null default '[]'::jsonb;

alter table seller_target
  drop constraint if exists chk_seller_target_business_tags_json;

alter table seller_target
  add constraint chk_seller_target_business_tags_json
  check (jsonb_typeof(business_tags_json) = 'array');

-- 回填只取二级行业。一级大类（制造与工业）不是业务标签，写进去会污染标签筛选
-- 下拉，而且对读摘要的 Agent 没有任何信息量。没有二级的标的留空，等重解析收敛
-- （方案 0908 第 5.3 节）。只回填空数组，幂等，重跑不覆盖人工或解析写过的值。
update seller_target
set business_tags_json = (
  select coalesce(jsonb_agg(l2 order by l2), '[]'::jsonb)
  from (
    select distinct btrim(pair ->> 'l2') as l2
    from jsonb_array_elements(
      case when jsonb_typeof(seller_target.industry_pairs_json) = 'array'
           then seller_target.industry_pairs_json else '[]'::jsonb end
    ) as pair
    where nullif(btrim(pair ->> 'l2'), '') is not null
  ) as tags
)
where business_tags_json = '[]'::jsonb
  and exists (
    select 1
    from jsonb_array_elements(
      case when jsonb_typeof(industry_pairs_json) = 'array'
           then industry_pairs_json else '[]'::jsonb end
    ) as pair
    where nullif(btrim(pair ->> 'l2'), '') is not null
  );

-- 访问模式与 idx_buyer_party_business_tags 相同（列表标签筛选与 filter-options 聚合）。
create index if not exists idx_seller_target_business_tags
  on seller_target using gin (business_tags_json)
  where deleted_at is null;
