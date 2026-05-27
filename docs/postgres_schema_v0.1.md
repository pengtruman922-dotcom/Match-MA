# Match-MA PostgreSQL Schema 草案 v0.1

状态：DDL 讨论稿  
范围：根据已确认的数据模型、字段收敛、constraint 白名单、风险枚举、权限隔离和向量检索设计，输出一期 PostgreSQL schema 草案。本文不是最终迁移脚本，后续仍需根据实现框架、ORM、Alembic 迁移和实际开发进行调整。

---

## 1. 已确认的数据库实现原则

### 1.1 主键与基础字段

已确认：

- 核心表统一使用 UUID 主键。
- UUID 生成使用 PostgreSQL `gen_random_uuid()`。
- 启用 `pgcrypto` extension。
- 表名使用 snake_case，单数命名。

### 1.2 数据隔离

核心业务表统一包含：

```text
team_id
workspace_id
visibility
```

含义：

| 字段 | 含义 |
| --- | --- |
| `team_id` | 公司 / 租户 / 大组织 |
| `workspace_id` | 部门 / 项目组 / 数据空间 / 专项项目 |
| `visibility` | 可见性，默认 `workspace` |

`visibility` 取值：

```text
workspace / team / private
```

一期默认：

```text
visibility = workspace
```

### 1.3 删除与审计

核心业务表使用 soft delete：

```text
deleted_at
deleted_by
```

通用审计字段：

```text
created_at
created_by
updated_at
updated_by
```

事件类表可只保留 `created_at / created_by`。

### 1.4 枚举实现

已确认：

```text
小而稳定的枚举使用 text + check constraint。
长尾业务字典使用 tag_dictionary 表。
```

不优先使用 PostgreSQL enum，避免后期修改困难。

### 1.5 四值状态

已确认统一使用：

```text
yes / no / unknown / likely
```

适用字段：

- `is_for_sale`
- `can_control`
- `can_consolidate`
- `accepts_minority_investment`
- `requires_control`
- `requires_consolidation`

### 1.6 金额与比例

金额统一使用人民币元：

```text
numeric(20,2)
```

比例统一按百分数数值存储：

```text
58 表示 58%
29.9 表示 29.9%
```

比例字段建议：

```text
numeric(10,4)
```

### 1.7 向量检索

一期 embedding：

```text
模型：text-embedding-v4
维度：1024
```

向量只用于：

- 语义召回。
- 非标准表达兜底召回。
- 标签未完全归一时的候选补充。

不用于：

- 利润 / PE / 估值比较。
- 地区硬条件。
- 风险硬排除。
- 不感兴趣硬排除。
- 权限隔离。

---

## 2. Extensions

```sql
create extension if not exists pgcrypto;
create extension if not exists pg_trgm;
create extension if not exists vector;
```

说明：

- `pgcrypto` 用于 `gen_random_uuid()`。
- `pg_trgm` 用于名称查重、相似度匹配。
- `vector` 用于 pgvector。

---

## 3. 通用约束建议

### 3.1 visibility check

```sql
check (visibility in ('workspace', 'team', 'private'))
```

### 3.2 四值状态 check

```sql
check (field_name in ('yes', 'no', 'unknown', 'likely'))
```

### 3.3 review_status check

```sql
check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored'))
```

### 3.4 normalization_status check

```sql
check (normalization_status in ('auto_accepted', 'accepted', 'pending_normalization', 'rejected', 'raw_only'))
```

---

## 4. 基础权限表

一期可先简化用户与空间模型，但 schema 预留。

### 4.1 `team`

```sql
create table team (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
```

### 4.2 `workspace`

```sql
create table workspace (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  name text not null,
  workspace_type text not null default 'department' check (workspace_type in ('department', 'project', 'data_space', 'special_task', 'other')),
  status text not null default 'active' check (status in ('active', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_workspace_team on workspace(team_id, status);
```

### 4.3 `app_user`

```sql
create table app_user (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  default_workspace_id uuid references workspace(id),
  name text not null,
  email text,
  role text not null default 'consultant' check (role in ('consultant', 'manager', 'admin', 'developer')),
  status text not null default 'active' check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_app_user_team on app_user(team_id, status);
```

---

## 5. 卖方主体与标的

### 5.1 `seller_party`

