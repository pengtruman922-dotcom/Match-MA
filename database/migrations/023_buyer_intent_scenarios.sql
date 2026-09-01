-- 买家需求方案化 —— 阶段 A：方案表加真列、回填、需求侧字段退役。旧列一律保留。
--
-- 一条买家需求不再是「公共条件 + N 个方案覆盖」两层，而是一个容器挂 1..N 个
-- 互相独立、各自完整的方案，命中任意一个即算命中这条需求。方案见
-- 《买家需求方案化重构方案0901.md》。
--
-- ============ 为什么要取消公共层 ============
--
-- 公共层不是「共享的便利」，是解析器猜不出某条约束属于哪一档时的兜底桶。
-- 2026-09-01 实测生产库：公共层与方案层的取值**冲突了 11 个格子**。
-- 广百股份的公共层挂着「估值上限 30 亿 + 可接受地区 山东省/广东省」，
-- 而它的两个方案是「广州重奢奥莱项目」和「超市便利店零售业态」——
-- 那两条约束到底属于哪一个，原文里根本看不出来，现在两个都被压着。
--
-- ============ 为什么方案表必须换成真列 ============
--
-- 现在方案的条件存在 fields_json 这个没有 schema 的袋子里。实测 18 个方案的
-- 83 个取值中，**25 个（30%）打在迁移 022 已经退役的列上**（max_debt_ratio、
-- min_net_margin、industry_l2_json、requires_team_retention、earnout_requirement、
-- market_cap_range_summary）。没有 CHECK、没有注册表管辖，必然漂移。
-- 换成真列之后才能进 SQL 筛选、有形状约束、被注册表统一管。
--
-- ============ 回填只是保底，正解是重跑解析 ============
--
-- 实测生产库 524 条字段来源记录里**人工填写/修改为 0**
-- （buyer_intent_parse 360、attachment_ocr_parse 76、extracted_action 88）。
-- 所以重跑解析比机械回填准：解析器面对的是原文，不需要猜「公共层的这条约束
-- 属于哪个方案」，因为重跑之后公共层不存在了。
-- 本文件的回填只服务两种情况：重跑失败的，以及重跑之前的那段窗口。
--
-- ============ 本文件的两条硬规则 ============
--
-- 一、注释里不能出现分号。自制 splitter（backend/app/migration_sql.py）按分号
--     切语句，注释里的分号会切坏语句、部署直接挂（有过事故，见 AGENTS.md）。
--
-- 二、有既有 CHECK 约束的表，同一约束涉及的多列必须在同一条 UPDATE 里改完。
--     本文件新建的市值区间约束涉及 min 与 max 两列，所以它们必须在同一条
--     UPDATE 里赋值，并且约束在回填之后才建。

-- ===== 一、方案表加 13 列 =====
--
-- scenario_summary 是这一单的核心字段：它同时是界面上这个方案的标题、
-- 反向检索 skill 第一层扫描读的材料、业务匹配判断的主材料。
-- 因此方案**不设名称**，label 列保留但停止写入。
--
-- 不再单设「业务说明」：022 之后 intent_business_summary 中位只有 54 字，
-- 跟标签列表差不多长，再设一个跨业务与门槛的摘要，两个文本字段必然互相抄。
--
-- required_regions_json 取代 acceptable_regions_json 这个名字：它是硬要求。
-- 「广东优先」「优先大湾区」这类偏好一律进 other_requirements_text，
-- 不进这一列 —— 填进来会把外地的好标的直接筛掉。
alter table buyer_intent_scenario
  add column if not exists scenario_summary text,
  add column if not exists excluded_business_text text,
  add column if not exists other_requirements_text text,
  add column if not exists business_tags_json jsonb not null default '[]'::jsonb,
  add column if not exists required_regions_json jsonb not null default '[]'::jsonb,
  add column if not exists acceptable_listed_status_json jsonb not null default '[]'::jsonb,
  add column if not exists min_revenue_yuan numeric(20,2),
  add column if not exists min_net_profit_yuan numeric(20,2),
  add column if not exists max_pe numeric(10,4),
  add column if not exists min_market_cap_yuan numeric(20,2),
  add column if not exists max_market_cap_yuan numeric(20,2),
  add column if not exists min_valuation_yuan numeric(20,2),
  add column if not exists max_valuation_yuan numeric(20,2);

