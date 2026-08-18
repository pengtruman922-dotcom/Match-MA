# 阶段一施工单：初筛 skill（SQL 硬筛）

> 2026-08-17。方案见 `平台优化方案/推荐功能升级设计框架0805.md`，**动工前必读第二、四、七点五节**。
> 本阶段不依赖指标体系那条线，可立即开工。

## 全局分期（本单是第一阶段）

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **一** | **初筛 skill：schema 生成器 + SQL 生成 + 返回结构** | 无，可立即开工 |
| 二 | 需求解析节点：复活 `recommendation_query_parser`，改输出 schema | 无，可与一并行 |
| 三 | 深评节点：分档改排序、定性逐条判定、不分片 | 一（候选结构） |
| 四 | 主 Agent 编排 + 提示词 v0.2.0 + 追问芯片 | 一、二、三 |
| 五 | 拆除旧打分链路（`_score_target_against_intent` 等） | 指标体系线的结论 |

---

## 一、目标与边界

### 做什么

把 `search_targets` 从「全表扫描 + 乐观打分 + 只排除硬冲突」改造成**纯 SQL 硬筛**：

- 条件从**注册表生成的 JSON Schema** 下发给模型，模型填不出集合外的值
- 每次调用是**一组 AND 条件**，全部硬筛，**缺失即出局**
- 返回**逐条件的淘汰拆分**，让 agent 知道该放宽哪一条
- 结果按 **A-D 级别 → 更新时间** 排序后取前 20

### 不做什么（越界即返工）

- **不做 OR**。多方案由 agent 拆成多次调用，skill 永远只做 AND。
- **不认软硬**。schema 里没有 `mode: hard|soft` 参数；"倾向于"由 agent 决定这次调用带不带这个条件。
- **不做标记列**。曾设计过"软条件变 select 列 + 命中数排序"，**已废弃**，不要实现。
- **不打分**。硬筛后所有幸存者在条件上等价，没有分数概念。
- **不动 `_candidate_targets_for_intent`**。旧打分链路在阶段五整体拆除，本阶段不要顺手改。
- **不做权限过滤**。业务方已确认本轮不做 owner_scope。

---

## 二、交付物

| 文件 | 内容 |
|---|---|
| `backend/app/services/screening_schema.py`（新） | 从注册表生成 JSON Schema |
| `backend/app/services/screening_sql.py`（新） | 八种算子 → SQL 片段；一次扫描算淘汰拆分 |
| `backend/app/services/recommendation_agent_tools.py` | `SEARCH_TARGETS_TOOL` 改用生成的 schema；`_search_targets` 改调新实现 |
| `tests/fixtures/screening_targets_snapshot.json`（新） | 71 条生产标的快照，验收基准 |
| `tests/test_screening_sql.py`（新） | 算子级单测 + 快照级端到端断言 |
| `tests/test_screening_schema.py`（新） | schema 生成的结构与闭集断言 |

---

## 三、设计

### 3.1 Schema 生成器

从 `indicators_for("buyer_intent")` 取 `screening=True` 的字段（当前 26 个），**剔除两个**：

- `min_net_margin`——标的侧无净利率列，靠 `净利/营收` 现算，除零与口径都不干净
- `max_ps`——分子声明为 `market_cap_yuan`，非上市标的没有市值，条件对主体人群恒失效

剩余 24 个按 `kind` 映射成 JSON Schema property：

| kind | 生成 |
|---|---|
| `yuan` | `{"type":"number","description":"<label>，单位元。2000 万写 20000000"}` |
| `ratio` | `{"type":"number","description":"<label>，0-1 小数"}` |
| `enum` | `{"type":"string","enum":[<enum_options 的码值>]}` |
| `json` + enum_options | `{"type":"array","items":{"type":"string","enum":[...]}}` |
| 行业类（`industries_json` / `industry_l2_json` / `excluded_industries_json`） | `enum` **运行时**从 `industry_taxonomy` 注入（L1 闭集当前 15 项） |
| `region_constraints_json` | 对象数组，`{province, city, district}` 三个可选字符串 |

**`requirement_capability` 的五个字段统一简化成布尔**。买家侧值域现在有两套
（`requires_control` 是 `yes/no/unknown/likely`，`requires_relocation` 是 `required/preferred/not_required/unknown`），
skill 不关心强度——强度由 agent 决定带不带这个条件。schema 里一律出 `{"type":"boolean"}`，
语义为「要求标的具备该能力」。

description 必须写清单位与方向，这是模型填对值的唯一依据。

### 3.2 SQL 生成：八种算子

**缺失即出局，所以模板不带 `is null or`。**

| 算子 | SQL 片段 |
|---|---|
| `gte` | `t.<col> >= :v` |
| `lte` | `t.<col> <= :v` |
| `in` | `t.<col> = any(:vals)` |
| `eq` | `t.<col> = :v` |
| `overlap`(l1) | `exists(select 1 from jsonb_array_elements(t.industry_pairs_json) p where p->>'l1' = any(:vals))` |
| `overlap`(l2) | 同上，取 `p->>'l2'` |
| `not_overlap` | `not exists(select 1 from jsonb_array_elements(t.industry_pairs_json) p where p->>'l1' = any(:vals) or p->>'l2' = any(:vals))` |
| `region_any` | 每个 constraint 展开成 `(province=:p and (city is null or city=:c) and (district is null or district=:d))`，多个之间 OR |
| `requirement_capability` | `t.<col> in ('yes','likely')` |