```sql
create table seller_party (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  party_name text not null,
  legal_name text,
  aliases_json jsonb not null default '[]'::jsonb,
  unified_credit_code text,
  party_type text not null default 'company' check (party_type in ('company', 'group', 'individual', 'other')),

  region_province text,
  region_city text,
  address text,
  website text,
  profile_summary text,

  owner_user_id uuid references app_user(id),
  status text not null default 'active' check (status in ('active', 'archived', 'merged')),
  merged_into_id uuid references seller_party(id),
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create index idx_seller_party_scope on seller_party(team_id, workspace_id, status) where deleted_at is null;
create index idx_seller_party_owner on seller_party(owner_user_id) where deleted_at is null;
create index idx_seller_party_name_trgm on seller_party using gin (party_name gin_trgm_ops);
create index idx_seller_party_legal_name_trgm on seller_party using gin (legal_name gin_trgm_ops);
create index idx_seller_party_credit_code on seller_party(unified_credit_code) where unified_credit_code is not null and deleted_at is null;
```

### 5.2 `seller_target`

```sql
create table seller_target (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  target_name text not null,
  target_type text not null default 'company' check (target_type in ('company', 'equity_package', 'business_unit', 'asset_package', 'project', 'other')),
  seller_party_id uuid references seller_party(id),
  owner_user_id uuid references app_user(id),

  recommendation_status text not null default 'recommendable' check (recommendation_status in ('recommendable', 'not_recommendable')),
  information_status text not null default 'insufficient' check (information_status in ('normal', 'insufficient', 'pending_review', 'parsing', 'researching', 'parse_failed')),

  industry_primary text,
  industry_secondary text,

  registered_country text default '中国',
  registered_province text,
  registered_city text,
  headquarter_province text,
  headquarter_city text,
  operating_regions_json jsonb not null default '[]'::jsonb,
  production_regions_json jsonb not null default '[]'::jsonb,
  asset_regions_json jsonb not null default '[]'::jsonb,
  raw_region_text text,
  region_granularity text check (region_granularity in ('country', 'province', 'city', 'district', 'region_group', 'unknown')),

  listed_status text not null default 'unknown' check (listed_status in ('listed', 'unlisted', 'pre_ipo', 'unknown')),
  listing_board text check (listing_board in ('main_board', 'gem', 'star_market', 'bse', 'hkex', 'nasdaq', 'nyse', 'other')),
  market_cap_yuan numeric(20,2),

  current_revenue_yuan numeric(20,2),
  current_net_profit_yuan numeric(20,2),
  current_total_profit_yuan numeric(20,2),
  current_assets_yuan numeric(20,2),
  current_debt_ratio numeric(10,4),
  current_operating_cash_flow_yuan numeric(20,2),
  financial_period_label text,
  profitability_status text check (profitability_status in ('profitable', 'loss_making', 'break_even', 'unknown')),
  cash_flow_status text check (cash_flow_status in ('stable_positive', 'positive', 'negative', 'unstable', 'unknown')),
  operation_stability_status text check (operation_stability_status in ('stable', 'unstable', 'unknown', 'needs_review')),

  valuation_yuan numeric(20,2),
  asking_price_yuan numeric(20,2),
  pe_ratio numeric(10,4),
  pe_source_type text check (pe_source_type in ('user_input', 'document', 'calculated', 'research', 'unknown')),
  pe_calculation_basis_json jsonb not null default '{}'::jsonb,
  premium_rate numeric(10,4),

  is_for_sale text not null default 'unknown' check (is_for_sale in ('yes', 'no', 'unknown', 'likely')),
  can_control text not null default 'unknown' check (can_control in ('yes', 'no', 'unknown', 'likely')),
  can_consolidate text not null default 'unknown' check (can_consolidate in ('yes', 'no', 'unknown', 'likely')),
  accepts_minority_investment text not null default 'unknown' check (accepts_minority_investment in ('yes', 'no', 'unknown', 'likely')),
  transfer_ratio_min numeric(10,4),
  transfer_ratio_max numeric(10,4),
  transfer_ratio_text text,
  transfer_flexibility_type text check (transfer_flexibility_type in ('control_available', 'consolidation_available', 'minority_available', 'full_sale_available', 'flexible', 'specific_range', 'unknown')),
  control_path_options_json jsonb not null default '[]'::jsonb,
  consolidation_path_summary text,
  deal_paths_json jsonb not null default '[]'::jsonb,
  accepted_payment_methods_json jsonb not null default '[]'::jsonb,

  accepts_relocation text not null default 'unknown' check (accepts_relocation in ('yes', 'no', 'unknown', 'likely')),
  acceptable_relocation_regions_json jsonb not null default '[]'::jsonb,
  accepts_return_investment text not null default 'unknown' check (accepts_return_investment in ('yes', 'no', 'unknown', 'likely')),

  management_team_summary text,
  management_retention_possible text not null default 'unknown' check (management_retention_possible in ('yes', 'no', 'unknown', 'likely')),
  earnout_dependency_status text check (earnout_dependency_status in ('none', 'low', 'medium', 'high', 'unknown')),

  business_summary text,
  transaction_summary text,
  risk_summary text,
  gap_summary text,
  completeness_score numeric(5,2),

  last_business_update_at timestamptz,
  last_research_at timestamptz,
  last_attachment_parse_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id),

  check (transfer_ratio_min is null or transfer_ratio_min >= 0),
  check (transfer_ratio_max is null or transfer_ratio_max <= 100),
  check (transfer_ratio_min is null or transfer_ratio_max is null or transfer_ratio_min <= transfer_ratio_max)
);

create index idx_seller_target_scope on seller_target(team_id, workspace_id, recommendation_status, information_status) where deleted_at is null;
create index idx_seller_target_owner on seller_target(owner_user_id) where deleted_at is null;
create index idx_seller_target_party on seller_target(seller_party_id) where deleted_at is null;
create index idx_seller_target_name_trgm on seller_target using gin (target_name gin_trgm_ops);
create index idx_seller_target_industry on seller_target(team_id, industry_primary, industry_secondary) where deleted_at is null;
create index idx_seller_target_region on seller_target(team_id, headquarter_province, headquarter_city) where deleted_at is null;
create index idx_seller_target_finance on seller_target(team_id, current_net_profit_yuan, pe_ratio, valuation_yuan) where deleted_at is null;
create index idx_seller_target_deal on seller_target(team_id, can_control, can_consolidate, is_for_sale) where deleted_at is null;
```

