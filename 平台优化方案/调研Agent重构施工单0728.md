# 调研 Agent 重构施工单 0728

图纸：`docs/系统总纲.md`。前序方案：`调研Agent与标的信息层重构方案0721.md`（领域设计，仍有效）、`调研Agent提示词草案0721.md`（已过期，本单替换）。

**本单范围**：标的公开信息调研（`seller_target_research`）从「跑一次产出为零」修到「能稳定补全标的信息」。不改推荐、不改抽取、不改撮合。买家侧无调研功能，本单不新增。

**批次顺序：A 批修复打通 → 量出实测数据 → B 批重构**。A 批可独立发版验证，且**必须先拿到一次成功基线**再开 B 批。

---

## 0. 起因：这个功能上线以来从未产出过一条数据

2026-07-27 查生产 `background_job`，`seller_target_research` 历史上共 **5 次**运行，**5 次全废**，分两种死法：

| 时间 | 标的 | job id | 结果 |
|---|---|---|---|
| 2026-07-22 05:46 | 江苏金陵体育 `0454ff0b` | `5b1c409f` | succeeded，`claim_count=0` → `no_public_information` |
| 2026-07-22 05:56 | 中大咨询集团 `b63f37ef` | `db3945a6` | succeeded，`claim_count=0` → `no_public_information` |
| 2026-07-23 07:31 | 苏州数据中心项目 `952da73f` | `7f8c1b90` | failed `Object of type datetime is not JSON serializable` |
| 2026-07-23 07:43 | 苏州数据中心项目 `952da73f` | `781048e6` | failed 同上 |
| 2026-07-27 07:03 | 河北福成五丰 `ae472b95` | `af8d9041` | failed `Object of type date is not JSON serializable` |

### P0-1　日期对象进 JSONB 绑定 → 整事务回滚

[`profile_sections.py:160`](../backend/app/services/profile_sections.py) 的 select 取 `as_of_date` 和 `updated_at` **没有 `::text`**，`dict(row)` 里是 Python `date` / `datetime`；而 [`common.py:707`](../backend/app/jobs/handlers/common.py) 的 `_json_safe_value` 只处理 UUID / Decimal / dict / list / tuple，**不处理日期**。

两个爆点，都在 agent 跑完之后：

| 位置 | 脏值来源 | 报错 |
|---|---|---|
| [`research.py:252`](../backend/app/jobs/handlers/research.py) `_insert_research_trace(input_json=research_context)` | `current_profile_sections[*].as_of_date` | `Object of type date` |
| [`research.py:507`](../backend/app/jobs/handlers/research.py) `_insert_research_proposal(current_value_json=…)` | 原始 row 里的 `updated_at` | `Object of type datetime` |

生产数据与这个分岔完全吻合：河北福成五丰有两条 `as_of_date=2026-07-24` 的画像 → 死在 trace，报 `date`；苏州数据中心只有一条 `as_of_date=None` 的画像 → trace 过关，死在 proposal，报 `datetime`。

**触发条件是「标的已有任意一条 accepted 画像」** —— 信息越全的标的越调不动，而这正是重复调研的主场景。worker 用 `session_scope()`，异常整事务回滚：trace、proposal、画像、`last_research_at` 全部消失，前面 2.5~5 分钟的 Tavily + LLM 一行痕迹不留。这就是用户报告的「看不到信息的变化」。

### P0-2　prompt 产出契约与代码收货契约不一致 → 全额丢弃

那两次「成功」的运行，agent 搜了 6~7 次、抓了年报 PDF，写出了带营收构成、FIBA 认证、专利数的完整画像，然后被**全部丢弃**：

```
normalization_notes: [
  "profile_sections:business_product:missing_sources",
  "profile_sections:chain_position:missing_sources",
  ... 共 13 条 ]
```

[`research.py:461`](../backend/app/jobs/handlers/research.py) 的 `_claim_sources` 只认 `sources`（http(s) URL 数组）或 `source_url`；模型输出的是 `evidence_refs: ["E3"]`。