#### ⚠️ 最容易踩的坑：`unknown` 不是 null

`can_control` / `can_consolidate` / `accepts_relocation` / `accepts_return_investment` /
`management_retention_possible` / `listed_status` / `is_for_sale` 等列在 DDL 里是
**`not null default 'unknown'`**。`col is null` **永远判不到它们**。

**判定「字段缺失」时，`unknown` 必须与 `null` 等价。** 所有带 unknown 档的枚举都适用。
定义一个 `is_missing(col)` 辅助函数集中处理，不要在每个算子里各写一遍。

`profitability_status` / `cash_flow_status` 是可空列且枚举里也有 `unknown`，两种都要判。

#### 排除条件是粘性的

`excluded_industries_json` 每次调用都必须带上，不参与放宽。这一条在 skill 层强制，
不依赖 agent 自觉。

### 3.3 准入闸门与排序

```sql
where t.team_id = :team_id and t.workspace_id = :workspace_id
  and t.deleted_at is null
  and t.target_grade <> 'E'          -- 唯一闸门，永远生效，不由买家指定
  and <条件们 AND 连接>
order by t.target_grade asc,          -- 'A'<'B'<'C'<'D' 字典序即优先级
         t.updated_at desc
limit :limit                          -- ≤ 20
```

**先排完整个命中集再截前 20，不是先截再排。**

> `recommendation_flow.py:1254` 的注释「A-D 之间不影响召回与排序」描述的是**正式推荐链路**——
> 那条路有匹配分数，级别不该干扰分数。初筛 skill 是另一条路：硬筛后所有幸存者等价，
> A-D 就是排序键。两条路规则不同是设计使然，请在新代码里写清楚这句话。

### 3.4 `excluded_by_condition`：一次扫描算完

这是本阶段**最重要也最容易做错**的部分。agent 能不能正确放宽，全靠它。

语义是 **marginal**（"去掉这一条能多召回几家"），不是 independent（"这一条单独筛掉几家"）。
后者会重复计数，对放宽决策没有指导意义。

用 `count(*) filter` 一次扫描算出全部，**不要跑 N 次查询**：

```sql
select
  count(*) filter (where c1 and c2 and c3)                          as matched,
  -- 对每个条件 ci：去掉它之后的命中数，以及它筛掉的那批里有多少是"字段缺失"
  count(*) filter (where c2 and c3)                                 as without_c1,
  count(*) filter (where c2 and c3 and <c1字段缺失>)                 as c1_missing,
  count(*) filter (where c2 and c3 and not <c1字段缺失> and not c1)  as c1_fail,
  ...
from seller_target t
where <闸门条件>
```

返回时组装成：

```json
"excluded_by_condition": {
  "max_debt_ratio": {"总计": 6, "字段为空": 5, "确实不达标": 1, "去掉后命中": 6}
}
```

三个数必须满足 `字段为空 + 确实不达标 = 总计`，测试要断言这个恒等式。

### 3.5 返回结构

```json
{
  "conditions": {"industries_json": ["制造与工业"], "min_net_profit_yuan": 10000000},
  "matched": 16,
  "returned_count": 16,
  "excluded_by_condition": { ... },
  "returned": [ /* ≤20 条极简摘要 */ ]
}
```

**单条摘要保持极简**（约 80 字符）：`id`、`name`、`grade`、行业、地区，
以及本次条件涉及的字段值。**不要**塞画像正文、业务摘要、风险摘要——
主 Agent 不做评估，完整信息在阶段三的深评里一次性给。

`matched > returned_count` 时，在返回里明确写一句
「另有 N 家未返回，请收窄条件或使用 offset」——**不要做字符截断**，
截断一个 JSON 只会得到半个 JSON，模型解析失败还不知道为什么。

### 3.6 参数与预算

| 参数 | 说明 |
|---|---|
| `conditions` | 一组 AND 条件，字段限定在生成的 schema 内 |
| `limit` | 默认 20，上限 20 |
| `offset` | 同条件翻页 |
| `count_only` | 只回计数与淘汰拆分，不回明细。真正的 `count(*)`，成本可忽略 |
| `note` | 一句话说明本次想验证什么，展示给用户 |

**调用次数与去重不在本阶段实现**（属阶段四 agent 编排）。但请预留：
**去重只能发生在汇总环节，绝不能在查询时排除已返回的 id**——
那会让第二次查询看不到第一次已返回的优质标的，制造「这个条件下最好的只有 B 级」的假象。

---

## 四、验收用例

基准数据：**2026-08-17 生产快照，71 条标的，其中 E 级 2 条，有效 69 条**。
快照落进 `tests/fixtures/screening_targets_snapshot.json`，
测试灌进真实 Postgres（CI 已有 pgvector 服务）后跑，**不要打生产**。