### 5.3 `seller_target_financial`

```sql
create table seller_target_financial (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  seller_target_id uuid not null references seller_target(id),

  period_type text not null check (period_type in ('annual', 'quarterly', 'monthly', 'ttm', 'latest')),
  period_label text not null,
  period_start date,
  period_end date,

  revenue_yuan numeric(20,2),
  net_profit_yuan numeric(20,2),
  total_profit_yuan numeric(20,2),
  ebitda_yuan numeric(20,2),
  assets_yuan numeric(20,2),
  liabilities_yuan numeric(20,2),
  debt_ratio numeric(10,4),
  gross_margin numeric(10,4),
  operating_cash_flow_yuan numeric(20,2),

  audit_status text check (audit_status in ('audited', 'unaudited', 'reviewed', 'unknown')),
  accounting_standard text,
  source_type text,
  source_id uuid,
  evidence_id uuid,
  confidence numeric(5,4),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id)
);

create index idx_seller_financial_target on seller_target_financial(seller_target_id, period_type, period_label);
create index idx_seller_financial_profit on seller_target_financial(team_id, net_profit_yuan, revenue_yuan);
```

### 5.4 `seller_target_risk`

```sql
create table seller_target_risk (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  seller_target_id uuid not null references seller_target(id),

  risk_type text not null,
  risk_status text not null default 'unknown' check (risk_status in ('confirmed_present', 'suspected', 'not_found', 'confirmed_absent', 'unknown')),
  severity text not null default 'unknown' check (severity in ('low', 'medium', 'high', 'critical', 'unknown')),
  title text,
  description text,
  amount_yuan numeric(20,2),
  occurred_at date,
  resolved_at date,

  source_type text,
  source_id uuid,
  evidence_id uuid,
  confidence numeric(5,4),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id)
);

create index idx_seller_risk_target on seller_target_risk(seller_target_id);
create index idx_seller_risk_filter on seller_target_risk(team_id, risk_type, risk_status, severity);
```

---

## 6. 字典与标签

### 6.1 `tag_dictionary`

```sql
create table tag_dictionary (
  id uuid primary key default gen_random_uuid(),
  team_id uuid references team(id),
  workspace_id uuid references workspace(id),

  domain text not null,
  canonical_key text not null,
  display_name text not null,
  parent_key text,
  aliases_json jsonb not null default '[]'::jsonb,
  description text,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index uniq_tag_dictionary_scope_key on tag_dictionary(
  coalesce(team_id, '00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
  domain,
  canonical_key
);
create index idx_tag_dictionary_domain on tag_dictionary(domain, is_active);
create index idx_tag_dictionary_aliases on tag_dictionary using gin (aliases_json);
```

说明：

- `team_id / workspace_id` 允许为空，用于全局默认字典。
- PostgreSQL 普通 `unique(team_id, workspace_id, domain, canonical_key)` 无法阻止多条 `null` scope 的重复值，因此一期使用 `coalesce` 表达式唯一索引。
- 字典不追求一次性全覆盖。LLM 先抽取原文，服务端用字典别名/相似度召回 Top-N，再让 LLM 或规则做小候选集归一化；低置信度进入 `pending_normalization`。

### 6.2 `region_alias_config`