当前默认 prompt 是 **v0.2.2**（id `e1e14173-ea3a-422c-b481-1644bd5ba03b`，0723 建），描述写着 "Uses sources/source_excerpt matching the proposal write path"，但**正文没改到位**。逐条对：

| 维度 | prompt v0.2.2 正文 | 代码实际收货 | 后果 |
|---|---|---|---|
| 来源 | system: `cite at least one evidence_ref and an exact evidence_quote` | `sources`: http(s) URL 数组 | 全丢 |
| 输出形状 | user: `Return exactly:` **后面是空的** | 需要 `profile_sections` / `structured_facts` / `not_found` | 靠 context 兜 |
| 栏目 | 描述 6 个（含 `chain_position` / `sell_intent_risk`，**无 `identity`**） | 只有 5 个，前两者是别名会折叠或判 `duplicate_section` | 折叠丢 |
| 结构化字段 | rule 5: `keep tracks in industry_l1/industry_l2` | 白名单是 `industry_pairs_json`，无 l1/l2 | 全丢 |
| JSON Schema | `output_schema_json` 里 `sources` 是 required | **从不进模型**——只写进 `ai_trace`（[`research.py:748`](../backend/app/jobs/handlers/research.py)），LLM 请求的 `response_format` 取自 node 字段 | 死存储 |
| 引文 | rule 6: `source_excerpt` 必须是逐字子串 | claim 不带该字段，insert 语句也没这列 | 解析后丢弃 |
| 冲突关系 | 只字未提 `relation` | `_relation_of` 缺省 `supplement` | UI 恒显示「补充信息」 |

> **`output_schema_json` 是继 `few_shot_examples_json` 之后的第二个死存储字段**，`anchor_matches_json` 是第三个（只读不写）。共同病根：同一份契约写在 prompt 正文、`output_schema_json`、Python 常量三个地方，只有一个真正生效，改任何一处不会惊动另外两处。

**P0-1 和 P0-2 必须一起修**：只修 P0-1，功能会从「崩溃」变成「每次都告诉你未找到公开信息」。

---

## 1. 已定稿的设计决策

| # | 决策 | 备注 |
|---|---|---|
| D1 | 调研的目的是**补全标的信息**，模块与内容由标的信息结构（45 字段 + 5 画像栏）反推 | 不照搬通用尽调九模块框架 |
| D2 | **一个 agent 一次跑完全部模块，统一输出**；不做模块级 fan-out | 「并发 5」指 5 个标的并发，不是 5 个模块并发 |
| D3 | 契约唯一事实源 = 代码常量 + `research_context`，**prompt 正文不复述**栏目定义和字段清单 | 重复即漂移，这是 P0-2 的根因 |
| D4 | 规范化独立成 job（`parent_job_id` 挂调研 job） | 调研 5~10 分钟很贵，映射几秒很便宜，失败要能分开重试 |
| D5 | 数值类字段放开给 research，**不区分上市/非上市主体**，全部 auto_accept | 兜底是来源标注 + 更新记录 + 回滚 |
| D6 | 数值只录原文直读，**不计算、不换算、不推断**；状态/分类类**允许推断**；单位换算由规范化节点做 | 硬约束只有字段白名单，其余是 prompt 软约束 |
| D7 | 全字段**覆盖**语义，不做合并 | 多轮调研会互相覆盖，靠回滚兜底 |
| D8 | 信源分级只作**检索优先级指导**，不作输出字段 | 不增加模型负担 |
| D9 | 未检索到的内容**不输出**；靠报告末尾的**覆盖清单**区分 `not_found`（查过没有）与 `missing`（没查） | 保住 0721 方案 §4 的语义 |
| D10 | 调研走**独立队列 `research`**，5 副本；stale 窗口按队列配 | 见 §1.2 |
| D11 | `max_tokens` 放宽到 16000，不置空 | 保留成本刹车 |
| D12 | 接上 `information_status='researching'` | 进度反馈的线前端已接好，见 §1.3 |
| D13 | **分两批**：A 批修复打通并量出实测；B 批重构 | 见 §0——此功能从无成功基线 |

