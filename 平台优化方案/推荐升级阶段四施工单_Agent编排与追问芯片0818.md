# 阶段四施工单：主 Agent 编排、深评接管与追问芯片

> 2026-08-18。依据：`平台优化方案/推荐功能升级设计框架0805.md`。
> 前置代码：阶段一初筛 skill（`b5da7c2`）、阶段二需求解析（`ac9015a`）、
> 阶段三深评节点（`d7bdb0d`）均已合入 `main`。
> 本文与框架冲突处以本文为准：本文按前三阶段的实际接口、生产 Prompt 实况及本轮讨论收口。

---

## 全局分期（本单拆成四个串行施工包）

| 施工包 | 内容 | 前置 | 完成后才能做 |
|---|---|---|---|
| **4A** | **阶段三 Prompt 收口 + 最近 5 轮对话驱动的“本轮当前需求快照” + 快照注入** | 阶段一至三 | 4B |
| **4B** | **主 Agent 初筛编排硬约束 + 多批次并集 + 深评回灌主 Agent** | 4A | 4C |
| **4C** | **最终素材包 v2 + Writer v0.2.0 + 追问芯片** | 4B | 4D |
| **4D** | **端到端验收、生产 Prompt 收口、部署验证、图纸回填** | 4A–4C | 阶段五拆旧链路 |

四包必须串行。每包结束都要跑对应测试并留下施工记录；上一包未收口，不开下一包。
配套开场白：

- `平台优化方案/阶段四4A开发_开场白0818.md`
- `平台优化方案/阶段四4B开发_开场白0818.md`
- `平台优化方案/阶段四4C开发_开场白0818.md`
- `平台优化方案/阶段四4D验收_开场白0818.md`

---

## 一、这个阶段解决什么

前三阶段都采取了“先产出、先落库、暂不接管最终答案”的灰度方式：

- 阶段一已经把 `search_targets` 换成纯 SQL 硬筛；
- 阶段二已经产出 `agent_understanding`，但主 Agent 的 prompt 还看不到需求快照；
- 阶段三已经产出 `agent_deep_eval`，但素材包与最终正文还使用主 Agent 的旧名单；
- 前端已经有追问芯片组件，但芯片内容仍来自旧主 Agent 输出，Writer 还会把追问建议揉进文末。

因此当前真实链路还是：

```text
需求解析（旁路落库）
→ 主 Agent 自己理解原话、自己选条件、自己挑名单
→ 深评（旁路落库）
→ 旧 brief
→ Writer
```

阶段四要把它收成唯一主链：

```text
最近 5 轮用户问题 + AI 最终正文 + 本轮用户消息
→ ① 需求解析节点：产出“本轮当前需求快照”
→ ② 主 Agent：按快照编排多次 SQL 初筛，并决定是否放宽
→ ③ 所有真实初筛批次按标的 ID 求并集，形成深评候选池
→ ④ 深评节点：对整个候选池逐条定性判定并排序
→ ⑤ 深评结果回灌主 Agent：选重点名单、备选、追问芯片
→ ⑥ 代码组装 brief v2，数字与名称仍从数据库回填
→ ⑦ Writer 流式输出正文，前端在正文后显示追问芯片
```

### 四个名词，全文只按这个口径使用

| 名词 | 定义 |
|---|---|
| **本轮当前需求快照** | 需求解析节点读最近 5 轮完整问答和本轮消息后，对“用户现在到底要什么”的完整判断；不是本轮增量，也不是代码机械合并 |
| **初筛批次** | 一次 `search_targets(count_only=false)` 的真实返回；每批最多 20 家，各批查询独立执行 |
| **深评候选池** | 全部初筛批次按标的 ID 求并集后的候选；去重只在汇总环节发生，最多 40 家 |
| **最终重点名单** | 深评后由主 Agent 从排序结果中选出、交给 Writer 在本轮正文重点介绍的 3–6 家；不是深评候选池本身 |

例：3 次真实初筛各返回 20 家，共有 30 条重复出现，深评候选池就是
`3 × 20 - 30 = 30` 家，这 30 家全部进入深评。

---

## 二、已经拍板的总原则

### 2.1 最近 5 轮原文由需求解析 Agent 自主判断，不由代码合并条件

输入包括：

- 最近 5 轮**已完成且未中止**的用户问题；
- 与之对应的 AI 最终正文（用户真正看到的内容）；
- 本轮用户消息；
- 可筛字段闭集、行业 L1/L2 闭集。

需求解析 Agent 每轮都输出一份**完整的当前快照**：

- “只看上市公司”通常是在上一轮条件上新增上市条件；
- “净利放宽到 500 万”通常是替换上一轮净利门槛，其他条件保留；
- “去掉地区限制”通常是删除地区条件；
- “算了，重新找浙江医疗行业”通常是整体重置；
- 到底是新增、替换、删除还是重置，由需求解析 Agent 根据对话判断。

代码不做条件补丁合并，也不从上一份 JSON 猜用户意图。解析节点输出的完整快照落库后，
就是本轮主 Agent 的唯一条件基线。

### 2.2 每次 SQL 查询独立，去重只在汇总给深评时发生

禁止把前批已返回的 ID 排除出后批 SQL。每次查询都必须如实返回该条件下真正的前 20，
否则会制造“后一个条件组最好的只有 B/C 级”这种假象。

汇总规则：

1. 只收 `count_only=false` 的真实批次；
2. 按标的 ID 求并集；
3. 并集不超过 40 家时全部进入深评；
4. 超过 40 家时，在不同**需求条件组**之间轮询取数，再按首次出现次序稳定去重，直到 40 家；
5. 不允许简单按调用先后截前 40，导致后面的条件组一席都没有。

### 2.3 required 通常不放宽，但是否放宽由主 Agent 根据召回信号判断

`strength=required` 不是代码禁止放宽的锁。正确规则是：

1. 每个条件组第一次正式查询必须带上完整 `required + preferred`；
2. 召回不足时先看 `excluded_by_condition`，优先放宽 preferred；
3. required 通常保留；但如果候选过少，且该条件淘汰项主要是“字段为空”，主 Agent可以放宽；
4. 若主要是“确实不达标”，原则上保留；
5. 明确排除项永不放宽；
6. 所有放宽必须记录原条件、新条件、理由与来源批次；
7. Writer 必须区分“完整条件命中”与“放宽后补充”，不得说成全部满足原要求。

允许的放宽形式：

