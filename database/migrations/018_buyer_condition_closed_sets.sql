-- 买家侧条件闭集补齐：重大风险容忍新建、交易方式改闭集、股比单位污染修正。
--
-- 这是第一轮真正让注册表四项声明（screening / operator / target_column /
-- enum_options）承重的迁移：推荐线的筛选 schema 由它们生成，所以两侧闭集
-- 从这一轮起必须能对得上。方案与范围见《指标体系与推荐对齐方案0817.md》
-- 与《指标体系与推荐对齐施工单0817.md》。
--
-- 三段互相独立，任何一段失败都不该带走另外两段的收益，所以不共用事务假设。

-- ===== 一、新增：买家不接受的重大风险 =====
--
-- 标的侧 major_risk_flags_json 的 5 值里 none 是「核查状态」不是「风险类型」，
-- 「不接受已核查无风险」讲不通，所以买家侧是它的 4 值子集。配对审计按「子集」
-- 档校验（差集只允许 unknown 或状态值），不是等号。
--
-- 三态全部由这一个字段表达，不加第二列：
--   []        未提及（推荐时不带这个条件）
--   四值全集   不接受全部（由 normalize_unacceptable_risk_flags 展开，不由 SQL 判）
--   其余子集   不接受特定类型
--
-- 与之配套的 SQL 模板必须带「已核查」前置：
--   t.major_risk_flags_json <> '[]'::jsonb and not exists (... overlap ...)
-- 少了前半段，未核查（[]）的标的会通过 not_overlap —— 「没查过」被当成
-- 「干净」，方向恰好是危险的那一边。

alter table buyer_intent
  add column if not exists unacceptable_risk_flags_json jsonb not null default '[]'::jsonb;

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_unacceptable_risk_flags_json;

alter table buyer_intent
  add constraint chk_buyer_intent_unacceptable_risk_flags_json
  check (
    jsonb_typeof(unacceptable_risk_flags_json) = 'array'
    and unacceptable_risk_flags_json
        <@ '["litigation", "equity_frozen", "enforcement", "violation"]'::jsonb
  );

-- ===== 二、交易方式：先救原话，再重写闭集 =====
--
-- 存量 27/44 的取值混了三个正交轴，只有第一轴对得上标的侧闭集：
--   交易结构    老股转让 / 定增 / 资产收购 / 吸收合并 / 借壳重组 / 并购
--   支付方式    现金 / 股份 / 现金+股份 / 全现金收购 / 换股 / 交叉持股
--   控制权诉求  控股收购 / 少数股权 / 战略投资 / 战略参股
--
-- 后两轴在标的侧没有对手方列（支付方式待下一轮成对新建，控制权诉求已由
-- requires_control / accepts_minority_investment / desired_equity_ratio_* 表达），
-- 所以重写后它们会从这一列消失。**顺序不能反**：先把原数组存进原话列再重写，
-- 否则映射不上的那些行直接蒸发，顾问会当成数据丢失报障。
--
-- transaction_type 从「兼容标量」改判为「交易方式原文」，与 industry_primary
-- 同定位：解析溯源 + 深评阅读，不参与任何匹配。只在它为空时写入。

update buyer_intent bi
set transaction_type = (
      select string_agg(t.value, '、' order by t.ord)
      from jsonb_array_elements_text(bi.transaction_types_json)
           with ordinality as t(value, ord)
    )
where jsonb_array_length(coalesce(bi.transaction_types_json, '[]'::jsonb)) > 0
  and coalesce(nullif(btrim(bi.transaction_type), ''), '') = '';

update buyer_intent bi
set transaction_types_json = coalesce(
      (
        select jsonb_agg(distinct m.code)
        from jsonb_array_elements_text(bi.transaction_types_json) as t(value)
        cross join lateral (
          select case
            when t.value in ('老股转让', '股权转让')        then 'equity_transfer'
            when t.value in ('定增', '增资控股', '增资扩股') then 'capital_increase'
            when t.value in ('资产收购')                   then 'asset_purchase'
            when t.value in ('吸收合并', '并购', '借壳重组') then 'merger'
            else null
          end as code
        ) as m
        where m.code is not null
      ),
      '[]'::jsonb
    )
where jsonb_array_length(coalesce(bi.transaction_types_json, '[]'::jsonb)) > 0;

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_transaction_types_json;

alter table buyer_intent
  add constraint chk_buyer_intent_transaction_types_json
  check (
    jsonb_typeof(transaction_types_json) = 'array'
    and transaction_types_json
        <@ '["equity_transfer", "capital_increase", "asset_purchase", "merger", "other"]'::jsonb
  );

-- ===== 三、既有三个闭集列补元素级约束 =====
--
-- 它们从 011 起就只有形状约束（jsonb_typeof = 'array'），元素取值全靠应用层的
-- _normalize_closed_list_values 拦。标的侧 015 建的两列一开始就是元素级 `<@`，
-- 两侧不一致意味着买家侧改注册表枚举时没有任何东西会挡住漂移。
-- 生产实测这三列的现有取值都在闭集内（可接受上市状态 14 行、另两列 0 行），
-- 加约束零数据风险。

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_acceptable_listed_status_json,
  drop constraint if exists chk_buyer_intent_acceptable_cash_flow_status_json,
  drop constraint if exists chk_buyer_intent_acceptable_profitability_status_json;

alter table buyer_intent
  add constraint chk_buyer_intent_acceptable_listed_status_json
  check (
    jsonb_typeof(acceptable_listed_status_json) = 'array'
    and acceptable_listed_status_json <@ '["listed", "unlisted", "pre_ipo"]'::jsonb
  ),
  add constraint chk_buyer_intent_acceptable_cash_flow_status_json
  check (
    jsonb_typeof(acceptable_cash_flow_status_json) = 'array'
    and acceptable_cash_flow_status_json
        <@ '["stable_positive", "positive", "negative", "unstable", "unknown"]'::jsonb
  ),
  add constraint chk_buyer_intent_acceptable_profitability_status_json
  check (
    jsonb_typeof(acceptable_profitability_status_json) = 'array'
    and acceptable_profitability_status_json
        <@ '["profitable", "loss_making", "break_even", "unknown"]'::jsonb
  );

-- ===== 四、股比单位污染 =====
--
-- desired_equity_ratio_min 里混着一条 0.2990（原话「上市公司29.9%及以下」被
-- 存成了分数），其余是 51 / 100 / 25 / 60 这样的百分数。同一个 gte 条件上并存
-- 两种口径，那一行会通过一切，而且不报错。
--
-- 阈值取 1：股比小于 1% 的收购诉求在业务上不存在，所以「小于 1」等价于
-- 「这一行存的是分数」。0 排除在外（0 是「没有下限」不是分数）。

update buyer_intent
set desired_equity_ratio_min = desired_equity_ratio_min * 100
where desired_equity_ratio_min is not null
  and desired_equity_ratio_min > 0
  and desired_equity_ratio_min < 1;

update buyer_intent
set desired_equity_ratio_max = desired_equity_ratio_max * 100
where desired_equity_ratio_max is not null
  and desired_equity_ratio_max > 0
  and desired_equity_ratio_max < 1;