-- ===== 二、给没有方案的需求生成一个方案 =====
--
-- 40/48 条需求现在没有方案行。方案化之后「需求没有方案」是不合法状态 ——
-- 门槛只住在方案里，没有方案就等于这条需求什么都没说。
--
-- label 传空串而不是需求名：它已经停止写入，留着只为不破坏 not null。
insert into buyer_intent_scenario (
  team_id, workspace_id, buyer_intent_id, label, sort_order, active, source,
  scenario_summary, excluded_business_text, business_tags_json,
  required_regions_json, acceptable_listed_status_json,
  min_revenue_yuan, min_net_profit_yuan, max_pe,
  min_market_cap_yuan, max_market_cap_yuan,
  min_valuation_yuan, max_valuation_yuan
)
select
  bi.team_id, bi.workspace_id, bi.id, '', 0, true, 'parser',
  bi.intent_business_summary,
  bi.excluded_business_text,
  case when jsonb_typeof(bi.intent_business_tags_json) = 'array'
       then bi.intent_business_tags_json else '[]'::jsonb end,
  case when jsonb_typeof(bi.acceptable_regions_json) = 'array'
       then bi.acceptable_regions_json else '[]'::jsonb end,
  case when jsonb_typeof(bi.acceptable_listed_status_json) = 'array'
       then bi.acceptable_listed_status_json else '[]'::jsonb end,
  bi.min_revenue_yuan, bi.min_net_profit_yuan, bi.max_pe,
  bi.min_market_cap_yuan, bi.max_market_cap_yuan,
  bi.min_valuation_yuan, bi.max_valuation_yuan
from buyer_intent bi
where bi.deleted_at is null
  and not exists (
    select 1 from buyer_intent_scenario s
    where s.buyer_intent_id = bi.id and s.deleted_at is null
  );

-- ===== 三、已有方案：方案值优先，公共值补空 =====
--
-- 这等价于现行「公共条件 AND 任一方案」的效果 —— 11 个冲突格子会自动取到
-- 方案侧的值，而实测那 11 个里方案侧全都是更严的那个（广晟的估值上限 3 亿
-- 对公共的 5 亿、北大健康非上市档的净利 2000 万对公共的 1000 万）。
--
-- 数字列与 jsonb 列分两条 UPDATE：市值区间的 CHECK 约束在本文件末尾才建，
-- 建之前这里不受任何多列约束的约束，可以安全拆分。
--
-- **数字必须先验形状再转型。** fields_json 是个没有 schema 的自由袋子，
-- 里面存过什么没人拦过 —— 一个 "5000万" 这样的值就会让 ::numeric 在运行时抛错，
-- 而这是 preDeploy 迁移：它挂了整个部署会被阻断回滚。正则不匹配的当成没值，
-- 退回需求侧的公共值，比让部署炸掉好。
update buyer_intent_scenario s
set
    min_revenue_yuan = coalesce(
      case when s.fields_json->>'min_revenue_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'min_revenue_yuan')::numeric end,
      bi.min_revenue_yuan),
    min_net_profit_yuan = coalesce(
      case when s.fields_json->>'min_net_profit_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'min_net_profit_yuan')::numeric end,
      bi.min_net_profit_yuan),
    max_pe = coalesce(
      case when s.fields_json->>'max_pe' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'max_pe')::numeric end,
      bi.max_pe),
    min_market_cap_yuan = coalesce(
      case when s.fields_json->>'min_market_cap_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'min_market_cap_yuan')::numeric end,
      bi.min_market_cap_yuan),
    max_market_cap_yuan = coalesce(
      case when s.fields_json->>'max_market_cap_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'max_market_cap_yuan')::numeric end,
      bi.max_market_cap_yuan),
    min_valuation_yuan = coalesce(
      case when s.fields_json->>'min_valuation_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'min_valuation_yuan')::numeric end,
      bi.min_valuation_yuan),
    max_valuation_yuan = coalesce(
      case when s.fields_json->>'max_valuation_yuan' ~ '^-?[0-9]+(\.[0-9]+)?$'
           then (s.fields_json->>'max_valuation_yuan')::numeric end,
      bi.max_valuation_yuan)
from buyer_intent bi
where bi.id = s.buyer_intent_id
  and s.deleted_at is null;