```sql
create table region_alias_config (
  id uuid primary key default gen_random_uuid(),
  team_id uuid references team(id),
  workspace_id uuid references workspace(id),

  alias_text text not null,
  expanded_regions_json jsonb not null default '[]'::jsonb,
  region_level text not null default 'province' check (region_level in ('country', 'province', 'city', 'district', 'mixed', 'other')),
  description text,
  is_active boolean not null default true,
  sort_order integer not null default 0,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index uniq_region_alias_scope_alias on region_alias_config(
  coalesce(team_id, '00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
  alias_text
);
create index idx_region_alias_active on region_alias_config(is_active);
```

用途：

- 支持 LLM 和服务端把买家意向中的“长三角、江浙沪、沿海发达地区”等业务区域表达展开为结构化候选区域。
- 注意：这是买家意向解析和规则判断辅助配置，不应把 `seller_target` 的事实字段改写成“是否落在偏好区域”。
- 如果标的来源只写“长三角”，标的侧保留 `raw_region_text` 和 `region_granularity = region_group`，不强行伪造精确省市。

### 6.3 `seller_target_tag`

```sql
create table seller_target_tag (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  seller_target_id uuid not null references seller_target(id),

  domain text not null,
  canonical_key text,
  display_name text,
  raw_text text not null,
  source_type text,
  source_id uuid,
  evidence_id uuid,
  confidence numeric(5,4),
  normalization_status text not null default 'raw_only' check (normalization_status in ('auto_accepted', 'accepted', 'pending_normalization', 'rejected', 'raw_only')),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id)
);

create index idx_seller_tag_target on seller_target_tag(seller_target_id);
create index idx_seller_tag_lookup on seller_target_tag(team_id, domain, canonical_key) where canonical_key is not null;
create index idx_seller_tag_raw_trgm on seller_target_tag using gin (raw_text gin_trgm_ops);
```

---

## 7. 买家主体与买家意向

### 7.1 `buyer_party`

```sql
create table buyer_party (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  buyer_name text not null,
  legal_name text,
  aliases_json jsonb not null default '[]'::jsonb,
  buyer_type text check (buyer_type in ('industrial_buyer', 'listed_company', 'state_owned_platform', 'pe_fund', 'financial_investor', 'government_platform', 'other')),
  group_name text,
  listed_status text not null default 'unknown' check (listed_status in ('listed', 'unlisted', 'pre_ipo', 'unknown')),
  region_country text default '中国',
  region_province text,
  region_city text,
  main_business text,
  capital_strength_summary text,
  profile_summary text,
  long_term_preference_json jsonb not null default '{}'::jsonb,

  owner_user_id uuid references app_user(id),
  status text not null default 'active' check (status in ('active', 'archived', 'merged')),
  merged_into_id uuid references buyer_party(id),
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create index idx_buyer_party_scope on buyer_party(team_id, workspace_id, status) where deleted_at is null;
create index idx_buyer_party_name_trgm on buyer_party using gin (buyer_name gin_trgm_ops);
create index idx_buyer_party_legal_trgm on buyer_party using gin (legal_name gin_trgm_ops);
```

### 7.2 `buyer_intent`

```sql
create table buyer_intent (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  buyer_party_id uuid references buyer_party(id),
  owner_user_id uuid references app_user(id),
  is_temporary boolean not null default false,

  intent_name text not null,
  status text not null default 'active' check (status in ('active', 'paused')),
  pause_reason text,
  contact_name text,
  contact_info_json jsonb not null default '{}'::jsonb,

  raw_requirement_text text,
  intent_summary text,
  parsed_requirement_json jsonb not null default '{}'::jsonb,

  industry_primary text,
  industry_secondary text,
  region_scope_summary text,
  region_constraints_json jsonb not null default '[]'::jsonb,

  min_revenue_yuan numeric(20,2),
  min_net_profit_yuan numeric(20,2),
  min_total_profit_yuan numeric(20,2),
  max_pe numeric(10,4),
  max_valuation_yuan numeric(20,2),
  market_cap_range_summary text,

  requires_control text not null default 'unknown' check (requires_control in ('yes', 'no', 'unknown', 'likely')),
  requires_consolidation text not null default 'unknown' check (requires_consolidation in ('yes', 'no', 'unknown', 'likely')),
  accepts_minority_investment text not null default 'unknown' check (accepts_minority_investment in ('yes', 'no', 'unknown', 'likely')),
  desired_equity_ratio_min numeric(10,4),
  desired_equity_ratio_max numeric(10,4),
  equity_ratio_summary text,
  equity_requirement_type text check (equity_requirement_type in ('control_required', 'consolidation_required', 'minority_acceptable', 'minority_only', 'flexible', 'specific_range', 'unknown')),
  acceptable_control_paths_json jsonb not null default '[]'::jsonb,

  preferred_listed_status text check (preferred_listed_status in ('listed', 'unlisted', 'pre_ipo', 'any', 'unknown')),
  transaction_type text,
  negative_summary text,
  priority_summary text,
  preference_summary text,
  unknown_summary text,

  last_recommendation_at timestamptz,
  last_business_update_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id),

  check (desired_equity_ratio_min is null or desired_equity_ratio_min >= 0),
  check (desired_equity_ratio_max is null or desired_equity_ratio_max <= 100),
  check (desired_equity_ratio_min is null or desired_equity_ratio_max is null or desired_equity_ratio_min <= desired_equity_ratio_max)
);

create index idx_buyer_intent_scope on buyer_intent(team_id, workspace_id, status) where deleted_at is null;
create index idx_buyer_intent_party on buyer_intent(buyer_party_id) where deleted_at is null;
create index idx_buyer_intent_owner on buyer_intent(owner_user_id) where deleted_at is null;
create index idx_buyer_intent_industry on buyer_intent(team_id, industry_primary, industry_secondary) where deleted_at is null;
create index idx_buyer_intent_text_trgm on buyer_intent using gin (intent_name gin_trgm_ops);
```

