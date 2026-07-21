-- Match-MA matching dimension alignment (accuracy plan batch 2)
-- Purpose: give every buyer requirement a matching target-side field so the
-- rule layer can judge it, and promote industry L2 from a normalisation-only
-- lookup into a real screening dimension.
--
-- Notes
--   * schema only; prompt versions are managed via the Settings UI
--   * no fixed UUIDs are allocated here, dictionary rows keep gen_random_uuid()

begin;

-- ---------------------------------------------------------------------------
-- 1. Industry L2 becomes a screening dimension on both sides
-- ---------------------------------------------------------------------------

alter table seller_target
  add column if not exists industry_l2 text;

alter table buyer_intent
  add column if not exists industry_l2_json jsonb not null default '[]'::jsonb;

-- excluded_industries_json intentionally stays a single mixed-granularity list
-- (normalize_excluded_terms already preserves "风电" rather than folding it up
-- to 能源). The level of each term is resolved against the dictionary at match
-- time, so legacy rows gain L2-exact matching without a data migration.

create index if not exists idx_seller_target_industry_l2
  on seller_target (team_id, industry_l2) where deleted_at is null;

-- ---------------------------------------------------------------------------
-- 2. Buyer-side counterparts for target-side facts that had no requirement side
-- ---------------------------------------------------------------------------

alter table buyer_intent
  -- 经营状态要求：直接复用标的侧枚举的取值集合
  add column if not exists acceptable_cash_flow_status_json jsonb not null default '[]'::jsonb,
  add column if not exists acceptable_profitability_status_json jsonb not null default '[]'::jsonb,
  -- 迁址 / 返投 / 团队留任 / 对赌：要求强度，对标的侧的能力或意愿枚举
  add column if not exists requires_relocation text not null default 'unknown',
  add column if not exists relocation_target_regions_json jsonb not null default '[]'::jsonb,
  add column if not exists requires_return_investment text not null default 'unknown',
  add column if not exists return_investment_multiple numeric(10,4),
  add column if not exists requires_team_retention text not null default 'unknown',
  add column if not exists earnout_requirement text not null default 'unknown',
  -- 上市地（境内/境外）：样本里买家提的是上市地而不是板块
  add column if not exists listing_market_region text,
  -- 出资预算：与整体估值口径分开，只用于反推隐含估值，不做硬筛
  add column if not exists budget_min_yuan numeric(20,2),
  add column if not exists budget_max_yuan numeric(20,2);

alter table seller_target
  add column if not exists listing_market_region text;

do $do$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'chk_buyer_intent_requirement_strength'
  ) then
    alter table buyer_intent add constraint chk_buyer_intent_requirement_strength check (
      requires_relocation in ('required', 'preferred', 'not_required', 'unknown')
      and requires_return_investment in ('required', 'preferred', 'not_required', 'unknown')
      and requires_team_retention in ('required', 'preferred', 'not_required', 'unknown')
      and earnout_requirement in ('required', 'preferred', 'not_required', 'unknown')
    );
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'chk_buyer_intent_listing_market_region'
  ) then
    alter table buyer_intent add constraint chk_buyer_intent_listing_market_region check (
      listing_market_region is null
      or listing_market_region in ('domestic', 'overseas', 'unknown')
    );
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'chk_seller_target_listing_market_region'
  ) then
    alter table seller_target add constraint chk_seller_target_listing_market_region check (
      listing_market_region is null
      or listing_market_region in ('domestic', 'overseas', 'unknown')
    );
  end if;
end
$do$;

-- Listing market region is derivable from the board we already store.
update seller_target
set listing_market_region = case
      when listing_board in ('main_board', 'gem', 'star_market', 'bse') then 'domestic'
      when listing_board in ('hkex', 'nasdaq', 'nyse') then 'overseas'
      else 'unknown'
    end
where listing_market_region is null
  and listing_board is not null;

-- ---------------------------------------------------------------------------
-- 3. Promote genuinely narrower dictionary aliases to L2
-- ---------------------------------------------------------------------------
-- These terms are industry segments, not synonyms of their L1. Kept as aliases
-- they collapsed into a 15-way L1 bucket and contributed nothing to screening;
-- as L2 they become the main filtering layer. Pure L1 synonyms
-- (医药健康 / 制造业 / 信息技术 …) intentionally stay aliases.

update industry_taxonomy
set level = 'l2',
    canonical_term_id = null,
    updated_at = now()
where level = 'alias'
  and term in (
    '半导体', '集成电路', '芯片', '软件', '互联网', '通信', '大数据', '云计算',
    '北斗', '卫星应用', '光通信', '光电子', 'PCB', '电子', '工业互联网',
    '生物技术', '生物制药', '制药', '医药商业', '康养',
    '新能源', '电力', '动力电池', '电池', '氢能',
    '食品制造', '食品', '电商',
    '有色金属压铸', '汽车', '精细化工', '低空经济', '无人机', '纺织业',
    '采矿业', '矿业', '有色金属及矿业',
    '物流仓储', '交通基础设施',
    '建材家居', '建材',
    '文化旅游', '文旅', '体育',
    '教育机构', '职业教育',
    '咨询'
  );

-- Re-wire parentage for everything now sitting at L2 (idempotent).
update industry_taxonomy child
set parent_id = parent.id,
    updated_at = now()
from industry_taxonomy parent
where child.level = 'l2'
  and child.parent_id is null
  and parent.team_id = child.team_id
  and parent.workspace_id = child.workspace_id
  and parent.level = 'l1'
  and parent.term = child.l1_name;

commit;