-- jsonb 列取值前先判形状：fields_json 是自由袋子，存过非数组的值一条就能把
-- 后面的 jsonb_array_length 打成运行时错误、整个 preDeploy 回滚。
update buyer_intent_scenario s
set business_tags_json = case
      when jsonb_typeof(s.fields_json->'intent_business_tags_json') = 'array'
           and jsonb_array_length(s.fields_json->'intent_business_tags_json') > 0
        then s.fields_json->'intent_business_tags_json'
      when jsonb_typeof(bi.intent_business_tags_json) = 'array'
        then bi.intent_business_tags_json
      else '[]'::jsonb end,
    required_regions_json = case
      when jsonb_typeof(s.fields_json->'acceptable_regions_json') = 'array'
           and jsonb_array_length(s.fields_json->'acceptable_regions_json') > 0
        then s.fields_json->'acceptable_regions_json'
      when jsonb_typeof(bi.acceptable_regions_json) = 'array'
        then bi.acceptable_regions_json
      else '[]'::jsonb end,
    acceptable_listed_status_json = case
      when jsonb_typeof(s.fields_json->'acceptable_listed_status_json') = 'array'
           and jsonb_array_length(s.fields_json->'acceptable_listed_status_json') > 0
        then s.fields_json->'acceptable_listed_status_json'
      when jsonb_typeof(bi.acceptable_listed_status_json) = 'array'
        then bi.acceptable_listed_status_json
      else '[]'::jsonb end,
    excluded_business_text = coalesce(
      nullif(s.fields_json->>'excluded_business_text', ''),
      bi.excluded_business_text)
from buyer_intent bi
where bi.id = s.buyer_intent_id
  and s.deleted_at is null;

-- ===== 四、摘要与其他要求 =====
--
-- 摘要回填只是把旧内容搬过来，**口径没有重定义**。新口径是「一段话说清这个
-- 方案要买什么业务、什么地域、什么规模」，那要靠重跑解析才能收敛。
-- label 的现有取值拼在最前面：它停止写入了，但那是顾问和解析写下的分档名
-- （「上市公司收购方案」「粮油食品」），不能丢。
update buyer_intent_scenario s
set scenario_summary = nullif(concat_ws(
      chr(10),
      nullif(s.label, ''),
      coalesce(
        nullif(s.fields_json->>'intent_business_summary', ''),
        bi.intent_business_summary,
        nullif(s.fields_json->>'intent_summary', ''),
        bi.intent_summary)
    ), '')
from buyer_intent bi
where bi.id = s.buyer_intent_id
  and s.deleted_at is null
  and s.scenario_summary is null;