### 7.3 `buyer_intent_constraint`

```sql
create table buyer_intent_constraint (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  buyer_intent_id uuid not null references buyer_intent(id),

  field text not null,
  operator text not null check (operator in ('=', '!=', 'in', 'preferred_in', 'exclude', '>=', '<=', 'between', 'exists', 'not_exists')),
  value_json jsonb not null,
  unit text,
  scope text,
  normalized_key text,
  constraint_type text not null default 'preference' check (constraint_type in ('hard', 'preference', 'unknown')),
  unknown_policy text not null default 'allow_but_flag_gap' check (unknown_policy in ('allow_but_flag_gap', 'allow_but_deprioritize', 'exclude', 'ask_user')),
  weight numeric(8,4),
  raw_text text,

  source_type text,
  source_id uuid,
  confidence numeric(5,4),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),

  check (field in (
    'target_type', 'listed_status', 'listing_board', 'market_cap_yuan',
    'industry', 'sector', 'product', 'certification',
    'operating_region', 'headquarter_region', 'registered_region', 'asset_region', 'relocation', 'return_investment',
    'revenue_yuan', 'net_profit_yuan', 'total_profit_yuan', 'assets_yuan', 'debt_ratio', 'operating_cash_flow_yuan', 'profitability_status',
    'valuation_yuan', 'asking_price_yuan', 'pe_ratio', 'premium_rate',
    'can_control', 'can_consolidate', 'equity_ratio', 'deal_path', 'payment_method', 'minority_investment', 'control_path',
    'risk', 'audit_status', 'st_or_delisting_risk', 'operation_stability',
    'customer_type', 'customer_quality', 'technology_barrier', 'export_capability', 'production_capacity', 'team_stability', 'management_retention', 'earnout_dependency', 'synergy', 'landing_value', 'urgency'
  ))
);

create index idx_buyer_constraint_intent on buyer_intent_constraint(buyer_intent_id);
create index idx_buyer_constraint_field on buyer_intent_constraint(team_id, field, constraint_type);
create index idx_buyer_constraint_value on buyer_intent_constraint using gin (value_json);
```

### 7.4 `buyer_intent_target_exclusion`

```sql
create table buyer_intent_target_exclusion (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  buyer_intent_id uuid not null references buyer_intent(id),
  buyer_party_id uuid references buyer_party(id),
  seller_target_id uuid not null references seller_target(id),

  reason text,
  source_relation_id uuid,
  source_update_id uuid,
  source_event_id uuid,
  active boolean not null default true,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  canceled_by uuid references app_user(id),
  canceled_at timestamptz
);

create unique index uniq_active_intent_target_exclusion on buyer_intent_target_exclusion(team_id, buyer_intent_id, seller_target_id) where active = true and canceled_at is null;
create index idx_exclusion_target on buyer_intent_target_exclusion(seller_target_id) where active = true and canceled_at is null;
```

---

## 8. 买家-标的关系与事件

### 8.1 `buyer_seller_relation`

```sql
create table buyer_seller_relation (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  buyer_intent_id uuid not null references buyer_intent(id),
  buyer_party_id uuid references buyer_party(id),
  seller_target_id uuid not null references seller_target(id),

  status text not null default 'recommended' check (status in ('recommended', 'interested', 'in_discussion', 'due_diligence', 'agreement', 'deal_closed', 'not_interested', 'paused', 'lost')),
  status_reason text,
  owner_user_id uuid references app_user(id),

  first_recommended_at timestamptz,
  last_contact_at timestamptz,
  last_event_at timestamptz,
  last_event_summary text,

  created_from_session_id uuid,
  created_from_report_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id),
  updated_at timestamptz not null default now(),
  updated_by uuid references app_user(id),
  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create unique index uniq_buyer_seller_relation_active on buyer_seller_relation(team_id, buyer_intent_id, seller_target_id) where deleted_at is null;
create index idx_relation_target on buyer_seller_relation(seller_target_id, status) where deleted_at is null;
create index idx_relation_intent on buyer_seller_relation(buyer_intent_id, status) where deleted_at is null;
create index idx_relation_recent on buyer_seller_relation(team_id, last_event_at desc) where deleted_at is null;
```