### 1.1 字段可写性：公开信息能不能查到，切一刀

当前 45 个字段中 **21 个参与筛选（`screening`）**，调研只能写 5 个。被挡住的 16 个筛选字段按「公开信息能否查到」切开：

**放开给 research（本单新增）**

```
current_revenue_yuan 筛      current_net_profit_yuan 筛   current_total_profit_yuan 筛
current_assets_yuan          current_debt_ratio 筛        current_operating_cash_flow_yuan
financial_period_label       profitability_status 筛      cash_flow_status 筛
operation_stability_status   listing_market_region 筛     market_cap_yuan 筛
valuation_yuan 筛            valuation_date               pe_ratio 筛
pe_source_type               risk_summary
```

**保持关闭（公开渠道不存在，属卖方私下向顾问表达的交易诉求）**

```
asking_price_yuan / asking_price_date        transfer_ratio_min / max / text
transfer_flexibility_type                    can_control          can_consolidate
accepts_minority_investment                  accepts_relocation   accepts_return_investment
earnout_dependency_status                    is_for_sale          premium_rate
management_retention_possible                management_team_summary
consolidation_path_summary                   transaction_summary
target_name                                  target_type
```

> `pe_source_type` 的枚举里**本来就有 `research` 这个值**，说明设计时已预留「PE 来自调研」这条路，只是 `writable_by` 没开。本单是补完，不是推翻 [`research_apply.py:24`](../backend/app/services/research_apply.py) 那条「数字不给调研写」的注释——那条注释随本单更新。

### 1.2 队列隔离

生产 `llm` 队列近 200 条任务的类型分布：

```
business_update_extract_actions   94     seller_target_parse              4
recommendation_deep_eval          41     recommendation_report_generate   4
buyer_intent_parse                10     model_node_test                  2
seller_target_research             6
```

worker 按队列**单线程顺序**消费（[`worker.py:19`](../backend/app/worker.py) `run_once` 一次 claim 一个、同步执行完再取下一个），5 个副本 = 5 个并发槽位。**5 个标的同时调研、每个 5~10 分钟，会把 5 个槽位全部占满**，期间业务更新抽取和推荐深评全部排队——而这两个是有人在屏幕前等结果的路径，调研反而可以慢慢来。

所以调研走独立队列 `research`。`background_job.job_type` 和 `queue_name` 都是无约束的 `text`（[`001_baseline.sql:136`](../database/migrations/001_baseline.sql)），**新队列和新 job_type 都不需要迁移**。

### 1.3 进度反馈：**已经是通的，本单不需要做**

> **起草更正（2026-07-28）**：本节初稿写的是「调研流程从来没设过 `information_status`」，那是基于过期读取的误判。开工前逐条复核现盘时发现，这件事已在 `033fa0e`「feat: consolidate seller target status phase A」里做完，**A-3 整项作废**。

现状（可自行核对）：

- [`research.py:321`](../backend/app/api/routes/research.py) 入队前调用 `acquire_ai_processing(desired_status="researching")`，与 job insert 同一事务；被占用时抛 `AIProcessingBusyError` → 409。
- [`research.py:653`](../backend/app/jobs/handlers/research.py) `_mark_research_outcome` 写 `last_research_at` / `research_last_outcome` 的同时，把 `information_status` 从 `researching` 释放回 `normal`。handler 的每个出口（缺供应商、密钥错、LLM 失败、输出不合法、成功）以及 [`dispatch.py:81`](../backend/app/jobs/handlers/dispatch.py) 的兜底边界都经过它。
- [`seller_target_status.py`](../backend/app/services/seller_target_status.py) 已有 `AI_PROCESSING_RESEARCHING` / `AI_PROCESSING_RESEARCH_FAILED` 两个状态和对应文案（「正在检索公开信息」「最近一次调研失败，请查看调研任务错误后重试」）。
- 前端 [`filters.ts:7`](../frontend/src/features/targets/filters.ts) 把 `parsing | researching` 判为处理中，[`TargetDetail.tsx:77`](../frontend/src/pages/TargetDetail.tsx) 与 [`Targets.tsx:123`](../frontend/src/pages/Targets.tsx) 据此轮询。

