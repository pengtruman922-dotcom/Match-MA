# 调研 Agent 重构 验收单 0728

对应施工单：`调研Agent重构施工单0728.md`。提示词正文：`调研Agent提示词0728.md`。

**本轮代码未提交、未部署。** 工作区在 `main` 分支 HEAD `03f6ef4` 之上。

---

## 0. 先读这一条：本轮能验到哪，验不到哪

调研跑在 worker 里、依赖生产数据库与 Tavily，**不部署就无法产生一次真实运行**。所以：

| | 能验 | 怎么验 |
|---|---|---|
| **A 档（本轮可完成）** | 代码审查、本地 `pytest`、前端 `typecheck` / `build`、迁移 splitter 回归、契约一致性静态核对 | §2 |
| **B 档（须先部署）** | 单标调研端到端、数值字段落库与单位、队列隔离、并发、prompt_tokens 实测 | §3，**本轮请标「未测（待部署）」而不是通过** |

**不要因为 B 档没跑就把 A 档判失败，也不要因为 A 档全绿就把 B 档判通过。**

---

## 1. 本轮改了什么

### 1.1 文件清单

**A 批（修复与打通）**

| 文件 | 改动 |
|---|---|
| `backend/app/services/profile_sections.py` | `load_profile_sections` 的 `as_of_date` / `updated_at` 加 `::text`；`order by` 改表限定 |
| `backend/app/jobs/handlers/common.py` | `_json_safe_value` 增加 `date` / `datetime` 分支 |
| `backend/app/jobs/handlers/research.py` | `_current_profiles_for_prompt` 与 `_insert_research_trace` 的 `input_json` 走 `_json_safe_value` |
| `backend/app/api/routes/research.py` | 调研入队改 `queue_name = 'research'`（新常量 `RESEARCH_QUEUE_NAME`） |
| `backend/app/worker.py` | 新增 `--stale-after`；单任务失败改为记日志继续轮询，不再 `raise` 退出进程 |
| `backend/app/services/background_job_governance.py` | 队列汇总的默认队列表加 `research` |
| `scripts/railway_start.py` | 新增 `worker-research` 角色与推断 |
| `railway.worker-research.toml` | **新增**：`--queue research --stale-after 1800` |

**B 批（重构）**

| 文件 | 改动 |
|---|---|
| `backend/app/registry/indicators.py` | 17 个字段 `writable_by` 加 `research`（清单见施工单 §1.1） |
| `backend/app/services/research_apply.py` | 金额单位换算 `MONEY_UNIT_MULTIPLIERS` / `_money_to_yuan` / `_ratio_value`；`normalize_structured_fact` 改注册表驱动；`FieldWriteError` → `ResearchApplyError` 翻译 |
| `backend/app/jobs/handlers/research.py` | 抽出 `apply_research_claims`；`_research_mapper_available` 分支；`_enqueue_research_map_job`；`_relation_of` 改代码判定；`_coverage_not_found_codes`；`result_json` 带报告与 token 用量 |
| `backend/app/jobs/handlers/research_map.py` | **新增**：规范化 job |
| `backend/app/jobs/handlers/dispatch.py` / `__init__.py` | 注册与 re-export |
| `database/migrations/007_*.sql` + `alembic/versions/20260728_0054_*.py` | **新增**：`found_but_rejected` 重建 check 约束 |
| `backend/app/services/seller_target_status.py` | `ai_processing_detail` 增加 `found_but_rejected` 文案 |
| 前端 4 个文件 | 来源标签「公开信息调研」→「AI调研」；`research_last_outcome` 联合体加 `found_but_rejected` |

### 1.2 与施工单的三处偏差（**复核重点**）

1. **A-3 整项作废**。起草时写的「调研流程从来没设过 `information_status`」是基于过期读取的误判——`acquire_ai_processing(desired_status="researching")` 和 `_mark_research_outcome` 里的释放逻辑，在 `033fa0e` 就做完了。**本项没有写任何代码**，施工单 §1.3 / §A-3 已更正。请核对：进度反馈现在到底通不通，以及施工单的更正说法是否准确。