| 条件类型 | 允许 | 禁止 |
|---|---|---|
| `min_*` / `gte` | 数值降低，或整项移除 | 数值提高后谎称放宽；新增用户未提的字段 |
| `max_*` / `lte` | 数值提高，或整项移除 | 数值降低后谎称放宽 |
| 枚举 / 能力布尔 | 整项移除 | 改成用户没表达过的另一枚举偏好；把 true 翻成 false |
| 地区 / 行业正向条件 | 整项移除，或只使用原快照已有的值 | 自行增加快照外地区/行业 |
| 排除行业 / 排除风险 | 无 | 删除、缩小或换成别的排除项 |

### 2.4 深评结果必须回到主 Agent，不由代码武断取前 5

深评候选池中的全部候选一起进入深评。深评输出 `ranked + dropped` 后回灌主 Agent，
由主 Agent决定：

- 本轮正文重点介绍 3–6 家中的几家；
- 哪些放在备选；
- 哪些候选虽然来自放宽批次，但值得作为“待核实参考”保留；
- 下一轮最有价值的 2–4 个追问方向。

代码只做边界校验：ID 必须来自本轮深评候选池、不得从 `dropped` 里偷偷捞回、数量上限、
数字回填、进度提示与链接回填。代码不替主 Agent做业务选择。

### 2.5 深评是必经阶段，不能由模型忘记调用

对主 Agent 暴露一个受控的 `deep_evaluate_candidates` 工具：

- 只有至少一次真实初筛且候选池非空时才能调用；
- 最多调用一次；
- 调用时工具自己读取候选池与当前需求快照，模型不传候选 ID；
- 调用后冻结筛选阶段，再调用 `search_targets` / `get_target_detail` 直接拒绝；
- 工具返回深评的排序、判定、风险、信息缺口和状态；
- 主 Agent 看到结果后才输出最终 JSON。

硬兜底：如果主 Agent 在有候选时直接给最终 JSON、忘了调深评，handler 不接受该结果；
代码自动跑一次深评，并用同一个 Agent 节点做一次无工具收尾，使 Agent 仍然看到深评结果。
这条要有测试，不能只靠 Prompt 劝告。

---

## 三、动工前 P0：阶段三 Prompt 实际未收口

2026-08-18 只读核查生产 `/model-config/prompts`：

- `recommendation_deep_eval_to_target` 当前默认 `v0.2.0` 仍是旧形态；
- 旧输出是 `results / candidate_id / grade`，没有 `ranked / dropped`；
- 旧变量只有 `mode / anchor_context / candidates_json`，没有
  `qualitative_requirements_json`；
- 阶段三代码会把它判为 `schema_mismatch`，然后继续使用主 Agent 原名单；
- `scripts/publish_deep_eval_v020_prompt.py` 同样把目标版本写成 `v0.2.0`，发现版本已存在就
  `[skip]`，所以新 Prompt 不可能由该脚本发布成功。

4A 必须先做：

1. 新建 `scripts/publish_deep_eval_v030_prompt.py`，版本使用 **v0.3.0**；
2. 沿用阶段三新形态正文与 `ranked / dropped` schema；
3. 版本冲突时若正文/schema 不同必须非零退出并明确报错，禁止无声 skip；
4. `--render-preview` 必须确认四个变量全部替换；
5. 是否 `--apply` 由用户单独决定，未经明确要求不改生产 Prompt；
6. 4B 加入筛选来源与放宽信息后，再发深评 **v0.3.1**。

Prompt 继续走 API，不写迁移。

---

## 四、4A：当前需求快照与基线接线

### 4A.1 历史从 6 轮改为 5 轮

现状：`recommendation_flow.AGENT_HISTORY_MAX_TURNS = 6`。

改为 5，并继续遵守原有不变式：

- 只取已完成轮次；
- 中止轮不带、不计数；
- 带用户问题与 AI 最终正文原文；
- 工具结果、brief、`agent_step`、`agent_understanding`、`agent_deep_eval` 不进历史；
- 超字符预算时按整轮从最旧的丢，绝不截断半轮；
- 继续用 `<history_context>` / `<user>：` / `<AI>：` 明确边界。

更新 `tests/test_recommendation_agent_history.py` 的上限断言。

### 4A.2 需求解析 Prompt v0.3.0：输出本轮完整快照

复用 `recommendation_query_parser`，不建新节点。变量形态不变，Prompt 语义调整：

- `history_context` 是判断当前需求的一部分，不只是指代消歧材料；
- 输出必须代表“用户经过本轮表达后现在要什么”；
- 保留、替换、删除、重置由模型结合历史判断；
- 不允许只输出本轮新增字段；
- 用户说“其他不变”时必须保留历史明确条件；
- 用户明确“重来/重新找/换一个需求”时可以整体重置；
- 仍然不能补用户没表达过的条件；
- `raw_text` 继续由代码回填本轮原话，用于审计，不冒充完整需求文本。

新建受版本控制的发布脚本，版本用 **v0.3.0**；不写 prompt seed 迁移。

### 4A.3 把快照真正注入主 Agent

当前 `agent_context` 只有 `user_message + budgets`。增加：

```json
{
  "intent_snapshot": {
    "condition_groups": [],
    "qualitative_requirements": [],
    "exclusions": {},
    "unstructured_notes": [],
    "parser_status": "ok"
  }
}
```

仍放进现有 `recommendation_context_json`，暂不新增 Agent 节点变量。历史继续走独立
`history_context` 变量，不能塞回 JSON。

### 4A.4 失败语义

- `parser_status=ok`：快照是唯一基线；
- `fallback/schema_mismatch`：原话进入定性诉求，结构化组为空；主 Agent只能做无条件初筛或提问，
  不得因为“解析失败”重新编一份结构化条件；
- 失败不中断本轮，但必须继续落 `agent_understanding` 与 trace；
- 解析后若用户已中止，不进入 Agent 工具循环。

### 4A.5 4A 测试

至少覆盖：

1. 历史只有最近 5 轮；
2. 中止轮不进历史；
3. “只看上市公司”可产出包含上一轮行业/利润条件的完整快照；
4. “净利放宽到 500 万，其他不变”只替换净利门槛；
5. “去掉地区限制”删除地区、保留其他条件；
6. “重新找浙江医疗行业”可以整体重置；
7. `intent_snapshot` 真正进入 Agent prompt 变量；
8. parser 降级时 Agent context 不出现伪造条件；
9. 深评 v0.3.0 发布脚本变量与 NodeSpec 一致；
10. 已存在同版本但内容不一致时发布脚本明确失败，不得 skip。