所以「批量调研零反馈」的真实原因不是没接线，而是 **P0-1 让任务在 agent 跑完之后崩溃**——虽然 `dispatch.py` 的兜底会释放状态，但整轮产出被回滚，用户看到的就是转了几分钟然后什么都没变。P0-1 修好，这条链路自然成立。

**遗留的一个缺口**（不在本单处理，验收时观察）：若任务被 `requeue_stale_running_jobs` 回收（而非 handler 抛错），走的不是 dispatch 的兜底路径，`information_status` 会滞留在 `researching`，而 `acquire_ai_processing` 会因此拒绝后续调研与解析。stale 窗口调到 1800s 后概率很低，但没有自愈手段。

---

## 2. 目标形态

```
用户点「AI调研」/「批量调研」
  → 置 information_status='researching'
  → 入 research 队列（5 副本并发，stale 1800s）
      ↓
  ① 调研 job（seller_target_research）
     一个 agent 跑完 M0~M5 六个模块，一次性输出：
       · 结构化 claims（画像 5 栏 + 结构化字段，每条带 sources URL）
       · 覆盖清单（覆盖了哪些模块 / 哪些查过但无公开信息）
     报告与 claims 写进 job.result_json
      ↓（parent_job_id）
  ② 规范化 job（seller_target_research_map）
     不带工具、便宜模型、可重跑：
       · 金额单位换算（万元/亿元 → 元）
       · 行业命中字典、枚举校验、字段白名单过滤
       · 覆盖清单 → not_found / missing
       · 输出符合契约的 proposals
      ↓
  ③ 现有 apply 路径（不改）
     write_seller_target_fields / apply_profile_section
     → field_value_source（来源标签「AI调研」）→ 更新记录 → 可回滚
      ↓
  置回 information_status='normal' / 'insufficient'
  写 last_research_at / research_last_outcome
```

**模块与产出的对应**（模块只是 prompt 里的检索组织方式，不是 job 边界）：

| 模块 | 画像栏 | 结构化字段 |
|---|---|---|
| M0 主体锚定 | `identity` | `target_subject_name`、省/市/区、`listed_status`、`listing_market_region` |
| M1 业务与行业 | `business_product` | `industry_pairs_json`、`business_summary` |
| M2 财务与经营质量 | `ops_quality` | 6 个数值 + `financial_period_label` + 3 个状态枚举 |
| M3 技术、资质与团队 | `tech_team` | **无**（字段均不对 research 开放）→ 检索预算最小 |
| M4 资本与估值 | `deal_terms` | `market_cap_yuan`、`valuation_yuan`、`valuation_date`、`pe_ratio`、`pe_source_type` |
| M5 风险与合规 | **不写画像栏** | `risk_summary` |

对照通用尽调九模块：主体与股权→M0；业务与运营→M1；财务→M2；知识产权与技术 + 团队与治理→M3；资本与估值→M4；法律与合规 + 舆情ESG→M5；**行业与市场并入 M1，只保留行业归类与标的地位**。砍掉市场规模、增速、产业政策、技术替代趋势——这些是行业层信息，落不进 45 个字段和 5 个画像栏中的任何一个，对「哪个买家要这个标的」无增益。

> M5 刻意不写画像栏：`apply_profile_section` 是 supersede 语义，M4 和 M5 若都写 `deal_terms` 会互相覆盖。M5 的产出就是 `risk_summary` 一个字段。

---