| # | 条件 | 期望 `matched` | 验什么 |
|---:|---|---:|---|
| 1 | 无条件 | **69** | E 级闸门（总 71，E 级 2） |
| 2 | `industries_json=["制造与工业"]` | **21** | `overlap` 算子 |
| 3 | `industries_json=["医药与健康"]` | **13** | 同上 |
| 4 | `region_constraints_json=[{province:"江苏省"}]` | **20** | `region_any` |
| 5 | `min_net_profit_yuan=10000000` | **48** | `gte` + 缺失出局（13 家无净利数据） |
| 6 | `min_net_profit_yuan=30000000` | **28** | 阈值敏感 |
| 7 | 制造与工业 **+** 江苏省 | **6** | 多条件 AND |
| 8 | 制造与工业 **+** 净利≥1000万 | **16** | 多条件 AND |
| 9 | 制造与工业 + 江苏省 + 净利≥1000万 | **6** | 三条件 |
| 10 | **上一条再加 `max_debt_ratio=0.6`** | **0** | 见下，核心用例 |

### 用例 10 是本阶段的核心验收

它必须同时满足：

- `matched == 0`
- `excluded_by_condition["max_debt_ratio"]` == `{总计: 6, 字段为空: 5, 确实不达标: 1, 去掉后命中: 6}`
- 其余三个条件的「去掉后命中」均为 **0**

这一条同时验证了 marginal 语义、缺失与不达标的拆分、以及恒等式。
**它也正是 agent 放宽策略的信息来源**：6 家里 5 家只是没录负债率，
所以该去掉的是负债率而不是净利。

> 全库 69 家里只有 16 家录了负债率，且**没有一家 ≤ 0.6**。
> 这不是构造的极端用例，是当前数据的真实状态——「条件过严触发放宽」会是常态而非例外。

### 排序验收（快照级别已重新分布，可直接用真实数据验）

2026-08-17 已把生产标的的级别重新铺开，现分布为 **A:8 B:16 C:28 D:17 E:2**，
fixture 同步刷新。三条排序用例：

| 条件 | 命中 | 期望的级别序列 |
|---|---:|---|
| 制造与工业 | 21 | `AAAAA BBBB CCCCCCCC DDDD` |
| 江苏省 | 20 | `A BBBBB CCCCCCC DDDDDDD` |
| 净利≥1000万 | 48 | A×3, B×13, C×18, D×14 |

**「净利≥1000万 + limit=20」是验「先排后截」的关键用例**：
正确实现返回的 20 条必然是 **A×3 + B×13 + C×4**；
若实现成「先截 20 再排序」，级别构成会完全不同（会混入 D 级、漏掉 B 级）。
断言返回列表的级别计数即可，不需要断言具体是哪几家。

另需断言：

1. 返回列表的 `target_grade` 序列**单调不减**（A ≤ B ≤ C ≤ D）
2. 同级内按 `updated_at desc`
3. 任何条件下返回结果都不含 E 级

---

## 五、测试要求

- `tests/test_screening_schema.py`：生成的 schema 必须包含 24 个字段、不含被剔除的两个、
  行业字段的 `enum` 来自 `industry_taxonomy`、`requirement_capability` 五项均为 `boolean`
- `tests/test_screening_sql.py`：每个算子至少一条正例一条反例；
  **`unknown` 与 `null` 同等对待**必须有独立用例（这是最容易漏的）
- 快照级端到端：上表 10 条用例逐条断言
- 全量回归：`python -m pytest -q`

---

## 六、已知的坑

1. **`unknown` 不是 null**——见 3.2，多个枚举列是 `not null default 'unknown'`。
2. **`industry_pairs_json` 与 `industry_l1` 双轨**——以 `industry_pairs_json` 为准，
   `industry_l1`/`industry_l2` 是派生展示列，筛选不要用它们。
3. **`region_constraints_json` 自带 effect**（required/preferred/excluded 混合）——
   本阶段**只实现 required 语义**（即命中即通过）。preferred/excluded 的处理属阶段四，
   由 agent 决定拆成几次调用。不要在 SQL 层自作主张实现三态。
4. **不要把 `is_for_sale` 接进筛选**——它与 `target_grade='E'` 语义重叠，属待清理项。
5. **别信旧文档**——`初筛skill与推荐agent设计框架0805.md` 已作废（标记列方案、
   缺失不出局规则均已推翻），只读 `推荐功能升级设计框架0805.md`。
6. **数字一律不由模型给**——本阶段返回的所有字段值都从数据库原样取出，
   不做任何格式化推断。格式化在写作环节统一做。

---

## 七、验证与部署

改动是纯后端且无迁移。本地 `python -m pytest -q` 通过后，按 `AGENTS.md` 的流程：
推 `main` → 轮询 Railway `/api/v1/health` 确认 `git_commit_sha` 已切换 → 再验证业务行为。
自建侧按需 `ssh match-ma-aliyun` 拉取。**未经明确要求不要 commit、不要 push。**