---

## 五、4B：Agent 编排、候选并集与深评回灌

### 4B.1 新建叶子策略模块

建议新建 `backend/app/services/recommendation_agent_policy.py`，避免把全部规则继续堆进
`recommendation_agent_tools.py`。它只依赖需求快照与 `screening_schema`，不依赖 handler。

建议公开纯函数：

```python
compile_condition_groups(intent_snapshot) -> list[CompiledGroup]
validate_search_call(group_id, conditions, prior_calls) -> ValidatedSearchPlan
build_deep_eval_pool(search_batches, *, limit=40) -> CandidatePool
```

### 4B.2 `search_targets` 增加条件组身份与放宽说明

参数增加：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `group_id` | 是 | 来自当前快照的条件组；无结构化组时使用代码生成的 `fallback-0` 空组 |
| `conditions` | 是 | 本次实际执行的条件 |
| `relaxation_reason` | 放宽时是 | 为什么放宽，必须引用上一次召回量或淘汰拆分 |
| `based_on_call_index` | 放宽时是 | 基于哪一次真实查询作出的放宽 |
| `limit/offset/count_only/note` | 沿用 | 语义不变 |

工具 schema 的 `group_id` 运行时从快照生成 enum，模型填不出不存在的组。

代码验证：

- 每组第一次真实查询必须是完整条件；
- 字段必须来自该组或全局排除项；
- 新值必须等于基线值，或满足 2.3 的单向放宽规则；
- 跨组拼条件拒绝；
- 排除项由代码注入，模型不带也会补上，尝试删除会拒绝；
- 无基线的 fallback 组只允许空条件，不能让主 Agent趁解析失败编条件；
- 无效调用写进 trace，返回结构化错误；是否计入 6 次预算必须固定——**建议计入**，防止模型无限试错。

### 4B.3 候选来源不能只记一个 hit_count

为每个候选维护：

```json
{
  "matched_group_ids": ["group-1", "group-2"],
  "matched_search_call_ids": [1, 3, 4],
  "screening_hits": [
    {
      "call_index": 1,
      "group_id": "group-1",
      "full_conditions": true,
      "applied_conditions": {},
      "relaxed_fields": [],
      "relaxation_reason": null
    }
  ]
}
```

阶段三的 `candidate_hit_counts` 现在每被一次真实查询返回就 `+1`，这会把“同一组完整筛 +
同一组放宽筛”误当成命中两组。4B 改成：

- `group_hit_count = len(matched_group_ids)`；
- `search_hit_count = len(matched_search_call_ids)`；
- 深评排序的强信号使用前者；
- 后者只用于解释“这家在多次策略中都出现过”。

### 4B.4 深评候选池最多 40 家

- 每批 SQL 仍独立返回真实前 20；
- 工具层保存每个真实批次的 ID 顺序；
- 深评调用时再求并集；
- 并集 ≤40 时全部保留；
- 并集 >40 时按不同 `group_id` 轮询取数，同组多个放宽批次内部按调用先后轮询；
- 去重保持稳定；
- trace 记录 `raw_occurrences / unique_before_cap / unique_after_cap / capped`。

### 4B.5 `deep_evaluate_candidates` 受控工具

无业务参数，候选与快照由 executor 内部持有。返回：

- `deep_eval_status`；
- `ranked / dropped / uncovered`；
- 每家定性逐条判定、`fit_points / risks / info_gaps`；
- 每家筛选来源与放宽信息摘要；
- 候选池计数与是否截到 40 家。

调用成功或失败后都冻结筛选阶段。`unavailable/schema_mismatch` 不终止本轮，主 Agent仍可用
SQL 初筛顺序收尾，但必须在最终结果里如实标明降级。

### 4B.6 深评 Prompt v0.3.1

在 v0.3.0 新形态上增加：

- 不再笼统宣称“所有硬条件都已经通过”；
- 逐家读取 `full_conditions / relaxed_fields / screening_hits`；
- 完整条件命中优先于 required 放宽后补充，但不是机械打分；
- 放宽候选不得被写成满足原 required；
- 同时命中多个不同条件组是强信号；同组多次出现只是稳定性信号，不能冒充多方案命中；
- 排除项若命中仍应 dropped；
- 定性逐条判定闭集不变。

### 4B.7 主 Agent Prompt v0.2.0

核心变化：

- 不再负责从原话重新解析需求；只读 `intent_snapshot`；
- 每个组先完整查询，再根据真实信号决定是否放宽；
- `count_only` 只能试探，不能进入候选池；
- 最少一次真实初筛；
- required 可判断后放宽，不是绝对禁止；
- 排除项永不放宽；
- 筛选完成后必须调用 `deep_evaluate_candidates`；
- 看到深评后再输出重点名单、备选与追问建议；
- 不允许在深评前给最终名单；
- 最终 ID 只能来自 `ranked`，不能来自 `dropped` 或候选池外；
- 数字仍不由模型输出。

### 4B.8 4B 测试

至少覆盖：

1. 组外字段、跨组拼接、新增值被代码拒绝；
2. 每组第一次真实查询不是完整条件时拒绝；
3. preferred 合法移除；
4. required 在召回不足后合法放宽，并记录依据；
5. `min_*` 只能降低、`max_*` 只能提高；
6. 排除条件无法删除；
7. fallback 空组无法编条件；
8. 3×20、30 条重复 → 30 家全部进深评；
9. 并集 >40 时不同条件组都有席位，且稳定可复现；
10. 同一组两次命中：`group_hit_count=1`、`search_hit_count=2`；
11. 两个不同组命中：`group_hit_count=2`；
12. 只做 count_only 不得形成候选池；
13. 没有真实候选时不能调用深评；
14. 深评最多一次，调用后不能再筛；
15. Agent 忘调深评时由代码补跑并做无工具收尾；
16. 深评 unavailable/schema_mismatch 时本轮继续，但状态不伪装成 ok；
17. 中止发生在深评前后均不生成最终 brief。

---

## 六、4C：最终素材包 v2、Writer 与追问芯片

### 4C.1 主 Agent 最终输出契约

```json
{
  "understanding": "一句话复述本轮当前需求，不写数字结论",
  "recommended_ids": ["深评 ranked 里的 id，3-6 家"],
  "runner_up_ids": ["深评 ranked 里未进入重点名单的 id，最多 5 家"],
  "selection_notes": {
    "id": "为什么作为重点或备选，只谈定性判断与放宽状态"
  },
  "follow_up_suggestions": ["2-4 条可直接作为下一轮用户消息发送的短句"]
}
```

