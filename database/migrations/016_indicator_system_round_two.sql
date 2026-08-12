-- 标的指标体系第二轮：上市地枚举换成交易所、解散技术与团队、
-- 「业务与产品·其他」改名产业优势、删四个 0% 且无买家对手方的列。
-- 判据（每个字段的生产填充率实测）与范围见《标的指标体系二轮施工单0807.md》。
-- 本轮不动筛选与打分代码：上市地是「保留字段换枚举」而不是删字段，
-- 正因为打分那里是相等比较，换值不用改代码。

-- ===== 一、上市地：境内/境外 → 具体交易所 =====
--
-- 生产实况：买家侧 44 个需求的 listing_market_region 全是 NULL（那个 6 分打分
-- 维度从未触发过），标的侧 70 个里 16 个有值且全部是 domestic、0 个 overseas。
-- 这一对指标在生产里完全空转，换枚举零数据损失。
--
-- 顺序：先删旧约束，再改数据，最后加新约束。
-- 反过来写会直接炸：旧约束只认 domestic/overseas/unknown，UPDATE 刚写下
-- 'szse' 就撞上它（002273.SZ 那一行），整次 preDeploy 迁移中止、部署阻断。
alter table seller_target
  drop constraint if exists chk_seller_target_listing_market_region;

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_listing_market_region;

-- domestic 反推不出具体交易所，只能置空；但股票代码后缀能直接判定，
-- 能推的先推 —— 可推导的数据不该因为一次枚举变更就丢掉。
update seller_target
set listing_market_region = case
    when upper(coalesce(stock_code, '')) like '%.SH' then 'sse'
    when upper(coalesce(stock_code, '')) like '%.SZ' then 'szse'
    when upper(coalesce(stock_code, '')) like '%.BJ' then 'bse'
    when upper(coalesce(stock_code, '')) like '%.HK' then 'hkex'
    else null
  end
where listing_market_region is not null
   or stock_code is not null;

update buyer_intent
set listing_market_region = null
where listing_market_region is not null;

alter table seller_target
  add constraint chk_seller_target_listing_market_region
  check (
    listing_market_region is null
    or listing_market_region in (
      'sse', 'szse', 'bse', 'hkex', 'nyse', 'nasdaq', 'other', 'unknown'
    )
  );

alter table buyer_intent
  add constraint chk_buyer_intent_listing_market_region
  check (
    listing_market_region is null
    or listing_market_region in (
      'sse', 'szse', 'bse', 'hkex', 'nyse', 'nasdaq', 'other', 'unknown'
    )
  );

-- ===== 二、「业务与产品·其他」改名产业优势，技术与团队并入 =====
--
-- 顺序不能反：先把现有的 business_product 当前版本整体作废，再让 tech_team
-- 顶上来，否则同一标的会出现两行当前版本。
--
-- 为什么作废而不是保留：实测 23 个同时有 business_summary 与该栏内容的标的里，
-- 高度重复 2 个、部分重复 6 个，剩下 15 个字面不同的抽样看也是同一件事换个说法。
-- 栏目改叫「产业优势」之后这些内容不对题，留着会让新栏目一上线就变成
-- 「业务摘要 2 号」—— 正是这次要消灭的东西。
--
-- 作废是软删：内容留在表里可回查，只是不再是当前值。注意这段是裸 SQL，
-- 不经过 apply_profile_section，所以不会写 action_application_log，
-- 顾问在「更新记录」里看不到这次作废。已知取舍。
update entity_profile_section
set deleted_at = now(), updated_at = now()
where entity_type = 'seller_target'
  and section_code = 'business_product'
  and deleted_at is null
  and review_status in ('accepted', 'auto_accepted');

-- 技术与团队那一栏装的是产能、资质、技术路线、核心团队 —— 本来就是「优势」，
-- 整段接管产业优势栏。
update entity_profile_section
set section_code = 'business_product', updated_at = now()
where entity_type = 'seller_target'
  and section_code = 'tech_team'
  and deleted_at is null
  and review_status in ('accepted', 'auto_accepted');

-- 历史版本（软删的、未采纳的）也要改码，否则新约束加不上去。
update entity_profile_section
set section_code = 'business_product'
where section_code = 'tech_team';

alter table entity_profile_section
  drop constraint if exists entity_profile_section_section_code_check;

alter table entity_profile_section
  add constraint entity_profile_section_section_code_check
  check (section_code in (
    'identity', 'business_product', 'ops_quality', 'deal_terms',
    'intent_scope', 'intent_financial', 'intent_deal'
  ));

-- ===== 三、删四个 0% 填充且无买家对手方的列 =====
--
-- 70 个标的上全部为空，且都不出现在 recommendation_flow.py / search_docs.py /
-- recommendation.py —— 删除不触碰打分与召回。
--   management_team_summary    全仓唯一引用是 API 出参与前端标签
--   transfer_flexibility_type  与 can_control / can_consolidate /
--                              accepts_minority_investment 重复表达
--   consolidation_path_summary 散文，内容归交易属性画像栏
--   earnout_dependency_status  无对手方枚举
alter table seller_target
  drop constraint if exists seller_target_transfer_flexibility_type_check,
  drop constraint if exists seller_target_earnout_dependency_status_check;

alter table seller_target
  drop column if exists management_team_summary,
  drop column if exists transfer_flexibility_type,
  drop column if exists consolidation_path_summary,
  drop column if exists earnout_dependency_status;