## 3. A 批：修复与打通（无迁移，可独立发版）

目标只有一个：**单标调研跑通，画像和字段真的写进去一条，并量出 prompt_tokens 实测值。**

### A-1　修 P0-1 日期序列化

1. [`profile_sections.py:160`](../backend/app/services/profile_sections.py) `load_profile_sections` 的 select 改为 `as_of_date::text as as_of_date, updated_at::text as updated_at`。
   - 消费方只有 [`recommendation.py:340/364`](../backend/app/jobs/handlers/recommendation.py)（经 `render_profile_text`，只读 `content_text`）和 `research.py`，改文本安全。
   - ⚠ **`order by` 必须同时改**。PostgreSQL 的 `ORDER BY` 遇到裸列名会**优先解析为输出列别名**，所以 `updated_at::text as updated_at` 会让 `order by ... updated_at desc` 变成按文本排序。ISO 时间戳的字典序碰巧多数情况下与时序一致，但这是巧合不是保证（小数秒位数不定），不能依赖。
   - 改为表限定：`order by entity_id, section_code, entity_profile_section.updated_at desc`。
   - 随之要改 `tests/test_profile_sections.py:185` 的断言字符串（该用例的意图是「按 updated_at 而非 as_of_date 决定当前版本」，第二条 `assert "as_of_date desc" not in statement` 保持不变，意图不受影响）。
2. [`common.py:707`](../backend/app/jobs/handlers/common.py) `_json_safe_value` 增加 `date` / `datetime` 分支返回 `.isoformat()`（防御性兜底，防止其它 raw SQL 走同一条路）。
3. 新增测试：把带 `date` / `datetime` 的 `current_profiles` 喂给 `normalize_research_output` + 绑定序列化路径，断言可 `json.dumps`。

### A-2　修 P0-2 prompt 契约（新建 prompt 版本，**不发版**）

在设置页「Prompt 版本管理」基于 v0.2.2 建 **v0.3.0**，最小对齐四处（完整重写留给 B-2，A 批只求跑通）：

1. system 里的 `evidence_ref` / `evidence_quote` → 改为「每条结论必须给出 `sources`：一个或多个可访问的 http(s) 链接」。
2. user 模板 `Return exactly:` 后面补上实际 JSON 形状。
3. 栏目定义**删掉正文里的 6 段描述**，改为「只使用 `context.profile_section_catalog` 中列出的 `section_code`」（当前是 5 个：`identity` / `business_product` / `tech_team` / `ops_quality` / `deal_terms`）。
4. rule 5 的 `industry_l1/industry_l2` → 改为 `industry_pairs_json`，并说明取值必须来自 `context` 提供的候选。

### A-3　~~接上 `information_status='researching'`~~ —— **作废，已在 `033fa0e` 完成**

见 §1.3 的更正。开工前复核现盘发现整条链路（入队占位 → 每个出口释放 → 前端轮询）都已存在，本项**不写任何代码**，只在验收时确认行为符合预期。

D12 相应从「本单要做」降级为「本单要验」。

### A-4　队列隔离与 stale 窗口

1. `_enqueue_seller_research_job` 的 `queue_name` `'llm'` → `'research'`。
2. 新增 `railway.worker-research.toml`（照抄 `railway.worker-llm.toml`，改 `--queue research --stale-after 1800`）；`scripts/railway_start.py` 的 `_infer_role` 增加 `worker-research` 分支。
3. worker CLI 增加 `--stale-after`（默认 300），传给 `requeue_stale_running_jobs`。该函数本就按 `queue_name` 调用，**无需按 job_type 分支**。
4. A 批**先起 1 个 research 副本**（5 副本放到 B 批，A 批只验证单标跑通）。

### A-5　放宽 `max_tokens`

研究节点 `seller_target_researcher` 的 `max_tokens` 5000 → **16000**，`timeout_seconds` 300 → **900**。纯配置，设置页可改。