代码归一：

- `recommended_ids` 只认深评 `ranked`；
- 数量 3–6，候选不足 3 家时按实有数量；超过 6 截断并记 notes；
- `runner_up_ids` 不能与重点名单重复，不能来自 dropped；
- 编造 ID 丢弃并记 trace；
- 若深评降级，允许从代码持有的候选池按主 Agent 原始输出收尾，但必须标
  `selection_source=agent_fallback`；
- Agent 输出的名称、facts、数字一律不采纳。

### 4C.2 brief v2

```json
{
  "mode": "buyer_to_target",
  "intent_summary": "代码依据本轮当前需求快照渲染",
  "parser_status": "ok",
  "selection_source": "deep_eval|agent_fallback|screening_fallback",
  "deep_eval_status": "ok",
  "candidate_pool_count": 30,
  "candidate_pool_capped": false,
  "screening_runs": [],
  "recommended": [
    {
      "id": "…",
      "name": "数据库名称",
      "facts": {},
      "qualitative_verdicts": {},
      "reason_points": [],
      "risks": "…",
      "info_gaps": "…",
      "screening_hits": [],
      "matched_full_conditions": true,
      "relaxed_fields": [],
      "already_in_progress": null,
      "other_buyer_in_deep_progress": false
    }
  ],
  "runner_ups": [],
  "follow_up_suggestions": []
}
```

删除旧 `total_eligible` 口径。多组、多次放宽时，“最后一次 matched”不是全局符合数，
Writer 不得拿它写“总共符合 N 家”。

### 4C.3 Writer Prompt v0.2.0

复用 `recommendation_answer_writer_to_target`，不建新节点。必须写死：

- 只读 brief v2；
- 开头复述的是 `intent_summary`；
- 可以说“本轮汇总了 N 家去重候选”，不能说“全库共有 N 家符合”；
- 明确区分完整条件命中与放宽后补充；
- required 放宽候选必须写“需核实/供参考”，不能写成完全满足；
- 原始数字只引用 `facts`；
- 深评理由来自 `reason_points / qualitative_verdicts / risks / info_gaps`；
- 不展示深评等级或分数；
- 不写 ID、URL、Markdown 链接；名称链接继续由代码回填；
- 不把 `follow_up_suggestions` 改写进正文末尾，追问只由芯片承载；
- `other_buyer_in_deep_progress` 只说“正与其他买家深入推进”，不透露对方；
- 400–800 字只是参考，候选少时不要灌水。

### 4C.4 规则兜底文案同步

`fallback_answer_markdown` 必须与 Writer 同口径：

- 不再读取 `total_eligible`；
- 使用 `candidate_pool_count`；
- 展示深评 reason/risk/gap；
- 标出放宽项；
- 不把追问芯片写进正文；
- 没有重点候选时给出诚实的“按当前条件未形成可推荐名单”，而不是空列表。

### 4C.5 追问芯片

前端基础设施已经存在：`AgentTurnView` 会在正文完成后显示 `followUps`，点击等于发送该句。
不新建第二套组件，只收口数据契约与交互。

生成规则：

- 2–4 条；每条短句、去重、不得为空；
- 点击后直接成为下一轮用户消息；需求解析节点会结合最近 5 轮问答生成新的完整快照；
- 优先覆盖：细看重点标的、恢复/继续放宽某条件、收窄行业/地区、再看下一批；
- 可以引用最终名单里的真实标的名称，不能输出 ID 或链接；
- 不承诺超过预算的“列出全部 56 家”，使用“再看下一批候选”；
- 如果没有可靠建议，允许少于 2 条或为空，不为凑数编建议；
- 中止、失败、澄清态不显示追问芯片；
- 恢复历史会话时从落库 brief 重建相同芯片。

### 4C.6 4C 测试

至少覆盖：

1. 深评 30 家，Agent 选 4 家，brief 只重点写这 4 家；
2. Agent 编造 ID、选 dropped ID 均被丢弃并留 notes；
3. 推荐数上限 6、备选上限 5；
4. 名称与数字来自代码，不来自模型；
5. 放宽 required 的候选带完整来源并被 Writer 明示；
6. `total_eligible` 从新 brief 与兜底文案消失；
7. Writer Prompt 不把追问写进正文；
8. 芯片 2–4 条、去重、长度限制、点击直接发送；
9. “再看下一批”不会承诺列出超预算全集；
10. 恢复会话后芯片不丢；
11. Writer 未配置/流式失败时规则兜底仍可用；
12. 链接回填与复制纯文本行为不回归；
13. 中止轮不显示正文和芯片。

---

## 七、4D：端到端验收与生产收口

### 4D.1 提示词版本

| 节点 | 目标版本 | 说明 |
|---|---|---|
| `recommendation_query_parser` | **v0.3.0** | 最近 5 轮驱动的完整当前需求快照 |
| `recommendation_deep_eval_to_target` | **v0.3.1** | 新 schema + 筛选来源/放宽信息；v0.3.0 是4A过渡收口 |
| `recommendation_agent_to_target` | **v0.2.0** | 只编排，不重新解析；深评后选最终重点名单与芯片 |
| `recommendation_answer_writer_to_target` | **v0.2.0** | brief v2；放宽说明；追问不进正文 |

全部通过 API 发布，不写迁移。每一份必须先：

1. 本地变量集合测试；
2. `/model-config/prompts/render-preview`；
3. 确认双花括号全部替换；
4. 确认版本不存在；若存在但内容不同必须报错；
5. 得到用户明确许可后才 `--apply`。

### 4D.2 真实 UAT 用例

至少跑以下 8 组：

| # | 对话 | 验收重点 |
|---:|---|---|
| 1 | `江苏制造业，净利1000万以上` | 完整快照、一次完整初筛、无编条件 |
| 2 | 接着说 `只看上市公司` | 新快照保留上一轮条件并新增上市 |
| 3 | 接着说 `净利放宽到500万，其他不变` | 只替换净利阈值 |
| 4 | 接着说 `去掉地区限制` | 删除地区，其他保留 |
| 5 | `机器人/AI行业，上市看市值和PE，非上市看营收` | 两组独立初筛、并集去重、组命中计数正确 |
| 6 | 条件过严导致少量召回 | Agent依据 marginal 拆分放宽；正文区分原命中与补充候选 |
| 7 | 带定性诉求 `最好有成熟海外仓、与现有业务有协同` | 深评逐条判定，主 Agent在深评后选名单 |
| 8 | 点击 `再看下一批候选` 或细看某家芯片 | 下一轮历史语义正确，芯片可执行 |