2. **多了一次迁移**。施工单原写「不涉及迁移」，开发中发现 `found_but_rejected` 撞 `chk_seller_target_research_outcome`（baseline 只允许三个值），因此新增 `007` + alembic `0054` 重建约束。已跑 `tests/test_migration_sql.py`。

3. **单位换算落在代码而不是映射 LLM**。讨论中定的是「交给规范化节点做」，实现上规范化节点只负责**原样传递数字与单位**，真正的乘法在 `_money_to_yuan` 里由代码完成。理由是差一个数量级是一万倍且进筛选后不可见。边界没变（仍在规范化环节），执行者从模型换成代码。**这一条如果你不认可，说一声，改回让映射节点算是小改动。**

### 1.3 一个开发中发现的、施工单未列的缺陷（已修）

`FieldWriteError` 与 `ResearchApplyError` 是**兄弟类**（都直接继承 `ValueError`），而调用方只 `except ResearchApplyError`。数值字段一放开，一个越界值（如负债率 150）就会逃出 per-claim 捕获，把整轮调研连同已通过的建议一起回滚——与 P0-1 同一类故障。已在 `_apply_structured_fact_proposal` 里翻译，并加了回归测试。

---

## 2. A 档：本轮就要完成的验收

### 2.1 静态检查

- [ ] `python -m pytest -q` → 预期 **469 passed**（改动前 458）
- [ ] `python -m pytest tests/test_migration_sql.py -q` → 27 passed
- [ ] `cd frontend && npm run typecheck` → 无输出即通过
- [ ] `cd frontend && npm run build` → 成功
- [ ] `python -m ruff check <改动文件>` 与 `git show HEAD:<file>` 的结果**不增加**（仓库基线本身不干净，1127 条，ruff 不是门禁；只看有没有变差）
- [ ] `git diff --stat` 中没有整文件行尾重写（本轮已按 HEAD 行尾规范化过，`tests/test_background_job_summary.py` 应只有 2 行改动）

### 2.2 P0-1：日期序列化（本轮最核心的修复）

- [ ] 读 `load_profile_sections`，确认 `as_of_date::text` / `updated_at::text` 都在
- [ ] **确认 `order by` 是表限定的** `entity_profile_section.updated_at desc`。裸列名会绑到 `::text` 输出别名上，把时序排序变成字典序——这是本轮最容易被漏掉的连带错误
- [ ] `tests/test_research_agent.py::test_claims_stay_json_serialisable_when_current_profiles_carry_dates` 存在且通过
- [ ] **反向验证**：把 `_json_safe_value` 的 date 分支注释掉，该测试应当失败（确认它真的在守这条线）

### 2.3 P0-2：契约一致性（静态核对，不需要跑 LLM）

对着 `调研Agent提示词0728.md` 的 v0.3.0 与代码逐条核：

- [ ] prompt 要求的 `sources` 字段名与 `_claim_sources` 接受的一致
- [ ] prompt 不再在正文里列举栏目——只引用 `context.profile_section_catalog`
- [ ] `PROFILE_SECTION_LABELS` 当前是 5 个 code，与 prompt 不冲突
- [ ] prompt 里的 `industry_pairs_json` 在 `writable_columns('research')` 里
- [ ] **`output_schema_json` 的处置**：施工单 B-2 要求「送进模型或删掉，二选一」。本轮**两件都没做**（v0.3.0/v0.4.0 都把形状写进了正文）。请确认这是否可接受，或记为遗留

### 2.4 字段可写性（决定了会不会写脏数据）

```bash
python -X utf8 -c "import sys;sys.path.insert(0,'.');from backend.app.registry.indicators import writable_columns;print(len(writable_columns('research')));print(sorted(writable_columns('research')))"
```

