-- 迁移 023 的验证用例。**只读，全部是 select，可以随便跑。**
--
-- 用法：跑完 `alembic upgrade head` 之后，把这个文件整份贴进生产库的 SQL 客户端，
-- 逐段核对「期望」那一列。期望值取自 2026-09-01 的生产快照
-- （58 条需求，其中 8 条带方案共 18 行；48 条真实 + 10 条 Mock）。
--
-- 库里数据变过的话行数会对不上，那不一定是迁移错了 —— 先看第 0 段的基线。
-- 判断的重点是**每段的语义断言**（用 case 写成了 PASS/FAIL），不是绝对行数。

-- ===== 0. 基线：先确认库存和快照一致 =====
--
-- 这一段不测迁移，测的是「期望值还适用不适用」。对不上就别看下面的绝对数字了，
-- 只看 PASS/FAIL 的那些。
select
  (select count(*) from buyer_intent where deleted_at is null)                as 需求数_期望58,
  (select count(distinct buyer_intent_id) from buyer_intent_scenario
    where deleted_at is null and label <> '')                                 as 迁移前有方案的需求数_期望8,
  (select count(*) from buyer_intent_scenario where deleted_at is null)       as 方案总数_期望68;

-- ===== 1. 每条需求都必须有方案 =====
--
-- **这是最要紧的一条。** 方案是门槛唯一的住处，一条需求没有方案等于它的要求
-- 全部丢了 —— 而丢了不报错，表现是这条需求从此对谁都通过。
select
  count(*) as 没有方案的需求数_期望0,
  case when count(*) = 0 then 'PASS' else 'FAIL' end as 结论
from buyer_intent bi
where bi.deleted_at is null
  and not exists (
    select 1 from buyer_intent_scenario s
    where s.buyer_intent_id = bi.id and s.deleted_at is null
  );

-- 反过来也查一遍：方案不能挂在已删除的需求上。
select
  count(*) as 孤儿方案数_期望0,
  case when count(*) = 0 then 'PASS' else 'FAIL' end as 结论
from buyer_intent_scenario s
where s.deleted_at is null
  and not exists (
    select 1 from buyer_intent bi
    where bi.id = s.buyer_intent_id and bi.deleted_at is null
  );

-- ===== 2. 冲突格子取到的是方案值，不是公共值 =====
--
-- 实测公共层与方案层冲突 11 个格子，方案侧全都是更严的那个。取错方向的表现是
-- 门槛被放宽 —— 不报错，只是候选池变大、顾问看到一堆不该出现的标的。
--
-- 广晟控股：公共估值上限 5 亿，方案A 是 3 亿 → 方案A 必须是 3 亿。
select
  s.sort_order,
  s.max_valuation_yuan                                   as 估值上限,
  s.min_net_profit_yuan                                  as 最低净利润,
  case
    when s.sort_order = 0 and s.max_valuation_yuan = 300000000 then 'PASS'
    when s.sort_order = 1 and s.max_valuation_yuan = 500000000
         and s.min_net_profit_yuan = 20000000 then 'PASS'
    when s.sort_order = 2 and s.max_valuation_yuan = 500000000
         and s.min_net_profit_yuan = 200000000 then 'PASS'
    when s.sort_order = 3 and s.min_net_profit_yuan = 10000000 then 'PASS'
    else 'FAIL'
  end as 结论
from buyer_intent_scenario s
where s.buyer_intent_id = '93b92c9a-a37a-4735-9291-707b8ef4dcc6'
  and s.deleted_at is null
order by s.sort_order;

-- 北大健康：公共净利 1000 万；上市档方案也写 1000 万，非上市档写 2000 万。
-- 非上市档必须是 2000 万（方案值赢），且 PE 上限 13 从方案里带过来。
select
  s.sort_order,
  s.min_net_profit_yuan                                  as 最低净利润,
  s.max_pe                                               as PE上限,
  s.max_market_cap_yuan                                  as 市值上限,
  s.acceptable_listed_status_json                        as 上市状态,
  case
    when s.sort_order = 0 and s.min_net_profit_yuan = 10000000
         and s.max_market_cap_yuan = 5000000000 then 'PASS'
    when s.sort_order = 1 and s.min_net_profit_yuan = 20000000
         and s.max_pe = 13 then 'PASS'
    else 'FAIL'
  end as 结论
from buyer_intent_scenario s
where s.buyer_intent_id = '6c1b0e26-a826-47d7-98f2-c0ff098af802'
  and s.deleted_at is null
order by s.sort_order;