-- 其他要求收口：022 退役的描述字段、本单退役的六个筛选字段，以及 fields_json
-- 里那 25 个打在已退役列上的取值，全部拼进这一段。**重跑之后 AI 会重新归纳，
-- 这里只保证信息不丢。**
--
-- 地域摘要放第一条：它承载的正是「广东优先、珠三角优先」这类偏好，
-- 而偏好从这一单起明确不进 required_regions_json。
update buyer_intent_scenario s
set other_requirements_text = nullif(concat_ws(
      chr(10),
      case when coalesce(bi.region_scope_summary, '') <> ''
           then '地域：' || bi.region_scope_summary end,
      case when coalesce(bi.buyer_industry_advantage_summary, '') <> ''
           then '买家产业优势：' || bi.buyer_industry_advantage_summary end,
      case when coalesce(bi.major_risk_tolerance_summary, '') <> ''
           then '风险容忍：' || bi.major_risk_tolerance_summary end,
      case when coalesce(bi.transaction_type, '') <> ''
           then '交易方式：' || bi.transaction_type end,
      case when bi.requires_control in ('required', 'yes')
           then '要求取得控股权' end,
      case when bi.requires_consolidation in ('required', 'yes')
           then '要求能并表' end,
      case when bi.desired_equity_ratio_min is not null
           then '期望股比不低于 ' || round(bi.desired_equity_ratio_min, 2)::text || '%' end,
      case when bi.desired_equity_ratio_max is not null
           then '期望股比不高于 ' || round(bi.desired_equity_ratio_max, 2)::text || '%' end,
      case when jsonb_typeof(bi.transaction_types_json) = 'array'
                and jsonb_array_length(bi.transaction_types_json) > 0
           then '可接受交易结构：' || (
                  select string_agg(value, '、')
                  from jsonb_array_elements_text(bi.transaction_types_json)
                ) end,
      case when jsonb_typeof(bi.unacceptable_risk_flags_json) = 'array'
                and jsonb_array_length(bi.unacceptable_risk_flags_json) > 0
           then '不接受的重大风险：' || (
                  select string_agg(value, '、')
                  from jsonb_array_elements_text(bi.unacceptable_risk_flags_json)
                ) end,
      nullif(s.fields_json->>'market_cap_range_summary', ''),
      nullif(s.fields_json->>'equity_ratio_summary', ''),
      nullif(s.fields_json->>'premium_tolerance_summary', ''),
      nullif(s.fields_json->>'debt_ratio_requirement_summary', ''),
      nullif(s.fields_json->>'listing_board_requirement_summary', ''),
      nullif(s.fields_json->>'financing_stage_requirement_summary', ''),
      case when nullif(s.fields_json->>'max_debt_ratio', '') is not null
           then '资产负债率不高于 ' || (s.fields_json->>'max_debt_ratio') || '%' end,
      case when nullif(s.fields_json->>'min_net_margin', '') is not null
           then '净利率不低于 ' || (s.fields_json->>'min_net_margin') || '%' end,
      case when nullif(s.fields_json->>'min_gross_margin', '') is not null
           then '毛利率不低于 ' || (s.fields_json->>'min_gross_margin') || '%' end,
      case when nullif(s.fields_json->>'max_premium_rate', '') is not null
           then '溢价不高于 ' || (s.fields_json->>'max_premium_rate') || '%' end,
      case when nullif(s.fields_json->>'min_total_profit_yuan', '') is not null
           then '利润总额不低于 ' || (s.fields_json->>'min_total_profit_yuan') || ' 元' end,
      case when s.fields_json->>'requires_team_retention' in ('required', 'preferred', 'yes')
           then '希望核心团队留任' end,
      case when s.fields_json->>'requires_relocation' in ('required', 'preferred', 'yes')
           then '涉及迁址要求' end,
      case when s.fields_json->>'requires_return_investment' in ('required', 'preferred', 'yes')
           then '涉及返投要求' end,
      case when s.fields_json->>'earnout_requirement' in ('required', 'preferred', 'yes')
           then '接受或要求业绩对赌' end,
      case when s.fields_json->>'accepts_minority_investment' in ('yes', 'required', 'preferred')
           then '接受少数股权投资' end,
      case when jsonb_typeof(s.fields_json->'industry_l2_json') = 'array'
                and jsonb_array_length(s.fields_json->'industry_l2_json') > 0
           then '关注细分行业：' || (
                  select string_agg(value, '、')
                  from jsonb_array_elements_text(s.fields_json->'industry_l2_json')
                ) end,
      case when jsonb_typeof(s.fields_json->'industry_focus_tags_json') = 'array'
                and jsonb_array_length(s.fields_json->'industry_focus_tags_json') > 0
           then '关注方向：' || (
                  select string_agg(value, '、')
                  from jsonb_array_elements_text(s.fields_json->'industry_focus_tags_json')
                ) end,
      case when jsonb_typeof(bi.excluded_regions_json) = 'array'
                and jsonb_array_length(bi.excluded_regions_json) > 0
           then '排除地区：' || (
                  select string_agg(
                    concat_ws('', item->>'province', item->>'city', item->>'district'), '、')
                  from jsonb_array_elements(bi.excluded_regions_json) as region(item)
                ) end
    ), '')
from buyer_intent bi
where bi.id = s.buyer_intent_id
  and s.deleted_at is null
  and s.other_requirements_text is null;

-- ===== 五、约束与索引 =====
--
-- 形状约束只管 jsonb 是不是数组。元素内部的形状由代码侧归一化保证 ——
-- DB 层做深检查会让一次解析写入变成一次全量校验，不划算。
alter table buyer_intent_scenario
  drop constraint if exists chk_bis_business_tags_json,
  drop constraint if exists chk_bis_required_regions_json,
  drop constraint if exists chk_bis_listed_status_json,
  drop constraint if exists chk_bis_market_cap_range,
  drop constraint if exists chk_bis_valuation_range;

alter table buyer_intent_scenario
  add constraint chk_bis_business_tags_json
  check (jsonb_typeof(business_tags_json) = 'array'),
  add constraint chk_bis_required_regions_json
  check (jsonb_typeof(required_regions_json) = 'array'),
  add constraint chk_bis_listed_status_json
  check (jsonb_typeof(acceptable_listed_status_json) = 'array'),
  add constraint chk_bis_market_cap_range
  check (min_market_cap_yuan is null or max_market_cap_yuan is null
         or min_market_cap_yuan <= max_market_cap_yuan),
  add constraint chk_bis_valuation_range
  check (min_valuation_yuan is null or max_valuation_yuan is null
         or min_valuation_yuan <= max_valuation_yuan);

create index if not exists idx_bis_business_tags
  on buyer_intent_scenario using gin (business_tags_json)
  where deleted_at is null;

create index if not exists idx_bis_intent_active
  on buyer_intent_scenario (buyer_intent_id, sort_order)
  where deleted_at is null and active;
