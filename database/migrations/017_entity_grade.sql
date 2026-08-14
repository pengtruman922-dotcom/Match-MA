-- 标的级别与需求级别（phase A）：加列 + 回填 + 不变式约束，旧列保留。
--
-- 级别 A-E 取代「交易状态 / 推荐状态」成为推荐的唯一闸门：E 不进推荐，A-D 进。
-- 原状态列不删，降级成「E 的细分原因」（已售出/已停售、暂停推荐/结束推荐），
-- 因此两列必须严格双向绑定，见下方 CHECK。
--
-- 为什么不变式必须落在数据库而不是应用层：recommendation_status 的教训就是
-- 「一列答两个问题、只有一条窄路径会正确置位」，其余写入路径静默留在错误值上，
-- 2026-07-27 审计时有 8 个活跃标的因此长期从推荐里消失（见 005 的注释）。
-- 两列耦合比一列多义更容易漂，约束是唯一能保证不出现
-- 「grade='A' 但 lifecycle_status='sold'」的东西。
--
-- 方案与范围见《标的与需求级别改造施工单0814.md》。
-- phase B（删旧列）另开迁移，要等 Railway 全部服务跑上 phase A 代码之后。

-- ===== 一、加列 =====
--
-- 默认 C：新录入的项目没有明确级别时统一为 C。这个默认只在「实体创建」这一个
-- 点生效——解析路径一律不许写兜底默认值，否则重新解析会把人工设成 D 的标的
-- 打回 C。

alter table seller_target
  add column if not exists target_grade text not null default 'C';

alter table buyer_intent
  add column if not exists intent_grade text not null default 'C';

-- ===== 二、回填 =====
--
-- 必须在加 CHECK 之前：默认值 'C' 已经给所有存量行写上了 C，此刻已售出/已停售
-- 的标的与暂停/结束的需求都还是 C，先加约束会当场撞上不变式。

update seller_target
set target_grade = 'E',
    updated_at = now()
where deleted_at is null
  and lifecycle_status <> 'active'
  and target_grade <> 'E';

update buyer_intent
set intent_grade = 'E',
    updated_at = now()
where deleted_at is null
  and status <> 'active'
  and intent_grade <> 'E';

-- 软删除的行不参与业务，但 CHECK 约束是全表生效的，它们也得满足不变式。
update seller_target
set target_grade = 'E'
where deleted_at is not null
  and lifecycle_status <> 'active'
  and target_grade <> 'E';

update buyer_intent
set intent_grade = 'E'
where deleted_at is not null
  and status <> 'active'
  and intent_grade <> 'E';

-- ===== 三、约束 =====

alter table seller_target
  drop constraint if exists chk_seller_target_grade;

alter table seller_target
  add constraint chk_seller_target_grade
  check (target_grade in ('A', 'B', 'C', 'D', 'E'));

alter table seller_target
  drop constraint if exists chk_seller_target_grade_lifecycle;

alter table seller_target
  add constraint chk_seller_target_grade_lifecycle
  check ((target_grade = 'E') = (lifecycle_status <> 'active'));

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_grade;

alter table buyer_intent
  add constraint chk_buyer_intent_grade
  check (intent_grade in ('A', 'B', 'C', 'D', 'E'));

alter table buyer_intent
  drop constraint if exists chk_buyer_intent_grade_status;

alter table buyer_intent
  add constraint chk_buyer_intent_grade_status
  check ((intent_grade = 'E') = (status <> 'active'));

-- ===== 四、索引换到级别列 =====
--
-- 两个 scope 索引的第三段就是初筛闸门，闸门换列索引就得跟着换，否则列表与
-- 召回都退化成全表扫。名字保持不变（006 特意把 lifecycle 版重命名回这个
-- 历史名，别再改）。

drop index if exists idx_seller_target_scope;

create index idx_seller_target_scope
  on seller_target using btree (team_id, workspace_id, target_grade, information_status)
  where deleted_at is null;

drop index if exists idx_buyer_intent_scope;

create index idx_buyer_intent_scope
  on buyer_intent using btree (team_id, workspace_id, intent_grade)
  where deleted_at is null;