> [`llm_client.py:66`](../backend/app/ai/llm_client.py) 是 `if max_tokens is not None:` 才放进 payload，所以置空也可行；但它是 agent 跑飞时唯一的成本刹车，本单保留一个大值。

### A-6　单任务失败不再带走 worker 进程

[`worker.py:35`](../backend/app/worker.py) 在 `mark_job_failed` 之后 `raise`，异常穿透 `main()` 导致进程退出，靠 Railway `restartPolicyMaxRetries = 3` 兜。改为记录日志后继续轮询。

### A 批验收（必须全部满足才能开 B 批）

- [ ] `python -m pytest -q` 全绿，新增日期序列化测试通过
- [ ] 推送后轮询生产 `/health`，确认 `railway.git_commit_sha` 已切到本次提交
- [ ] 对**已有画像的标的**（如河北福成五丰 `ae472b95`）发起调研，job 状态 `succeeded`，不再出现 `Object of type date/datetime`
- [ ] `result_json.proposal_count > 0` 且 `auto_accepted_count > 0`
- [ ] 标的详情页至少一栏画像内容发生变化，来源显示为调研，可在更新记录中回滚
- [ ] 调研期间列表页/详情页显示处理中并自动刷新，结束后状态归位
- [ ] `background-jobs/{id}/traces` 中 `schema_validation_json.normalization_notes` **不再出现 `missing_sources`**
- [ ] **记录 `ai_trace.prompt_tokens` / `completion_tokens` / `tool_calls` 实测值** —— B-7 是否需要做，取决于这个数

---

## 4. B 批：重构

### B-1　注册表放开 + 来源改名

1. `backend/app/registry/indicators.py`：§1.1「放开」清单中的字段 `writable_by` 加 `research`；`research_apply.py:24` 的注释同步更新。
2. `normalize_structured_fact`（[`research_apply.py:124`](../backend/app/services/research_apply.py)）增加数值/日期/枚举分支：
   - `*_yuan` / `*_ratio`：接受 `{"value": 83200, "unit": "万元"}` 或已换算的数字，走 §B-3 的换算；非数字或负值（除利润类）拒绝
   - `financial_period_label`：与数值字段**同时缺失才通过**——单独给数字不带期间标签的一律拒绝（`ResearchApplyError`）
   - 三个 `*_status` 枚举：值必须在 `enum_options` 内
   - `valuation_date`：ISO 日期
3. 来源标签「公开信息调研」→「**AI调研**」，三处：[`TargetInfoPanel.tsx:469`](../frontend/src/features/targets/TargetInfoPanel.tsx)、[`:570`](../frontend/src/features/targets/TargetInfoPanel.tsx)、[`fieldLabels.ts:453`](../frontend/src/lib/fieldLabels.ts)。按钮文案「公开信息调研」→「AI调研」（`TargetInfoPanel.tsx:224`、`BatchResearchDialog.tsx:62`）。

### B-2　新 prompt（v0.4.0）

结构：角色 → 检索方法论 → 模块清单（M0~M5，只写「查什么」不写「有哪些栏目/字段」）→ 数据取用规则 → 不要检索清单 → 输出契约。

栏目定义、字段白名单、枚举取值**一律不写进正文**，全部引用 `research_context`（已在送 `profile_section_catalog` / `allowed_structured_fields` / `allowed_relations`）。另外把 `output_schema_json` 作为 `{{ output_schema_json }}` 变量注入 `_render_prompt_messages`，让它真正进模型——或者删掉这个字段。**二选一，不能维持现状。**

数据取用规则（D6 定稿文本）：