- [ ] 结果是 **24** 个
- [ ] 「保持关闭」清单里的字段一个都不在其中：`asking_price_yuan` / `asking_price_date` / `transfer_ratio_*` / `transfer_flexibility_type` / `can_control` / `can_consolidate` / `accepts_minority_investment` / `accepts_relocation` / `accepts_return_investment` / `earnout_dependency_status` / `is_for_sale` / `premium_rate` / `management_retention_possible` / `management_team_summary` / `consolidation_path_summary` / `transaction_summary` / `target_name` / `target_type`
- [ ] `listing_market_region` 只对 `manual` + `research` 开放（**不含 `parse`**——开发中曾误开，会连带触发 `test_seller_target_parse_supports_rollback_fields`）

### 2.5 单位换算

- [ ] `test_money_units_are_converted_by_code_not_by_the_model` 通过
- [ ] 手工核一遍：`83,200.00 万元` → `832000000`；`12.5 亿元` → `1250000000`
- [ ] 比率不吃单位乘数：`{"value": "45%", "unit": "%"}` → `45`（不是 0.45，也不是 45×任何倍数）
- [ ] 无法识别的单位（如「斤」）抛 `ResearchApplyError` 而不是静默按 1 处理

### 2.6 降级路径（决定 A 批能否单独发版）

- [ ] `test_missing_mapper_node_falls_back_instead_of_failing` 通过
- [ ] 读 `_handle_seller_target_research`，确认 `_research_mapper_available()` 为假时**走的是原来的内联采纳**，行为与改动前一致
- [ ] 确认映射 job 失败时**不会**让标的卡在「调研中」（调研 job 已经释放过状态）

### 2.7 代码审查要点

- [ ] `_relation_of` 的四个分支（`supplement` / `consistent` / `temporal_update` / `same_period_conflict`）判定是否合理，尤其「都没有 as_of_date 且内容不同 → 冲突」这个选择
- [ ] `_coverage_not_found_codes` 是否兼容旧的顶层 `not_found` 数组
- [ ] `worker.py` 不再 `raise` 之后，Railway 的 `restartPolicyMaxRetries` 是否还有意义
- [ ] `research_map.py` 的 `REPORT_TEXT_LIMIT = 40000` 是否合适
- [ ] 全字段覆盖语义下，多轮调研互相覆盖 `risk_summary` 是否可接受（已定为可接受，靠回滚兜底）

---

## 3. B 档：部署后才能验的（本轮标「未测」）

### 3.1 部署前置

- [ ] Railway 新建 `worker-research` 服务，`MATCH_MA_SERVICE_ROLE=worker-research` 或服务名含 `worker` + `research`；**A 批先起 1 个副本**
- [ ] 设置页发布 `seller_target_researcher` **v0.3.0** 并设为默认
- [ ] 同一节点 `max_tokens` → 16000，`timeout_seconds` → 900
- [ ] **A 批阶段不要建 mapper 节点**（建了就切成两步流水线，验不出基线）
- [ ] 轮询 `/health`，确认 `railway.git_commit_sha` 已切到本次提交
- [ ] 迁移 `0054` 已执行（preDeploy 失败会阻断整个部署，hash 不变就去查迁移）

### 3.2 A 批的成功基线（**这是整轮的关键判据**）

对一个**已有画像**的标的发起调研（例：河北福成五丰 `ae472b95-8da8-47f3-b906-50bf5734f580`，它有两条 `as_of_date=2026-07-24` 的画像，正是 0727 崩溃的那一个）：