每轮查：

- `agent_understanding`：完整当前快照；
- `agent_step`：完整条件与放宽理由；
- `agent_deep_eval`：候选池、定性判定、来源；
- `agent_brief`：最终 3–6 家、selection source、芯片；
- `ai_trace`：解析、筛选、深评状态与预算；
- 页面正文：数字、放宽说明、推进提示、链接与复制行为。

### 4D.3 失败与中止矩阵

| 故障点 | 期望 |
|---|---|
| 需求解析 unavailable | 空结构化基线 + 原话定性兜底；Agent不得编条件 |
| 需求解析 schema_mismatch | 同上，状态响 |
| Agent 非法筛选参数 | 工具拒绝、trace 留痕、允许预算内纠正 |
| 深评 unavailable | 不阻断本轮，标 `agent_fallback` |
| 深评 schema_mismatch | 不伪造排序，标 `agent_fallback` |
| Agent 忘调深评 | 代码补跑并做一次无工具收尾 |
| Writer 未配置/超时 | 规则兜底正文 |
| 用户任一点停止 | `agent_aborted` 优先；不续接、不重试、不生成后续正文/芯片 |
| SSE 中途关页 | 恢复时补连并落库，芯片随 brief 恢复 |

### 4D.4 测试与部署

本地：

```bash
python -m pytest -q
cd frontend
npm run typecheck
npm run build
npm run lint
```

未经用户明确要求，不要 commit、不要 push。推 `main` 等于 Railway 生产部署。

用户批准发布后：

1. `git push origin main`；
2. 轮询 `/api/v1/health`，确认 `git_commit_sha` 切到新提交；
3. 按 4D.1 顺序发布并 render-preview 四份 Prompt；
4. 跑 4D.2 UAT；
5. 自建环境只有用户要求时才执行拉取部署；推 Railway 不会自动更新自建；
6. 把结论合并回 `docs/系统总纲.md` §3.3。

---

## 八、文件改动建议

| 文件 | 施工包 | 预期改动 |
|---|---|---|
| `backend/app/services/recommendation_flow.py` | 4A | 历史轮数 6→5 |
| `backend/app/services/recommendation_conditions.py` | 4A | 完整当前快照语义与描述，不改白名单底座 |
| `backend/app/jobs/handlers/recommendation.py` | 4A/4B/4C | 注入快照、深评回灌、最终 brief v2、trace |
| `backend/app/services/recommendation_agent_policy.py`（新） | 4B | 条件组编译、放宽校验、候选池汇总 |
| `backend/app/services/recommendation_agent_tools.py` | 4B | group_id、来源记录、深评工具、冻结状态 |
| `backend/app/services/recommendation_deep_eval.py` | 4B | 筛选来源与放宽信息进入深评 |
| `backend/app/services/recommendation_answer.py` | 4C | brief v2 与规则兜底 |
| `backend/app/registry/nodes.py` | 4A/4B/4C | 节点说明、运行时输入与 Prompt 变量校准 |
| `frontend/src/types/api.ts` | 4C | brief v2 / 芯片类型 |
| `frontend/src/pages/Recommend.tsx` | 4C | 恢复与芯片契约适配，避免重做组件 |
| `frontend/src/features/recommend/AgentTurnView.tsx` | 4C | 原组件最小调整与状态边界 |
| `scripts/publish_*prompt.py` | 4A/4B/4C | 四份可审计 Prompt 发布脚本 |
| `tests/test_recommendation_agent_history.py` | 4A | 最近 5 轮 |
| `tests/test_intent_parse_result.py` | 4A | 多轮完整快照 |
| `tests/test_recommendation_agent_tools.py` | 4B | 条件边界、并集、来源、深评工具 |
| `tests/test_recommendation_deep_eval_node.py` | 4A/4B | Prompt 收口与来源输入 |
| `tests/test_recommendation_agent_turn.py` | 4B/4C | 深评后收尾与 brief v2 |
| `tests/test_recommendation_answer_stream.py` | 4C | Writer/fallback/链接/复制 |
| 前端推荐页测试 | 4C | 芯片显示、点击、恢复、中止 |
| `docs/系统总纲.md` | 4D | 最终链路回填 |

文件名可以因实际模块边界微调，但不得把策略纯函数塞进 API route，或让叶子服务 import handler。

---

## 九、明确不要做的

- 不建新的需求解析、深评、Agent 或 Writer 节点；复用现有四个节点。
- 不写 prompt seed 迁移；Prompt 走 API。
- 不做条件面板；业务方已经确认不需要。
- 不做反向“为标的找买家”。
- 不做 owner_scope 权限过滤，本轮沿用跨负责人召回。
- 不把全库或完整候选画像塞进主 Agent 历史；完整画像只给深评干净上下文。
- 不让 Writer 或主 Agent决定数字；数字继续由代码 facts 回填。
- 不把不同初筛批次在 SQL 层去重。
- 不把同一组多次命中冒充多方案命中。
- 不把 required 放宽候选写成完全满足原条件。
- 不把追问建议重复写进正文。
- **不动旧 `/candidates` 打分链路、旧深评分片、rerank、旧增量条件操作。**
  它们全部留到阶段五统一拆除。

---

## 十、阶段四完成判据

全部满足才算完成：

1. 需求解析读最近 5 轮并产出完整当前快照；
2. 主 Agent实际收到该快照，不能编造组外条件；
3. 完整查询先于放宽，required 的放宽有真实依据与可见记录；
4. 多批次结果只在汇总时去重，≤40 全进深评，>40 公平收口；
5. 深评看到每家来自哪些组、哪些调用、放宽了什么；
6. 深评结果回到主 Agent，主 Agent从 ranked 中选 3–6 家；
7. brief v2 不再使用误导性的 `total_eligible`；
8. Writer 正确区分原条件命中与放宽后补充；
9. 追问芯片在正文后可点击、可恢复、不重复进正文；
10. parser/deep eval/agent/writer 四种失败均有降级，不静默；
11. 中止不变式未回归；
12. 全量后端测试、前端 typecheck/build/lint 全绿；
13. 真实 UAT 通过并留证；
14. `docs/系统总纲.md` 已回填；
15. 只有以上全部完成，阶段五才允许拆旧链路。

---

## 十一、施工记录