```text
你自行判断检索到的信息是否可信：优先监管披露、官方登记、公司自身公告；
不同来源冲突时，说明分歧并给出更采信哪一方及理由。判断可信，就采用。

对数值型字段（营业收入、净利润、利润总额、资产总额、资产负债率、
经营性现金流、市值、估值、PE），额外遵守：
1. 只录入在原文中直接读到的数字。不做任何计算、换算或倒推——
   不用增长率反推绝对值，不用季度数相加得年度数。
2. 原样给出数字和它在原文里的单位（例："83,200.00" + "万元"），
   不要自己折算成元。单位统一由后续环节处理。
3. 每个数字必须同时给出期间标签（如"2024年度""2025年三季度"）。
   给不出期间的数字，不要输出。
4. 读不到确切数字时不要输出该字段，把相关描述写进对应画像正文。

对状态与分类字段（盈利状况、现金流状况、经营稳定性、上市状态、
行业归类、地区），允许基于已获得的事实做判断和归类，并说明依据。

检索不到的内容不要输出。在报告末尾给出覆盖清单：
本轮覆盖了哪些模块、哪些模块检索过但无公开信息。
```

「不要检索也不要输出」清单 = §1.1 的「保持关闭」列表。

> 该清单有硬约束兜底：`writable_columns('research')` 白名单外的字段在 `normalize_research_output` 里记 `unsupported_field` 直接丢弃。prompt 里写只是省得它白费检索预算。**真正只剩软约束的是「数字是不是编的」**，风险已由 D5 接受，兜底为来源标注 + 更新记录 + 回滚。

### B-3　规范化 job（新 job_type `seller_target_research_map`）

- 新 node `seller_target_research_mapper` + 独立 prompt，走设置页版本管理。不带工具、便宜模型、`response_format=json_object`。
- 调研 job 结束时把**报告全文 + 原始 claims** 放进 `background_job.result_json`（jsonb，无迁移），并入队映射 job（`parent_job_id` = 调研 job id，同 `research` 队列）。
- 映射 job 读父 job 的 `result_json`，产出符合契约的 proposals 并走现有 apply 路径。
- 职责：金额单位换算 → 元；行业命中字典（`normalize_industry_pairs`）；枚举校验；白名单过滤；覆盖清单 → `not_found` / `missing`。
- **调研成功但映射失败时，调研 job 保持 succeeded**，映射 job 单独 failed 可单独重试——不重跑 5~10 分钟的检索。
- 可选加固：复用 [`business_update.py:966`](../backend/app/jobs/handlers/business_update.py) 的金额校正器（从报告原文解析中文金额，对不上就用原文里最接近的值替换并记 note）。只需报告文本，不依赖新表。

### B-4　覆盖清单 → `not_found`

映射节点据覆盖清单判定：覆盖了但无内容 → `info_status='not_found'`；未覆盖 → 保持 `missing`。恢复 0721 方案 §4 中「查了没有」与「根本没查」的区分——这是 30 天二次确认（`BatchResearchDialog`）和下一轮调研的判断依据。

同时删除 v0.2.2 rule 2 的 `never output not_found from a partial web search`。

### B-5　并发放大

`railway.worker-research.toml` 副本数 1 → 5。前置条件：A-4 的 `--stale-after 1800` 已生效（多副本 + 300 秒窗口 = 副本互相误杀正在跑的任务，且 `max_attempts=1` 意味着回收即判死）。

### B-6　`relation` 由代码判定

`_relation_of` 当前取模型的 `relation` 字段，prompt 从未要求过，故恒为 `supplement`，UI 永远显示「补充信息」。改为代码判定：无 current 值 → `supplement`；有 current 且新值不同、`as_of_date` 更新 → `temporal_update`；同期不同 → `same_period_conflict`。模型只提供事实与日期。

### B-7　上下文外置（**条件项**）

一个 agent 一次跑完六模块 ≈ 15~20 次检索，工具结果全部堆在上下文且每轮全量重发（`SNIPPET_LIMIT=600` × 6 条/次，加若干次 `FETCH_TEXT_LIMIT=8000` 的正文）。