### 8.2 `relation_event`

```sql
create table relation_event (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  relation_id uuid not null references buyer_seller_relation(id),
  buyer_intent_id uuid not null references buyer_intent(id),
  buyer_party_id uuid references buyer_party(id),
  seller_target_id uuid not null references seller_target(id),

  event_type text not null check (event_type in ('recommended', 'buyer_interested', 'buyer_not_interested', 'meeting', 'call', 'material_sent', 'due_diligence_started', 'agreement_discussion', 'deal_closed', 'paused', 'internal_note', 'other')),
  event_time timestamptz not null default now(),
  title text,
  content text,
  next_step text,

  source_type text,
  source_id uuid,
  evidence_id uuid,
  metadata_json jsonb not null default '{}'::jsonb,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now()
);

create index idx_relation_event_relation on relation_event(relation_id, event_time desc);
create index idx_relation_event_target on relation_event(seller_target_id, event_time desc);
create index idx_relation_event_intent on relation_event(buyer_intent_id, event_time desc);
```

---

## 9. 推荐会话、消息、采用结果和报告

### 9.1 `recommendation_session`

```sql
create table recommendation_session (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  mode text not null check (mode in ('buyer_to_target', 'target_to_buyer')),
  buyer_intent_id uuid references buyer_intent(id),
  buyer_party_id uuid references buyer_party(id),
  seller_target_id uuid references seller_target(id),
  anonymous_input_snapshot text,

  initial_condition_snapshot_json jsonb not null default '{}'::jsonb,
  latest_condition_snapshot_json jsonb not null default '{}'::jsonb,
  status text not null default 'active' check (status in ('active', 'archived', 'completed')),
  selected_count integer not null default 0,
  report_count integer not null default 0,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb
);

create index idx_recommendation_session_scope on recommendation_session(team_id, workspace_id, mode, status);
create index idx_recommendation_session_buyer on recommendation_session(buyer_intent_id, created_at desc);
create index idx_recommendation_session_target on recommendation_session(seller_target_id, created_at desc);
```

### 9.2 `recommendation_message`

```sql
create table recommendation_message (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  session_id uuid not null references recommendation_session(id),

  role text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content text not null,
  content_type text not null default 'text' check (content_type in ('text', 'json', 'markdown')),
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id)
);

create index idx_recommendation_message_session on recommendation_message(session_id, created_at);
create index idx_recommendation_message_metadata on recommendation_message using gin (metadata_json);
```

说明：`metadata_json` 可以保存候选卡片快照，但不代表正式结构化推荐结果。

### 9.3 `recommendation_selected_item`

```sql
create table recommendation_selected_item (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  session_id uuid not null references recommendation_session(id),
  mode text not null check (mode in ('buyer_to_target', 'target_to_buyer')),

  seller_target_id uuid references seller_target(id),
  buyer_intent_id uuid references buyer_intent(id),
  buyer_party_id uuid references buyer_party(id),

  selected_from_message_id uuid references recommendation_message(id),
  rank_at_selection integer,
  recommendation_level text check (recommendation_level in ('strong', 'recommended', 'possible', 'weak')),

  match_summary text,
  risk_summary text,
  gap_summary text,
  reason_snapshot text,
  evidence_snapshot_json jsonb not null default '{}'::jsonb,

  selected_by uuid references app_user(id),
  selected_at timestamptz not null default now(),
  canceled_by uuid references app_user(id),
  canceled_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb
);

create index idx_selected_item_session on recommendation_selected_item(session_id, selected_at desc);
create index idx_selected_item_target on recommendation_selected_item(seller_target_id) where canceled_at is null;
create index idx_selected_item_intent on recommendation_selected_item(buyer_intent_id) where canceled_at is null;
```

### 9.4 `recommendation_report`

```sql
create table recommendation_report (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  session_id uuid not null references recommendation_session(id),

  report_type text not null check (report_type in ('buyer_facing_target_report', 'internal_buyer_list')),
  selected_item_ids_json jsonb not null default '[]'::jsonb,
  title text,
  markdown_content text,
  file_path text,
  file_format text check (file_format in ('markdown', 'docx', 'pdf')),
  status text not null default 'generated' check (status in ('generating', 'generated', 'failed', 'archived')),
  generated_by_model text,
  prompt_version text,

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  metadata_json jsonb not null default '{}'::jsonb
);

create index idx_recommendation_report_session on recommendation_report(session_id, created_at desc);
```