> 由 4A–4D 的开发对话逐包追加。每包至少记录：提交/工作树状态、改动文件、测试结果、
> Prompt 版本与 render-preview、未完成项、给下一包的接口说明。不要把施工记录另起一份会漂移的文件。

### 4A 施工记录（2026-08-18）

#### 基线与工作树

- 开始核查：分支 `main`，HEAD `d7bdb0d6313f1ccff89a141a1ea31acac9479511`
  （`d7bdb0d feat: 深评节点接管定性诉求，逐条判定后重排序`）。工作树原本已脏：
  `推荐升级阶段二施工单_需求解析节点0817.md` 有用户未提交修改，另有 `.claude/`、UAT 表、
  阶段一至四施工文档等未跟踪文件；阶段四总施工单本身也是未跟踪的用户文件。
- 冲突处理：本包只在本总施工单末尾定点追加记录；没有改动阶段二施工单，也没有
  reset / checkout / stash / clean / pull。用户原有修改全部保留。
- 结束核查（2026-08-18 01:52 -07:00）：仍在 `main`，HEAD 仍为 `d7bdb0d`；工作树保持脏，
  新增的 4A 修改均未提交。未 commit、未 push、未部署。

#### 实际改动与关键接口

- `backend/app/services/recommendation_flow.py`
  - `AGENT_HISTORY_MAX_TURNS` 从 6 改为 5；原有“已完成双边问答才算一轮、中止整轮剔除、
    只带用户问题和最终正文、超预算从最旧整轮丢弃、标签边界不截断”实现保持不变。
- `backend/app/services/recommendation_conditions.py`
  - 更新契约说明：`parse_recommendation_intent` 读最近已完成问答与本轮消息，模型自主判断
    保留 / 新增 / 替换 / 删除 / 整体重置，代码只归一化完整结果，不机械累计上一份 JSON；
    `raw_text` 继续由代码回填本轮原话。
- `backend/app/jobs/handlers/recommendation.py`
  - 新增 `_build_recommendation_agent_context()`；现有 `recommendation_context_json` 真正带入
    `intent_snapshot`，字段为 `condition_groups / qualitative_requirements / exclusions /
    unstructured_notes / parser_status`。
  - `parser_status=ok` 时保留解析快照为唯一结构化基线；`fallback/schema_mismatch` 时在进入
    主 Agent 前再次清空条件组与排除项，只把本轮原话放入定性兜底，即便异常 fallback 载荷
    夹带条件也不会冒充基线。
  - 同一 JSON 增加 `intent_snapshot_policy`，明确禁止主 Agent 自创结构化条件，解析失败时
    只允许无条件初筛或提问。历史仍只通过独立 `history_context` 变量传入，没有塞回 JSON。
  - 原有解析后中止检查保留在工具循环之前；原有 `agent_understanding` 即时落库与 trace
    `intent_parser` 摘要路径保持不变。
- `backend/app/registry/nodes.py`
  - 两个节点的运行时输入和变量说明从最近 6 轮校准为最近 5 轮；主 Agent 运行时输入补上
    “完整当前需求快照”。没有新增节点或 Prompt 变量。
- `scripts/prompt_publish_utils.py`（新）
  - 公共安全检查：Prompt 双花括号变量集合必须与 NodeSpec 完全一致；服务端同版本若系统正文、
    用户正文、schema 或变量集合不同，抛 `PromptVersionConflict`；render-preview 后若还有变量
    字面量或任一变量未注入，非零退出。
- `scripts/publish_query_parser_v030_prompt.py`（新）
  - `recommendation_query_parser` v0.3.0；6 个变量保持 NodeSpec 原集合不变；正文明确最近 5 轮、
    完整当前快照、其他不变、指定删除、条件替换、整体重置、不得补条件与 `raw_text` 审计语义。
- `scripts/publish_deep_eval_v030_prompt.py`（新）
  - `recommendation_deep_eval_to_target` v0.3.0；四变量与 NodeSpec 一致；输出使用阶段三新形态
    `ranked / dropped / qualitative_verdicts`，不评级、不打分、不分片。它是 4A 过渡版，
    没有提前加入 4B 的条件组来源与放宽信息。
- `docs/系统总纲.md`
  - 只同步本包已经生效的历史上限 6→5 与中止轮“不计入 5 轮”；阶段四最终链路仍按 4D 回填。
- 测试：更新 `tests/test_recommendation_agent_history.py`、`tests/test_intent_parse_result.py`、
  `tests/test_recommendation_agent_turn.py`、`tests/test_recommendation_deep_eval_node.py`，覆盖 4A.5
  十项及两份脚本的非零冲突退出。

#### 测试与 Prompt 验证（真实结果）

- 测试先行红灯：首次运行 4 个相关测试文件时，因尚无
  `_build_recommendation_agent_context` 收集失败（1 error），随后实现。
- 相关回归：
  `python -m pytest -q tests/test_recommendation_agent_history.py tests/test_intent_parse_result.py
  tests/test_recommendation_agent_turn.py tests/test_recommendation_deep_eval_node.py`
  → 最终 `111 passed in 2.39s`（含“解析后中止不进入工具循环”回归）。
- 全量回归：`python -m pytest -q`
  → 最终 `1106 passed, 36 skipped, 5 warnings in 12.12s`；5 条均为既有 Starlette
  `HTTP_422_UNPROCESSABLE_ENTITY` 弃用警告，无失败。
- `python scripts/publish_query_parser_v030_prompt.py --check`
  → 变量与 NodeSpec 一致：
  `mode / user_message / history_context / screening_fields_json / industry_l1_list / industry_l2_list`。
- `python scripts/publish_deep_eval_v030_prompt.py --check`
  → 变量与 NodeSpec 一致：
  `mode / anchor_context / candidates_json / qualitative_requirements_json`。
- 两份脚本 `--dry-run`：只读查询确认生产均不存在 v0.3.0，均显示“将创建并设为默认”；
  没有写入。
- 两份脚本 `--render-preview`：服务端端点均返回成功；query parser 6/6、deep eval 4/4
  双花括号变量全部替换，渲染结果无未解析变量。该端点只渲染草稿，没有写 Prompt。
- **未运行任何 `--apply`。** query parser v0.3.0 与 deep eval v0.3.0 都只是受版本控制的脚本，
  尚未应用生产；没有伪造生产 Prompt 验证结果。

#### 4B 可依赖的接口、遗留与风险