-- ===== 3. 公共值在方案没说时补进来 =====
--
-- 这等价于现行「公共条件 AND 任一方案」的效果。补不进来的表现是门槛丢失。
--
-- 广百股份：公共有「地区 山东/广东 + 估值上限 30 亿」，两个方案都没说地区，
-- 所以两个方案都该带上这两条。
--
-- ⚠️ **这正是需要人工复核的那 8 条之一**：那两条公共约束到底属于「重奢奥莱」
-- 还是「超市便利店」，原文里看不出来，回填只能照搬给两个。重跑解析才能真正解决。
select
  s.sort_order,
  s.required_regions_json                                as 要求地区,
  s.max_valuation_yuan                                   as 估值上限,
  s.min_revenue_yuan                                     as 最低营收,
  case
    when jsonb_array_length(s.required_regions_json) = 2
         and s.max_valuation_yuan = 3000000000 then 'PASS'
    else 'FAIL'
  end as 结论_两个方案都该继承公共的地区与估值,
  case
    when s.sort_order = 0 and s.min_revenue_yuan = 2200000000 then 'PASS'
    when s.sort_order = 1 and s.min_revenue_yuan is null then 'PASS'
    else 'FAIL'
  end as 结论_营收只属于方案A
from buyer_intent_scenario s
where s.buyer_intent_id = '50265a5f-1172-409c-8caa-010c04ad822d'
  and s.deleted_at is null
order by s.sort_order;

-- ===== 4. 退役列的取值进了「其他要求」，一个字都没丢 =====
--
-- fields_json 里有 25 个取值打在已退役的列上（max_debt_ratio、min_net_margin、
-- market_cap_range_summary、requires_team_retention…）。它们不进任何结构化列，
-- 只能靠这一段兜住 —— 兜不住就是永久丢失。
--
-- 北大健康两档的 market_cap_range_summary 是「其他要求」最典型的内容：
-- 「上市公司市值50亿元以内，可适当放宽到100亿」这句里的"可放宽"正是结构化
-- 字段装不下的弹性口径。
select
  s.sort_order,
  s.other_requirements_text                              as 其他要求,
  case
    when s.sort_order = 0 and s.other_requirements_text like '%可适当放宽到100亿%' then 'PASS'
    when s.sort_order = 1 and s.other_requirements_text like '%PE原则上不超过13倍%' then 'PASS'
    else 'FAIL'
  end as 结论
from buyer_intent_scenario s
where s.buyer_intent_id = '6c1b0e26-a826-47d7-98f2-c0ff098af802'
  and s.deleted_at is null
order by s.sort_order;

-- 广百方案A 的负债率 50%、团队留任、股比下限 51% 都该在其他要求里。
select
  s.other_requirements_text                              as 其他要求,
  case
    when s.other_requirements_text like '%资产负债率不高于 50%'
     and s.other_requirements_text like '%团队留任%'
     and s.other_requirements_text like '%期望股比不低于 51%'  then 'PASS'
    else 'FAIL'
  end as 结论
from buyer_intent_scenario s
where s.buyer_intent_id = '50265a5f-1172-409c-8caa-010c04ad822d'
  and s.sort_order = 0
  and s.deleted_at is null;

-- 全库扫一遍：需求侧有内容、而方案的其他要求是空的，都要人看一眼。
-- 期望 0 行；有行不一定是错（那条需求可能本来就没有这类约束），但值得核。
select
  bi.intent_name,
  bi.region_scope_summary,
  bi.transaction_type,
  bi.major_risk_tolerance_summary
from buyer_intent bi
join buyer_intent_scenario s on s.buyer_intent_id = bi.id and s.deleted_at is null
where bi.deleted_at is null
  and s.other_requirements_text is null
  and (
    coalesce(bi.region_scope_summary, '') <> ''
    or coalesce(bi.transaction_type, '') <> ''
    or coalesce(bi.major_risk_tolerance_summary, '') <> ''
    or bi.requires_control in ('required', 'yes')
    or bi.desired_equity_ratio_min is not null
  )
order by bi.intent_name;

-- ===== 5. label 没丢 =====
--
-- 方案 0901 起没有名称，但「上市公司收购方案」「粮油食品」这些分档名是顾问和
-- 解析写下的，重跑之前它是唯一能区分两档的东西。它拼在摘要开头。
select
  count(*) as 原有label没进摘要的方案数_期望0,
  case when count(*) = 0 then 'PASS' else 'FAIL' end as 结论
from buyer_intent_scenario s
where s.deleted_at is null
  and s.label <> ''
  and (s.scenario_summary is null or position(s.label in s.scenario_summary) = 0);

-- ===== 6. 形状约束与索引都在 =====
select
  conname as 约束名,
  case when conname is not null then 'PASS' else 'FAIL' end as 结论
from pg_constraint
where conrelid = 'buyer_intent_scenario'::regclass
  and conname in (
    'chk_bis_business_tags_json',
    'chk_bis_required_regions_json',
    'chk_bis_listed_status_json',
    'chk_bis_market_cap_range',
    'chk_bis_valuation_range'
  )