---

## 10. 附件、解析与证据

### 10.1 `attachment`

```sql
create table attachment (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  file_name text not null,
  file_type text,
  mime_type text,
  file_size bigint,
  storage_path text not null,
  uploaded_by uuid references app_user(id),
  uploaded_at timestamptz not null default now(),
  parse_status text not null default 'pending' check (parse_status in ('pending', 'parsing', 'parsed', 'failed', 'skipped')),
  metadata_json jsonb not null default '{}'::jsonb,

  deleted_at timestamptz,
  deleted_by uuid references app_user(id)
);

create index idx_attachment_scope on attachment(team_id, workspace_id, parse_status) where deleted_at is null;
```

### 10.2 `attachment_link`

```sql
create table attachment_link (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  attachment_id uuid not null references attachment(id),

  entity_type text not null,
  entity_id uuid not null,
  link_type text,

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id)
);

create index idx_attachment_link_attachment on attachment_link(attachment_id);
create index idx_attachment_link_entity on attachment_link(entity_type, entity_id);
```

### 10.3 `parsed_document`

```sql
create table parsed_document (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  attachment_id uuid not null references attachment(id),

  parser_name text,
  parser_version text,
  parse_status text not null default 'pending' check (parse_status in ('pending', 'parsing', 'parsed', 'failed', 'skipped')),
  text_path text,
  markdown_path text,
  manifest_path text,
  page_count integer,
  token_count integer,
  error_message text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_parsed_document_attachment on parsed_document(attachment_id);
```

### 10.4 `evidence_span`

```sql
create table evidence_span (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  source_type text not null,
  source_id uuid,
  attachment_id uuid references attachment(id),
  parsed_document_id uuid references parsed_document(id),
  page_no integer,
  slide_no integer,
  sheet_name text,
  cell_range text,
  text_excerpt text,
  char_start integer,
  char_end integer,

  created_at timestamptz not null default now()
);

create index idx_evidence_source on evidence_span(source_type, source_id);
create index idx_evidence_attachment on evidence_span(attachment_id);
```

### 10.5 `field_value_source`

```sql
create table field_value_source (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  entity_type text not null,
  entity_id uuid not null,
  field_path text not null,
  value_snapshot_json jsonb not null default '{}'::jsonb,
  source_type text,
  source_id uuid,
  evidence_id uuid references evidence_span(id),
  source_label text,
  confidence numeric(5,4),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),

  created_at timestamptz not null default now(),
  created_by uuid references app_user(id)
);

create index idx_field_source_entity on field_value_source(entity_type, entity_id, field_path);
create index idx_field_source_review on field_value_source(team_id, review_status);
```

---

## 11. 统一业务更新

### 11.1 `business_update`

```sql
create table business_update (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  visibility text not null default 'workspace' check (visibility in ('workspace', 'team', 'private')),

  raw_text text,
  input_type text not null default 'text' check (input_type in ('text', 'screenshot', 'attachment', 'mixed')),
  processing_status text not null default 'pending' check (processing_status in ('pending', 'processing', 'parsed', 'partially_applied', 'applied', 'failed')),

  bound_seller_target_ids_json jsonb not null default '[]'::jsonb,
  bound_buyer_party_ids_json jsonb not null default '[]'::jsonb,
  bound_buyer_intent_ids_json jsonb not null default '[]'::jsonb,
  bound_recommendation_session_id uuid references recommendation_session(id),

  created_by uuid references app_user(id),
  created_at timestamptz not null default now(),
  metadata_json jsonb not null default '{}'::jsonb
);

create index idx_business_update_scope on business_update(team_id, workspace_id, processing_status, created_at desc);
create index idx_business_update_metadata on business_update using gin (metadata_json);
```

### 11.2 `extracted_action`

```sql
create table extracted_action (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  business_update_id uuid not null references business_update(id),

  action_type text not null check (action_type in ('seller_fact_update', 'seller_event', 'buyer_seller_relation_update', 'buyer_intent_target_exclusion', 'buyer_intent_suggestion', 'buyer_level_blacklist_suggestion', 'internal_note', 'unresolved_item')),
  target_entity_type text,
  target_entity_id uuid,
  proposed_changes_json jsonb not null default '{}'::jsonb,
  raw_evidence_text text,
  evidence_id uuid references evidence_span(id),
  confidence numeric(5,4),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'accepted', 'rejected', 'auto_accepted', 'ignored')),
  reviewed_by uuid references app_user(id),
  reviewed_at timestamptz,
  applied_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb,

  created_at timestamptz not null default now()
);

create index idx_extracted_action_update on extracted_action(business_update_id);
create index idx_extracted_action_review on extracted_action(team_id, workspace_id, review_status);
create index idx_extracted_action_target on extracted_action(target_entity_type, target_entity_id);
```