- [ ] job 状态 `succeeded`，**不再出现 `Object of type date/datetime is not JSON serializable`**
- [ ] `result_json.proposal_count > 0` 且 `auto_accepted_count > 0`
- [ ] 标的详情页至少一栏画像内容变化，来源显示「AI调研」，可在更新记录中回滚
- [ ] `/background-jobs/{id}/traces` 的 `schema_validation_json.normalization_notes` **不再出现 `missing_sources`**
- [ ] 调研期间列表页/详情页显示处理中并自动刷新，结束后状态归位
- [ ] **记录 `prompt_tokens` / `completion_tokens` / `tool_calls`**——B-7 做不做取决于这个数（超过模型窗口 60% 就要做上下文外置）

### 3.3 队列隔离与并发

- [ ] `/background-jobs/summary/queues` 中出现 `research` 队列
- [ ] 调研任务的 `queue_name` 是 `research`，不再是 `llm`
- [ ] 调研运行超过 5 分钟未被误判 failed（`--stale-after 1800` 生效）
- [ ] 5 个标的并发调研期间提交一份业务更新，抽取任务**不排在调研后面**
- [ ] 人为让一个调研 job 失败，worker 进程**不退出**，继续消费下一个任务

### 3.4 B 批（建 mapper 节点后）

- [ ] 一家 A 股上市标的：`current_revenue_yuan` / `current_net_profit_yuan` / `market_cap_yuan` **数量级正确**，且 `financial_period_label` 同时写入
- [ ] 一家非上市标的：**没有任何凭空的财务数字**；相关判断出现在 `ops_quality` 画像正文
- [ ] `industry_pairs_json` 写入值都能在行业字典中命中
- [ ] `risk_summary` 写入且来源「AI调研」，可回滚
- [ ] 至少一栏出现 `info_status='not_found'`（覆盖清单生效）
- [ ] 「保持关闭」清单里的字段一个都没被写入
- [ ] 映射 job 可单独重试：把它置 failed 后重试，**不重新触发检索**
- [ ] 出现过 `found_but_rejected` 结论（可人为构造：让 mapper 输出无 `sources` 的 claim）

---

## 4. 已知风险与观察项

1. **零真机验证**。本轮所有代码只过了本地 `pytest` 与类型检查，一次真实调研都没跑过。§3 全部未测。
2. **规范化节点的 prompt 从未运行过**。`调研Agent提示词0728.md` 第三节是设计稿，没有一次实际调用验证过它能稳定产出合法 JSON。第一次跑很可能要调。
3. **`information_status` 的自愈缺口**。若任务被 `requeue_stale_running_jobs` 回收（而非 handler 抛错），走不到 dispatch 的兜底，状态会滞留 `researching`，而 `acquire_ai_processing` 会因此拒绝后续调研与解析。窗口调到 1800s 后概率很低，但没有自愈手段，也没有清理入口。
4. **批量调研遇到 busy 标的会整批 409**。`_enqueue_seller_research_job` 抛 `AIProcessingBusyError` → `HTTPException`，路由逐个入队，一个失败整批中断。属既有行为，本轮未改。
5. **数值全部 auto_accept 且不区分主体类型**。这是明确拍板的取舍，兜底是来源标注 + 更新记录 + 回滚。**「数字是不是编的」只有 prompt 软约束**，没有代码执行面。
6. **`source_excerpt` / `anchor_matches_json` 仍是死字段**。prompt 要求逐字引文，但代码既不落库也不校验。按本轮取舍维持现状。
7. **B-7 上下文外置未做**，等 §3.2 的实测数据。
8. **报告没有顾问可读入口**。存在 `background_job.result_json` 里，只能从 `/background-jobs/{id}` 看到。九模块里装不进 5 栏的内容（诉讼细节、访谈问题清单）目前对顾问不可见。

---

## 5. 下一步

1. 复核本单 §2（A 档），有问题当场提。
2. 认可后按 §3.1 部署 **A 批**，拿到 §3.2 的成功基线并记录 token 用量。
3. 基线通过再建 mapper 节点、发 v0.4.0，验 §3.4。
4. B 批通过后把结论合并回 `docs/系统总纲.md`，归档 `调研Agent提示词草案0721.md`。