- 4B 可直接从 handler 持有的 `intent_snapshot`，或从
  `recommendation_context_json.intent_snapshot` 读取同一套五字段安全快照；失败状态进入
  Agent 前已经是空结构化基线。`history_context` 继续是独立变量，不需迁移接口。
- `_build_recommendation_agent_context()` 是主 Agent 注入边界；4B 的
  `compile_condition_groups / validate_search_call` 可在此契约之上工作，不必再次解析用户原话。
- 4A 只用上下文策略声明“不得编条件”。按本单边界，组外字段、第一次完整查询、单向放宽、
  fallback 空组等**工具层硬校验仍属于 4B**，不得把本记录误读为已经完成 4B。
- 生产仍在使用 query parser v0.2.0 和冲突的 deep eval v0.2.0；在用户明确授权执行两份
  v0.3.0 脚本的 `--apply` 前，生产多轮快照语义不会切换，deep eval 仍可能
  `schema_mismatch`。这是未授权发布导致的预期遗留，不是本地代码阻塞。
- v0.3.0 同版本若已被其他人以不同内容创建，脚本会明确报出差异并以退出码 2 结束，
  不覆盖、不 skip；需要人工核查并改用新版本号。

#### 用户授权后的生产发布补记（2026-08-18 02:29 -07:00）

- 用户在 4A 完工交接后明确授权推送与配置最新 Prompt。代码提交
  `88d4366ae230a73b8a937b1a91a59fe69961bed7` 已推送 `origin/main`；Railway 生产
  `/api/v1/health` 已返回该完整 `git_commit_sha` 后才开始应用 Prompt。
- 已执行 `python scripts/publish_query_parser_v030_prompt.py --apply`：创建并启用默认
  `recommendation_query_parser v0.3.0`，Prompt id
  `e342602b-0c02-40af-b8f5-dd63942ef39f`。
- 已执行 `python scripts/publish_deep_eval_v030_prompt.py --apply`：创建并启用默认
  `recommendation_deep_eval_to_target v0.3.0`，Prompt id
  `a22f34a1-48a8-4a5c-976d-17d55ed01efc`。
- 应用后重新执行两份脚本的 `--dry-run`：均返回 `exists-identical`，确认服务端正文、schema、
  变量集合与仓库脚本一致；重新执行 `--render-preview`：query parser 6/6、deep eval 4/4
  变量全部替换，无双花括号残留。
- 只读查询 `/model-config/prompts` 确认两个 v0.3.0 均为各自节点唯一
  `is_default=true` 且 `is_active=true` 的 Prompt。没有部署自建环境；本次推送只触发 Railway。

### 4B 施工记录（2026-08-18）

#### 基线、4A 验收与工作树

- 开工分支 `main`，HEAD `ba05e8a5033c7b7b0fa02550d157dd166a87eb9e`
  （`ba05e8a docs: 记录4A生产发布`）。先完整阅读 `AGENTS.md`、系统总纲、本施工单、4A
  施工记录与实际源码/测试/发布脚本，再读设计框架；没有 pull / reset / checkout / stash / clean。
- 开工前实际执行 4A 相关回归：
  `python -m pytest -q tests/test_recommendation_agent_history.py tests/test_intent_parse_result.py
  tests/test_recommendation_agent_turn.py tests/test_recommendation_deep_eval_node.py`
  → `111 passed in 2.33s`。由源码与测试确认最近 5 轮、query parser v0.3.0 完整当前快照、
  `intent_snapshot` 注入与 deep eval v0.3.0 脚本闭环均已存在，4B 才开始施工。
- 工作树原有用户资产保持不动：阶段二施工单的既有修改以及 `.claude/`、UAT 表、其他施工文档等
  未跟踪文件均未清理或覆盖。本总施工单已随 4A 提交纳入跟踪，本包只在第十一节末尾追加本记录。
- 结束核查（2026-08-18 03:01 -07:00）：仍在 `main`，HEAD 仍为 `ba05e8a`；本包修改均未提交。
  未 commit、未 push、未部署、未发布生产 Prompt。

#### 实际代码与接口

- `backend/app/services/recommendation_agent_policy.py`（新叶子模块）
  - `compile_condition_groups()` 生成稳定的 `group-1...`；空/降级快照只生成 `fallback-0` 空组。
    行业与重大风险排除编译为全组代码注入项。
  - `validate_search_call()` 强制组内字段、每组首次真实查询完整基线、preferred/required 放宽依据、
    `min_*` 只降 / `max_*` 只升、枚举/能力/行业/地区不得换新值、排除项不可删除。
    required 只有所引用的同组真实调用召回不超过 5 家时才允许 Agent 作放宽判断；无效调用返回
    结构化错误并由 executor 计入 6 次筛选预算。
  - `build_deep_eval_pool()` 只汇总有效的非 `count_only` 批次；保留每批原始 ID 顺序；先按 ID 求
    并集，超过 40 时先跨 `group_id` 轮询、同组再按批次调用先后轮询，稳定公平收口。
- `backend/app/services/recommendation_agent_tools.py`
  - `search_targets` schema 新增必填 `group_id`，放宽时使用 `relaxation_reason /
    based_on_call_index`；运行时 enum 只含当前快照生成的组 id。
  - 每个真实批次记录 `candidate_ids / full_conditions / relaxed_fields / excluded_by_condition` 与
    放宽依据；SQL 仍独立执行，没有任何“排除前批 ID”的参数。
  - 候选来源改为 `matched_group_ids / matched_search_call_ids / screening_hits /
    group_hit_count / search_hit_count`，不再用一个含义混淆的 `candidate_hit_counts`。
  - 新增无业务参数的 `deep_evaluate_candidates`。只有真实候选池非空才可调用；成功、
    `unavailable` 或 `schema_mismatch` 后都冻结 `search_targets / get_target_detail`，全程最多一次。
    trace 带 `raw_occurrences / unique_before_cap / unique_after_cap / capped` 及策略拒绝记录。
- `backend/app/services/recommendation_deep_eval.py`
  - 深评输入逐家带 `full_conditions / relaxed_fields / screening_hits` 以及分开的 group/search hit；
    anchor 不再谎称每家都通过完整硬条件。
  - 结果元数据使用 `candidate_group_hit_counts / candidate_search_hit_counts`；executor 再把完整
    筛选来源并回 `ranked / dropped`。降级无 ranked 时返回候选来源映射，供主 Agent 按 SQL 顺序收尾。