order by conname;

select indexname, case when indexname is not null then 'PASS' else 'FAIL' end as 结论
from pg_indexes
where tablename = 'buyer_intent_scenario'
  and indexname in ('idx_bis_business_tags', 'idx_bis_intent_active')
order by indexname;

-- ===== 7. 数字没有被脏值吃掉 =====
--
-- fields_json 是自由袋子，迁移里数字先过正则再转型。**副作用要看**：
-- 一个存成 "5000万" 的值会被判成「没值」，退回需求侧的公共值 —— 那比让
-- preDeploy 炸掉好，但如果真有这种值，人要知道。
--
-- 期望 0 行。有行说明那个方案的这个数字**没有**从 fields_json 迁过来。
select
  s.buyer_intent_id,
  s.sort_order,
  key                                                    as 字段,
  value                                                  as 原始值
from buyer_intent_scenario s
cross join lateral jsonb_each_text(s.fields_json) as kv(key, value)
where s.deleted_at is null
  and key in (
    'min_revenue_yuan', 'min_net_profit_yuan', 'max_pe',
    'min_market_cap_yuan', 'max_market_cap_yuan',
    'min_valuation_yuan', 'max_valuation_yuan'
  )
  and value <> ''
  and value !~ '^-?[0-9]+(\.[0-9]+)?$';

-- ===== 8. 区间约束没被回填数据违反 =====
--
-- 市值与估值的 min <= max 是本迁移新建的 CHECK。约束建在回填之后，所以
-- 它能建起来就说明数据是干净的 —— 这一段是双保险，也顺便让人看到实际区间。
select
  count(*) filter (where min_market_cap_yuan > max_market_cap_yuan) as 市值区间倒挂_期望0,
  count(*) filter (where min_valuation_yuan > max_valuation_yuan)   as 估值区间倒挂_期望0,
  case
    when count(*) filter (where min_market_cap_yuan > max_market_cap_yuan) = 0
     and count(*) filter (where min_valuation_yuan > max_valuation_yuan) = 0
    then 'PASS' else 'FAIL'
  end as 结论
from buyer_intent_scenario
where deleted_at is null;

-- ===== 9. 单方案需求：字段确实从需求搬过来了 =====
--
-- 40 条（含 mock 是 50 条）没有方案的需求各生成一个方案。生成时字段直接从
-- buyer_intent 搬 —— 搬漏了不报错，表现是那条需求的门槛全空。
select
  count(*)                                                       as 单方案需求数,
  count(*) filter (where bi.min_net_profit_yuan is not null
                     and s.min_net_profit_yuan is null)          as 净利没搬过来_期望0,
  count(*) filter (where bi.min_revenue_yuan is not null
                     and s.min_revenue_yuan is null)             as 营收没搬过来_期望0,
  count(*) filter (where coalesce(bi.intent_business_summary, '') <> ''
                     and coalesce(s.scenario_summary, '') = '')  as 摘要没搬过来_期望0,
  count(*) filter (where jsonb_array_length(
                           case when jsonb_typeof(bi.acceptable_regions_json) = 'array'
                                then bi.acceptable_regions_json else '[]'::jsonb end) > 0
                     and jsonb_array_length(s.required_regions_json) = 0)
                                                                 as 地区没搬过来_期望0
from buyer_intent bi
join buyer_intent_scenario s on s.buyer_intent_id = bi.id and s.deleted_at is null
where bi.deleted_at is null
  and s.label = ''
  and (select count(*) from buyer_intent_scenario x
        where x.buyer_intent_id = bi.id and x.deleted_at is null) = 1;

-- ===== 10. 抽查三条，人眼看一遍 =====
--
-- 前面九段测的是「有没有搬错」，这一段是让人看「搬完之后读起来对不对」。
-- 挑的三条覆盖三种形状：单方案、上市/非上市二分、业务二分。
select
  bi.intent_name,
  s.sort_order,
  s.scenario_summary,
  s.business_tags_json,
  s.required_regions_json,
  s.acceptable_listed_status_json,
  s.min_revenue_yuan, s.min_net_profit_yuan, s.max_pe,
  s.min_market_cap_yuan, s.max_market_cap_yuan,
  s.min_valuation_yuan, s.max_valuation_yuan,
  s.other_requirements_text
from buyer_intent bi
join buyer_intent_scenario s on s.buyer_intent_id = bi.id and s.deleted_at is null
where bi.id in (
  '6c1b0e26-a826-47d7-98f2-c0ff098af802',  -- 北大健康：上市/非上市二分
  '50265a5f-1172-409c-8caa-010c04ad822d',  -- 广百股份：业务二分
  '0de82e28-4f8d-4d50-8341-068fd58f70fc'   -- 文旅轻资产：单方案且 fields_json 为空
)
order by bi.intent_name, s.sort_order;