### 11.3 `action_application_log`

```sql
create table action_application_log (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),

  extracted_action_id uuid references extracted_action(id),
  business_update_id uuid references business_update(id),
  entity_type text not null,
  entity_id uuid not null,
  field_path text not null,
  old_value_json jsonb,
  new_value_json jsonb,
  source_type text,
  source_id uuid,
  evidence_id uuid references evidence_span(id),
  applied_by uuid references app_user(id),
  applied_at timestamptz not null default now(),
  edited_before_apply boolean not null default false,
  can_rollback boolean not null default true,
  rollback_at timestamptz,
  metadata_json jsonb not null default '{}'::jsonb
);

create index idx_action_log_entity on action_application_log(entity_type, entity_id, applied_at desc);
create index idx_action_log_update on action_application_log(business_update_id);
create index idx_action_log_action on action_application_log(extracted_action_id);
```

---

## 12. Search Doc 与向量检索

### 12.1 `seller_target_search_doc`

```sql
create table seller_target_search_doc (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  seller_target_id uuid not null references seller_target(id),

  doc_type text not null default 'profile' check (doc_type in ('profile', 'business', 'transaction', 'risk', 'attachment_summary', 'research_summary')),
  title text,
  structured_summary text,
  tag_text text,
  business_text text,
  financial_text text,
  transaction_text text,
  risk_text text,
  gap_text text,
  full_text text,

  embedding vector(1024),
  embedding_model text default 'text-embedding-v4',
  embedding_dim integer default 1024,
  source_version integer not null default 1,
  updated_at timestamptz not null default now(),

  unique(seller_target_id, doc_type)
);

create index idx_seller_search_target on seller_target_search_doc(seller_target_id);
create index idx_seller_search_full_text_trgm on seller_target_search_doc using gin (full_text gin_trgm_ops);
create index idx_seller_search_embedding on seller_target_search_doc using ivfflat (embedding vector_cosine_ops) with (lists = 100);
```

### 12.2 `buyer_intent_search_doc`

```sql
create table buyer_intent_search_doc (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references team(id),
  workspace_id uuid not null references workspace(id),
  buyer_intent_id uuid not null references buyer_intent(id),

  title text,
  requirement_summary text,
  constraint_text text,
  preference_text text,
  negative_text text,
  history_text text,
  full_text text,

  embedding vector(1024),
  embedding_model text default 'text-embedding-v4',
  embedding_dim integer default 1024,
  source_version integer not null default 1,
  updated_at timestamptz not null default now(),

  unique(buyer_intent_id)
);

create index idx_buyer_search_intent on buyer_intent_search_doc(buyer_intent_id);
create index idx_buyer_search_full_text_trgm on buyer_intent_search_doc using gin (full_text gin_trgm_ops);
create index idx_buyer_search_embedding on buyer_intent_search_doc using ivfflat (embedding vector_cosine_ops) with (lists = 100);
```

说明：如果初期数据量较小，可以先不建 ivfflat 索引，直接精确向量检索；等数据量增长后再创建索引。

---

## 13. 后续迁移实现注意事项

### 13.1 多态引用

部分表中 `source_id / entity_id` 是多态引用，无法使用强外键。

例如：

```text
field_value_source.entity_type + entity_id
action_application_log.entity_type + entity_id
attachment_link.entity_type + entity_id
```

后续应由应用层校验。

### 13.2 updated_at 自动更新

DDL 草案未写 trigger。

实际实现时建议增加统一 trigger：

```sql
set updated_at = now()
```

### 13.3 RLS

后续如果需要数据库级权限隔离，可基于：

```text
team_id
workspace_id
visibility
```

实现 PostgreSQL Row Level Security。

一期可先由应用层控制。

### 13.4 Alembic 迁移建议

建议迁移顺序：

1. extensions。
2. team / workspace / app_user。
3. seller / buyer 主体表。
4. seller_target / buyer_intent。
5. tag / risk / financial / constraint / region alias config。
6. relation / recommendation。
7. attachment / evidence / business_update。
8. search_doc / vector index。

---

## 14. 待继续确认

1. 是否将 `seller_target` P1 字段进一步拆出，减少主表宽度。
2. `industry_primary / industry_secondary` 一期先保留 text，同时用 `tag_dictionary` 辅助归一化；后续是否改成强外键字典。
3. `risk_type` 一期保持开放 text，并 seed P0 风险字典；后续是否增加团队自定义风险维护功能。
4. vector index 是否一期创建，还是等数据量增长后再建。
5. `team / workspace / app_user` 是否一期就实现真实权限，还是先 seed 默认值。
6. 是否需要把 schema 进一步拆成 Alembic migration 文件。