- `backend/app/jobs/handlers/recommendation.py`
  - Agent context 新增代码生成的 `search_group_catalog`，但 4A 的降级 `intent_snapshot` 仍保持空结构化组；
    工具执行器只拿这份安全快照，不能利用异常 fallback 载荷编条件。
  - 深评从 handler 旁路改为主 Agent 可见工具。Agent 忘调时，代码自动补跑一次，再把完整深评结果
    放回同一 Agent 节点做一次 `tools=None` 无工具收尾；不把深评机械截成前 5。
  - 深评前、深评期间、深评后无工具收尾三个边界都重新检查 `agent_aborted`；任何中止都只留 trace，
    不写 `agent_brief`。深评降级不终止本轮，也不把状态伪装为 ok。
- `backend/app/registry/nodes.py`：只校准现有两个节点的运行时说明，没有新建节点或 Prompt 变量。
- 测试：新增 `tests/test_recommendation_agent_policy.py`；更新
  `tests/test_recommendation_agent_tools.py`、`tests/test_recommendation_deep_eval_node.py`、
  `tests/test_recommendation_agent_turn.py`，覆盖 4B.8 的 17 项，包括 3×20/30 重复得到 30、
  >40 公平稳定、组命中与搜索命中分离、required 正反例、排除注入、count_only、深评一次/冻结、
  忘调自动补跑、两种深评降级和深评前后中止。

#### Prompt v0.3.1 / v0.2.0（未 apply）

- `scripts/publish_deep_eval_v031_prompt.py`（新）：复用
  `recommendation_deep_eval_to_target`，目标 **v0.3.1**；正文要求逐家读取完整/放宽来源，
  区分 group/search hit，放宽 required 不得写成完整满足，排除命中进入 dropped。
- `scripts/publish_recommendation_agent_v020_prompt.py`（新）：复用
  `recommendation_agent_to_target`，目标 **v0.2.0**；只读快照与组目录，每组先完整真实筛，
  放宽必须引用真实信号，深评后才输出重点/备选/追问，ok 时 ID 只能来自 ranked。
- 两份脚本均复用 `prompt_publish_utils` 的变量完全一致校验、同版本内容冲突非零失败与
  render-preview 残留检查。没有写 seed 迁移，没有新建节点。
- 本地检查：deep eval 变量 4/4（`mode / anchor_context / candidates_json /
  qualitative_requirements_json`），main Agent 变量 2/2（`recommendation_context_json /
  history_context`），均与 NodeSpec 完全一致。
- 两份脚本 `--dry-run` 只读确认服务端尚无目标版本，均显示“将创建并设为默认”；两份
  `--render-preview` 均成功，分别替换 4/4、2/2 变量，无未解析双花括号。**未执行 `--apply`**。

#### 测试结果

- 4B 相关回归（policy/tools/deep eval/agent turn，加 4A parser/history）最终一轮：
  `159 passed in 1.97s`；后续小修继续由全量回归覆盖。
- 全量最终回归：`python -m pytest -q`
  → `1132 passed, 36 skipped, 5 warnings in 15.59s`。5 条仍是既有 Starlette
  `HTTP_422_UNPROCESSABLE_ENTITY` 弃用警告，无失败。
- `git diff --check` 无空白错误，仅 Windows 工作树既有 LF→CRLF 提示。

#### 给 4C 的准确接口与边界

- 深评落库/工具结果：`deep_eval_status`（`ok | unavailable | schema_mismatch`）、`ranked / dropped /
  uncovered / notes / fallback_reason`、`candidate_pool`（四项计数）、`auto_invoked`。`ranked` 与
  `dropped` 每项除定性判定、`fit_points / risks / info_gaps` 外，还带
  `matched_group_ids / matched_search_call_ids / group_hit_count / search_hit_count / screening_hits`；
  深评降级时顶层 `candidate_sources` 保存同样来源，按映射插入序即公平收口后的 SQL 初筛顺序。
- 主 Agent 最终原始输出：仍是 v0.2.0 的 `understanding / deep_eval_status / recommended /
  runner_ups / follow_up_suggestions`，保存在本轮 `ai_trace.parsed_output_json`，随后进入现有
  `_build_answer_brief()`。4B 只保证 Agent 真正看过深评；3–6 家严格归一、ranked/dropped ID
  代码校验、brief v2 与 Writer 接线仍由 4C 完成。
- 候选来源：每个 `screening_hit` 精确给出 `call_index / group_id / full_conditions /
  applied_conditions / relaxed_fields / relaxation_reason / based_on_call_index`；同组多批只增加
  `search_hit_count`，跨组才增加 `group_hit_count`。
- 降级语义：`unavailable/schema_mismatch` 都冻结筛选但不中断本轮，主 Agent 能看到状态与公平候选
  顺序并降级收尾；不得把状态改成 ok。没有真实候选时深评工具返回结构化拒绝且不消耗唯一一次深评。
- 中止语义：深评前中止不调用深评；深评进行中或完成后中止可以在 trace 留下已发生工作，但绝不生成
  `agent_brief`，因此 SSE/Writer 没有后续正文或芯片可生成。`agent_aborted` 继续拥有最高优先级。

#### 用户授权后的 4B 生产发布补记（2026-08-18 03:15 -07:00）

- 用户在 4B 完工交接后明确授权推送与更新生产 Prompt。4B 代码提交
  `7b08467b641fe459ada5c8456286647855a3c471` 已推送 `origin/main`；Railway 生产
  `/api/v1/health` 已返回该完整 `git_commit_sha` 后才开始应用 Prompt。
- 已执行 `python scripts/publish_deep_eval_v031_prompt.py --apply`：创建并启用默认
  `recommendation_deep_eval_to_target v0.3.1`，Prompt id
  `44bfd504-f7ae-4ad2-b63b-00a4a75767a9`。
- 已执行 `python scripts/publish_recommendation_agent_v020_prompt.py --apply`：创建并启用默认
  `recommendation_agent_to_target v0.2.0`，Prompt id
  `55e23371-2a37-4e45-823d-95f4c6085ed1`。
- 应用后重新执行两份脚本的 `--dry-run`：均返回 `exists-identical`，确认服务端正文、schema、
  变量集合与仓库脚本一致；重新执行 `--render-preview`：deep eval 4/4、main Agent 2/2
  变量全部替换，无双花括号残留。
- 只读查询 `/model-config/prompts` 确认 v0.3.1 与 v0.2.0 均为各自节点
  `is_default=true` 且 `is_active=true` 的 Prompt。没有部署自建环境；本次推送只触发 Railway。
