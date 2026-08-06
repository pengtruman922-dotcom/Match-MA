-- 标的指标体系第一轮：问卷驱动的两个闭集 + 两个展示列，删一个伪枚举。
-- 施工范围与边界见《标的指标体系重构施工单0806.md》。本轮只建标的侧事实列，
-- 买家侧对手方与打分接线在下一轮——所以这四列落地后暂时是单侧的，是计划内状态。

alter table seller_target
  add column if not exists major_risk_flags_json jsonb not null default '[]'::jsonb,
  add column if not exists acceptable_transaction_structures_json jsonb not null default '[]'::jsonb,
  add column if not exists main_products_text text,
  add column if not exists stock_code text;

-- 元素级校验：数组里出现字典外的值，直接被 DB 拒。解析侧也会先丢弃非法取值
-- （common.py 的闭集归一化），这里是最后一道，防手动 PATCH 与调研 apply 绕过。
--
-- 用 jsonb 包含运算符 `<@` 而不是 `not exists (select ... jsonb_array_elements)`：
-- **PostgreSQL 的 check 约束里不允许出现子查询**（0A000: cannot use subquery in
-- check constraint），写了会在 preDeploy 迁移阶段直接炸掉整次部署。
-- `<@` 要求左侧每个元素都出现在右侧字典里，空数组恒为真；再配一个 jsonb_typeof
-- 是因为裸标量字符串也满足 `<@`（'"litigation"' <@ '["litigation"]'为真）。
--
-- major_risk_flags_json 的三种状态用同一个字段表达，不再加第二列：
--   []        未核查
--   ["none"]  已核查，无重大风险
--   [其他]    已核查，有对应风险
alter table seller_target
  drop constraint if exists chk_seller_target_major_risk_flags_json,
  drop constraint if exists chk_seller_target_acceptable_transaction_structures_json;

alter table seller_target
  add constraint chk_seller_target_major_risk_flags_json
  check (
    jsonb_typeof(major_risk_flags_json) = 'array'
    and major_risk_flags_json <@ '["litigation", "equity_frozen", "enforcement", "violation", "none"]'::jsonb
  ),
  add constraint chk_seller_target_acceptable_transaction_structures_json
  check (
    jsonb_typeof(acceptable_transaction_structures_json) = 'array'
    and acceptable_transaction_structures_json <@ '["equity_transfer", "capital_increase", "asset_purchase", "merger", "other"]'::jsonb
  );

-- 与 industry_pairs_json 同一模式：闭集多值列建 GIN，下一轮接线时 not_overlap /
-- overlap 直接能用，不必再补索引。
create index if not exists idx_seller_target_major_risk_flags
  on seller_target using gin (major_risk_flags_json jsonb_path_ops)
  where deleted_at is null;

create index if not exists idx_seller_target_transaction_structures
  on seller_target using gin (acceptable_transaction_structures_json jsonb_path_ops)
  where deleted_at is null;

-- 经营稳定性判死：4 值伪枚举，「稳定 / 不稳定」没有客观判据，同一份材料两次
-- 解析可以给出不同值；买家也不用这个词提要求（他们说「业绩别大起大落」）。
-- 无买家对手方，打分链路无读者。内容归 ops_quality 画像栏。
alter table seller_target
  drop constraint if exists seller_target_operation_stability_status_check;

alter table seller_target
  drop column if exists operation_stability_status;