**做不做取决于 A 批实测的 `prompt_tokens`**：超过模型窗口 60% 才做。做法二选一——(a) 建 `research_evidence` 表，搜索结果落表、上下文只放索引行，模型用 `read_source(id)` 按需取正文；(b) 每轮把旧的 tool 消息压缩成摘要。(a) 顺带让 `source_excerpt` 子串校验有数据源、让 `anchor_matches_json` 不再是死字段。

`MAX_TOOL_ITERATIONS = 12` 不是瓶颈（实测 6~7 次搜索只用 2~4 轮，模型会一轮并发多个 tool_call），不必调整。

---

## 5. 验收点

### A 批

见 §3 末尾清单（8 项）。

### B 批

- [ ] `pytest -q` 全绿；`tests/test_action_type_sync.py` 不受影响（本单不新增 `extracted_action` 类型）
- [ ] 对一家 A 股上市标的调研：`current_revenue_yuan` / `current_net_profit_yuan` / `market_cap_yuan` 落入正确数量级（**单位换算正确**，误差 10000 倍是本项最主要的失败模式），且 `financial_period_label` 同时写入
- [ ] 对一家非上市标的调研：**未出现任何凭空的财务数字**；相关判断出现在 `ops_quality` 画像正文
- [ ] `industry_pairs_json` 写入值均能在行业字典中命中；未命中时记 note 而非写脏数据
- [ ] `risk_summary` 写入且来源显示「AI调研」，可回滚
- [ ] 至少一栏出现 `info_status='not_found'`（覆盖清单生效）
- [ ] 「保持关闭」清单中的字段**一个都没有被写入**
- [ ] 映射 job 可单独重试：手工把映射 job 置 failed 后重试，不重新触发检索
- [ ] 5 个标的并发调研期间，提交一份业务更新，抽取任务**不排在调研后面**（队列隔离生效）
- [ ] 调研任务运行超过 5 分钟未被误判 failed（stale 窗口生效）
- [ ] UI 中不再出现「公开信息调研」字样

---

## 6. 流程要求与遗留

- A 批与 B 批**分别提交、分别验证**。A 批未拿到成功基线不得开 B 批（§0：此功能从无一次成功产出，混在一起改会分不清是新架构还是老 bug）。
- 涉及后端的提交推送后，先轮询生产 `/health` 确认 commit hash 已切换，再验证业务行为。
- **迁移**：起草时判断「不涉及迁移」，开发中发现 `found_but_rejected` 撞上 `chk_seller_target_research_outcome`（[`001_baseline.sql:836`](../database/migrations/001_baseline.sql) 只允许 `found | no_public_information | failed`），因此新增 `007_research_outcome_found_but_rejected.sql` + alembic `20260728_0054` 重建该约束，不动数据。已跑 `tests/test_migration_sql.py`。其余仍无需迁移：`job_type` / `queue_name` 是无约束 `text`，报告存既有的 `result_json` jsonb 列，注册表 `writable_by` 是 Python 常量。若 B-7 走方案 (a) 会再需要一次建表迁移。
- Prompt 一律通过设置页「Prompt 版本管理」发布，**不写 prompt seed 迁移**。
- B 批落地后把结论合并回 `docs/系统总纲.md`，并归档 `调研Agent提示词草案0721.md`（已被 B-2 取代）。

**本单未处理、留作后续**：

1. **报告的顾问可读入口**。B-3 把报告存进 `result_json`，但没有 UI 展示。九模块里装不进 5 栏的内容（诉讼细节、访谈问题清单、VDR 清单）目前只有通过 `/background-jobs/{id}` 才看得到。需要单独定：挂在标的详情页哪个 tab、要不要落成正式的文档实体。
2. **`source_excerpt` 与 `anchor_matches_json`**。两者目前都是解析后丢弃 / 只读不写。本单按 D6 只用 prompt 软约束，不做子串校验，故维持现状；若 B-7 走方案 (a)，可顺带补上。
3. **`research_retry_after` 只写不读**（0721 方案 P1-4）。现由前端 `BatchResearchDialog` 的 30 天二次确认替代，字段本身仍是死存储，可择机清理。
