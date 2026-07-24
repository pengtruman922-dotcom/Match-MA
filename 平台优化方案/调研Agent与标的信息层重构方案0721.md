# 调研 Agent 与标的信息层重构方案（2026-07-21）

> 本方案是 `推荐准确性优化方案0720.md`（下称"0720 方案"）的**增补与局部修订**，不是替代。
> 0720 方案 §1–§11、§13–§16 全部继续有效，未作任何改动。
> 本方案只推翻并重写 0720 方案 **§12（调研 Agent）**，并新增两块 0720 方案没有涉及的内容：
> **标的信息层的页面重构** 和 **画像变更的审计链路**。

---

## 0. 本方案与 0720 方案的关系

### 0.1 继续有效，不复议

0720 方案的以下结论保持不变，本方案基于它们展开：

| 章节 | 内容 |
|---|---|
| §2 | 指标体系（MECE 九轴） |
| §3 | 价格两轴（企业价值 C-a / 交易对价 C-b） |
| §4 | 两条通用判定规则（要求×能力矩阵、数值区间） |
| §5 | 闭集设计 |
| §6 | 行业字典三层分工 |
| §7 | 多方案条件模型（全局 AND（方案 OR）） |
| §8 | 召回与三态判断（compatible / possible / conflict） |
| §9 | 信息缺失与匹配度拆分（乐观分 + 已知条件数二级排序） |
| §10 | 深评协议（一次深评、按 candidate_id 回写、分片并发） |
| §11 | 匹配画像六栏 + 每栏字符预算 + 三态 info_status |
| §13 | Golden Set（口径仍由业务侧设计） |
| §16 | 实施顺序（批次 1–5 已完成） |

**画像六栏的定义（§11）不变**：`business_product` / `chain_position` / `tech_team` / `ops_quality` / `deal_terms` / `sell_intent_risk`。本方案只改变它们**怎么被填充**和**怎么被展示**。

### 0.2 本方案取代的部分

**0720 方案 §12 整节作废**，由本方案 §2 取代。

作废的具体设计：

| 0720 §12 原设计 | 现状 | 本方案 |
|---|---|---|
| §12.4-1 实体锚点硬闸门："证据原文须包含锚点特征才采信" | 已实现，且已因过严被迫放宽 | **删除**。见 §2.7 决策记录 |
| §12.4-2 无痕标的："记录下次重试时间" | 已实现，但从未被读取 | **改为前端二次确认**，见 §5 |
| §12.3 四分类由代码判定 | 已实现为字符串相等比较 | **四分类保留为输出字段，判定者改为 LLM**，见 §2.4 |
| §12.3 来源优先级链驱动自动写入 | 已实现为 `HIGH_AUTHORITY_SOURCE_TYPES` | **简化**，见 §2.5 |
| 固定三组检索词 + 证据总量计数器 | 已实现，且有缺陷（见 §6-E） | **删除**，改由 agent 自主决策，见 §2.2 |

### 0.3 本方案新增的部分

0720 方案完全没有涉及、由本轮实测暴露出来的：

- **§3 标的信息层页面重构**：基本信息 tab 字段残缺 + 匹配画像独立成 tab，两者割裂
- **§4 画像变更进入更新记录**：自动采纳的画像目前不可见、不可回滚
- **§6 现存缺陷清单**：10 项已定位的代码缺陷，含 2 项阻断性问题

---

## 1. 为什么推翻 §12 的调研设计

已实现的版本（提交 `133edd3`、`eb7bf57`）是一条**伪装成 agent 的固定流水线**：

```
代码写死 3 组检索词 → 代码调搜索 → 代码用字符串匹配过滤页面
→ 把过滤后的证据一次性塞给 LLM → LLM 写一段总结 → 代码判断冲突类型
```

LLM 在全程中没有任何决策权，只是最后一步的格式化器。由此产生的问题不是实现 bug，是架构后果：

1. **不能转向**。第一次搜索发现标的是某上市公司子公司时，正确动作是改搜母公司公告——固定检索词做不到。
2. **过滤器既过严又无效**。代码用 substring 在搜索摘要上匹配锚点，严格模式下几乎没有页面能通过，于是被迫放宽规则（`is_evidence_trusted` 从 `name AND legal_person` 改成 `name AND (legal_person OR region)`，且 region 含省级）。最终既没挡住同名污染，又丢掉了大量有效页面。
3. **判断被降级为字符串比较**。画像是自由文本，`current_text == proposed_text` 意味着同一事实换个措辞就判成"同期冲突"，重复调研必然产生噪音卡片。
4. **正文抓取从未接线**。`fetch_page_text` 全仓无人调用，调研完全依赖 Tavily 返回的 `raw_content`。

**结论**：检索词设计、页面取舍、时效判断，这三件都是判断问题，LLM 比规则做得好。把它们写成代码是用最不擅长的工具做最需要灵活性的事。

---

## 2. 调研 Agent 新架构

### 2.1 形态

**主 agent + 工具循环**。agent 自主决定搜什么、搜几次、哪些结果值得读全文、什么时候收尾。代码只提供工具和预算刹车，不介入任何内容判断。

```
messages = [system_prompt, user_prompt(标的已知信息 + 现有画像 + 待补栏目)]
for i in range(MAX_TOOL_ITERATIONS):
    resp = chat(messages, tools=TOOLS)
    if not resp.tool_calls:
        return resp.content              # 最终 JSON，循环结束
    messages.append(resp.assistant_message)
    for call in resp.tool_calls:
        result = execute(call.name, call.arguments)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
# 达到上限：追加一条"请立即输出结论"的 user 消息，再要一轮
```

这就是 Dify Agent 节点、Claude Code、LangChain AgentExecutor 的共同机制。**不引入任何框架**，自己写这 10 行。

### 2.2 两个工具

```jsonc
{
  "name": "web_search",
  "description": "联网搜索。每类信息搜一次即可，不要对同一主题反复检索。",
  "parameters": {
    "query": "string，检索词",
    "max_results": "integer，默认 6，上限 10"
  }
}
// 返回：[{title, url, snippet, published_at}]，不含正文
```

```jsonc
{
  "name": "fetch_page",
  "description": "抓取指定 URL 的正文。搜索摘要不足以判断时使用。",
  "parameters": { "url": "string" }
}
// 返回：{title, text}，text 上限 8000 字
```

设计要点：

- `web_search` **只回摘要不回正文**。要正文让 agent 自己调 `fetch_page` —— 这样"值不值得读全文"是 agent 的决策，而不是代码替它预取。
- `fetch_page` 复用已写好的 `backend/app/services/search_providers/fetch.py`（含 gb18030 解码兜底、任何失败返回 None 而不抛异常）。
- 检索维度靠 prompt 指引（"业务产品/产业链、技术团队/资质、经营质量/交易意愿风险各搜一次"），**不做代码配额**。

### 2.3 输出契约

agent 的最后一条消息（无 tool_calls）即为结果，JSON：

```json
{
  "profile_sections": [
    {
      "section_code": "business_product",
      "content_text": "主营高端体外诊断试剂……",
      "relation": "supplement",
      "as_of_date": "2025-03",
      "sources": ["https://…", "https://…"]
    }
  ],
  "structured_facts": [
    {
      "field_path": "industry_l2",
      "value": "医疗器械",
      "relation": "supplement",
      "sources": ["https://…"]
    }
  ],
  "not_found": ["ops_quality", "sell_intent_risk"]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `section_code` | 必须属于画像六栏（0720 §11），代码校验，不在白名单的丢弃并记 note |
| `content_text` | 自由文本，受 §11 的每栏字符预算约束 |
| `relation` | 四分类，**由 agent 判断**：`consistent` / `supplement` / `temporal_update` / `same_period_conflict` |
| `as_of_date` | 信息的**事实时点**（非网页发布时间）。**仅用于展示和喂给深评，不参与"谁是当前值"的排序**，见 §4.2 |
| `sources` | URL 列表。不要求原文摘录，不要求 identity_basis |
| `field_path` | 必须属于 `RESEARCH_STRUCTURED_FIELDS` 白名单，见 §2.6 |
| `not_found` | agent 查过但确实没有公开信息的栏目。**区分"查了没有"和"根本没查"**，是下一轮调研的依据，也是 §5 二次确认的判断材料 |

`profile_sections` 与 `structured_facts` 的爆炸半径不同：

- **画像**是自由文本，只有深评的 LLM 会读。写错 → 匹配理由变差，影响可逆且局部。
- **结构化字段**（尤其 `industry_l1/l2`、`listed_status`）直接进 SQL 筛选。写错 → 标的**静默地**退出某些买家的候选池或错误进入。**这类变更必须进更新记录且可回滚**（§4）。

### 2.4 时效与冲突判定

四分类的**产物保留**（顾问复核界面需要区分"补充缺失"和"与现有信息冲突"），**判定者从代码换成 LLM**。

现有画像已作为 `current_profile_sections` 传入 prompt，材料是齐的。删除 `classify_research_conflict` 的字符串比较逻辑。

### 2.5 采纳策略与审计

**全部自动采纳**（`auto_accepted`），不设人工复核闸门。

理由：风险由审计链兜住而非事前拦截。同名实体污染这类错误，人工复核对它是透明的（顾问看到的是和 agent 相同的信息，同样判断不了），所以把它挡在人工复核前没有收益，只有噪音。

**成立前提（本方案的强制项）**：所有自动采纳的变更——画像和结构化字段——**必须出现在更新记录中，且可回滚**。见 §4。这条不做，自动采纳不成立。

删除 `HIGH_AUTHORITY_SOURCE_TYPES` / `COMPANY_AUTO_SECTION_CODES` 那套按来源权威度决定是否自动采纳的逻辑。

### 2.6 结构化字段白名单

维持现有 11 项，**全部为文本/枚举类，不含任何数值字段**：

```
target_subject_name
industry_primary / industry_secondary / industry_l1 / industry_l2
registered_province / registered_city / headquarter_province / headquarter_city
listed_status
business_summary
```

营收、利润、估值等数值字段**本轮不纳入**：写错的代价和纠错难度都高一档，等这套跑顺、有 Golden Set 可度量后单独议。

**这意味着调研目前补不了填充率 60% 的利润/营收字段**——这是显式取舍，不是遗漏。

采纳时仍走现有校验：`industry_l1/l2` 过行业字典（`resolve_l1` / `normalize_l2_values`），`listed_status` 过枚举，长度截断。

### 2.7 决策记录：为什么删掉实体锚点硬闸门

0720 §12.4-1 把"同名实体污染"列为最高频失败模式，这个判断本身没有错。删除硬闸门的理由是**这个实现方式解决不了它**：

- 代码只能做机械匹配（substring），而区分两家同名公司需要的信息，**常常压根不在那个页面上**。严格闸门的实际效果是拒绝大量有效页面，同时放过真正的同名污染。
- 实测已经证明了这一点：严格版本几乎不产出，被迫放宽到 `name + region`（含省级），此时闸门形同虚设。
- 兜底责任转移到**审计与回滚**：变更可见、可撤回，且调研的输出限定在小范围字段白名单内。

**同时废弃**：`is_evidence_trusted` / `match_anchors` 的调用（`research_anchor.py` 文件可保留，但不再进入调研主链路）。

**保留一条线索**：`seller_party.unified_credit_code` 目前**全仓无任何写入路径**（列存在于 `001_initial_schema.sql:66`，只有调研的 SELECT 读它）。如果将来要重建可靠的身份校验，前置条件是先让这个字段有数据——建议纳入附件解析（营业执照/工商信息里必然有），或在 §3 重构后的信息页给一个填写入口。**本方案不做，仅记录。**

### 2.8 LLM 客户端改造

`backend/app/ai/llm_client.py` 的 `call_openai_compatible_chat` 目前**完全不支持工具调用**：无 `tools` 参数、不解析 `tool_calls`、无多轮循环。全项目所有 LLM 调用都是单次往返。

需要增加：

- `tools: list[dict] | None` 参数，透传到 payload
- 解析 `choices[0].message.tool_calls` 与 `finish_reason`，在 `ChatCompletionResult` 中返回
- 保持向后兼容：不传 `tools` 时行为完全不变（其他节点不受影响）

**已知坑位**：

1. **`response_format=json_object` 与 `tools` 同传**，部分 OpenAI 兼容层会报错或静默忽略 tools。规避：工具循环期间不传 `response_format`，收尾轮再传；或全程不传，靠 prompt 约束 + 宽松解析。**按此规避设计后无需事前探针**，首次真实运行时 `ai_trace` 会记录完整消息链，届时即可确认。
2. **工具返回必须截断后再入 messages**。一次 `fetch_page` 可能返回数万字，两三轮即撑爆 context。`fetch_page` 自身限 8000 字，`web_search` 只回摘要。
3. **模型**：生产使用 qwen-plus，已由业务侧在其他平台验证支持 function calling。

### 2.9 预算与终止

| 项 | 值 | 性质 |
|---|---|---|
| `MAX_TOOL_ITERATIONS` | 12 | **预算刹车，不是质量控制**。限额内 agent 完全自主 |
| 达到上限 | 追加"请立即基于已有信息输出结论"消息，再要一轮 | 保证总有结构化产出 |
| 单标的搜索次数 | 由 prompt 指引，不硬限 | |
| `fetch_page` 返回上限 | 8000 字 | |

成本量级参考：每标的约 5–10 次 LLM 往返 + 5–15 次搜索；批量 50 个标的 ≈ 250–500 次 LLM 调用。批量走队列（现状已是）。

### 2.10 ai_trace 设计变更

现状是**一次 LLM 调用一行 trace**。agent 循环下，一次批量调研（50 标的）会灌入数百行，且看不出"一次调研"的全貌。

改为**一个调研任务一行 trace**：

- `prompt_messages_json` 存完整消息链（含所有 tool 调用与返回，截断后）
- `metadata_json` 记 `tool_call_count` / `search_count` / `fetch_count` / 各轮耗时
- token 累计求和后写入 `prompt_tokens` / `completion_tokens` / `total_tokens`

---

## 3. 标的信息层页面重构

### 3.1 问题

当前 `TargetDetail.tsx` 有 5 个 tab，其中：

- **基本信息 tab**（`InfoTab`）只展示约 20 个字段，而 `SELLER_TARGET_PARSE_FIELDS` 有 51 个。**缺的恰恰是筛选真正读取的规范维度**：
  - `industry_l1` / `industry_l2` 完全不显示（页面显示的是原文字段 `industry_primary/secondary`，但 SQL 硬筛用的是 L1/L2）
  - 地区（`headquarter_province/city`）只在页头小字出现，字段区没有——而它填充率 99%，是软打分维度
  - `current_debt_ratio`、`cash_flow_status`、`operation_stability_status`、`accepts_relocation`、`accepts_return_investment`、`management_retention_possible`、`market_cap_yuan`、`listing_market_region` 全部未展示，其中多个是买家硬门槛
- **匹配画像 tab** 是 6 段大文本独立成页，看不出与字段的关系

顾问因此无法判断"补哪个字段能改善召回"。补一个利润数字和补一段业务描述对推荐的作用完全不同，但页面上看不出区别。

### 3.2 合并方案

**合并为单个"标的信息"tab**，tab 总数 5 → 4。按业务大类分组，每组内**上半为结构化字段、下半为该组的定性画像**。分组与画像六栏对齐（画像本就是按业务维度切分的），另加一个"身份与地区"组。

| 分组 | 结构化字段 | 定性画像栏 |
|---|---|---|
| **身份与地区** | 标的名称、标的主体、类型、注册省/市、总部省/市、地区粒度、统一社会信用代码<sup>新</sup> | —— |
| **业务与产品** | industry_l1<sup>筛</sup>、industry_l2<sup>筛</sup>、industry_primary、industry_secondary、business_summary | `business_product` |
| **产业链位置与行业地位** | （无结构化字段） | `chain_position` |
| **技术与团队** | management_retention_possible<sup>筛</sup>、management_team_summary | `tech_team` |
| **经营质量** | 营收<sup>筛</sup>、净利润<sup>筛</sup>、总利润<sup>筛</sup>、总资产、负债率<sup>筛</sup>、经营现金流、财务期间、盈利状态、现金流状态<sup>筛</sup>、经营稳定性 | `ops_quality` |
| **交易属性与配合度** | 上市状态<sup>筛</sup>、市值<sup>筛</sup>、上市板块<sup>筛</sup>、估值<sup>筛</sup>、估值时间、报价、报价时间、PE<sup>筛</sup>、出售比例<sup>筛</sup>、可控股<sup>筛</sup>、可并表<sup>筛</sup>、接受少数股权、转让灵活度、并表路径、接受迁址<sup>筛</sup>、接受回投<sup>筛</sup>、对赌依赖 | `deal_terms` |
| **出售诉求与风险缺口** | 是否还卖、信息状态、推荐状态、风险摘要、缺口摘要 | `sell_intent_risk` |

"产业链位置"无结构化字段是正确的——这类判断本就只能靠画像，空着恰好说明画像存在的理由。

### 3.3 字段用途标注（关键设计）

每个字段挂角标：

- **`筛`** —— 参与 SQL 硬筛或软打分（0720 §8 三态判断实际读取的字段）
- **无角标** —— 仅作为深评上下文

判定依据（代码事实，不是估计）：`recommendation_flow.py` 中 `target.get(...)` 实际读取的字段，加上 `CAPABILITY_DIMENSIONS` 三行映射的能力字段（`accepts_relocation` / `accepts_return_investment` / `management_retention_possible`）。

**这不是装饰**。顾问需要知道哪些空缺值得花时间补，而这个信息现在完全不可见。

### 3.4 交互

- **大类可折叠**，默认展开有内容的组、折叠整组全空的组
- **顶部完整度条**，按大类显示填充情况
- **画像的编辑、"标为暂无信息"、"不适用"三态**保持不变（0720 §11）
- **调研入口与调研结果提示提到 tab 顶部**（跨大类），不再嵌在画像分组里
- 画像内容展示其来源、`as_of_date`、置信度（现有实现保留）

### 3.5 范围

- **买家侧本轮不做**。`ProfileSectionsPanel` 虽已支持 `entityType='buyer_intent'`，但买家详情页未接线，且买家画像应挂在**意向（intent）**而非买家主体上（0720 结论）。记为后续项。

---

## 4. 画像变更进入更新记录

### 4.1 现状缺陷

更新记录（`/update-logs/batches`）由 `action_application_log` 拼装（`update_logs.py:445`）。而画像写入走 `upsert_profile_section` 直接插 `entity_profile_section` 表，**整个调研 handler 中一次 `write_action_log` 都没有**。

后果：**自动采纳的画像在更新记录里不可见，也无法回滚。** §2.5 的自动采纳策略依赖这条链路，因此本项是强制前置项。

### 4.2 要做的

1. **画像写入产生 `action_application_log` 记录**，进入更新记录时间线，与附件解析、手工编辑的记录同列。
2. **画像支持回滚**：回滚一个批次时，同批次写入的画像行一并撤回（恢复上一版本，`entity_profile_section` 本就是多版本表，不是覆盖式的）。
3. **结构化字段**走现有 apply 路径即可自动获得日志与回滚（它们是 `seller_target` 的列，`ROLLBACK_FIELDS_BY_ENTITY` 已覆盖），只需接线。
4. **修复"当前值"判定**：现在 `load_profile_sections` 用 `order by as_of_date desc nulls last, updated_at desc` 决定哪一行是当前值，而人工采纳走的是 `supersede_current=False`。后果是**顾问点"确认"后旧画像仍排在前面，界面纹丝不动**（见 §6-C）。
   - 修法：**采纳即 supersede**。"谁是当前值"由"最后一次被采纳"决定，不由日期比大小决定。
   - `as_of_date` 退回其正确职责：展示标注 + 喂给深评作时效参考，不参与排序。

---

## 5. 调研重复触发：退避改为二次确认

废弃 `seller_target.research_retry_after`（该列写入后从未被读取，30 天退避形同虚设）。**建议删列**。

改为显式交互：

1. 标的列表接口返回 `last_research_at`（列已存在）
2. 顾问勾选一批标的点"批量调研"，前端识别出**30 天内已调研过**的标的
3. 弹窗列出这些标的，让顾问二次确认是否重跑
4. 未在近期调研过的直接入队

优于隐式规则的地方：用户知情、可覆盖、且系统"记得上次什么时候查过"这件事对用户可见。

`research_last_outcome`（`found` / `no_public_information` / `failed`）保留，作为弹窗中的辅助信息（"上次调研：30 天前，未找到公开信息"）。

---

## 6. 现存缺陷清单

本轮交叉检查定位的缺陷，按修复优先级排列。前两项阻断"配好搜索工具就能跑通"。

| # | 缺陷 | 位置 | 后果 | 规模 |
|---|---|---|---|---|
| **P0-1** | `PROVIDER_TYPES` 白名单缺 `'search'`（迁移 045 已扩 DB CHECK，API 层白名单是独立清单） | `model_config.py:36` | 保存搜索工具直接 422 `Invalid provider_type: search`，**搜索功能完全无法配置** | 一行 |
| **P0-2** | `_clear_default_provider` 跨 provider_type 全表清 `is_default`，而前端创建搜索工具时硬编码 `is_default: true` | `model_config.py:1366`、`api/index.ts:482` | 保存搜索工具会**静默清掉默认 LLM provider**，下次跑深评才发现 | 小 |
| **P0-3** | 人工采纳画像用 `supersede_current=False`，当前值由 `as_of_date` 排序决定 | `research.py:375` + `profile_sections.py` | 顾问点"确认"可能是**空操作**，界面无反应 | 一行（并入 §4.2） |
| **P1-4** | `research_retry_after` 只写不读 | `research.py:617` 写，无处读 | 30 天退避不生效，批量调研对已知无信息标的反复烧钱 | 并入 §5 |
| **P1-5** | 取证共享计数器 + 循环内 `return`：第一组最多 6 条、第二组填满 8 条即返回，**第三组检索永不执行** | `jobs/handlers/research.py:266` | `ops_quality` / `deal_terms` / `sell_intent_risk` 三栏系统性无证据，且失败隐形 | 随 §2 重写消失 |
| **P1-6** | `fetch_page_text` 全仓无调用，自建抓取是死代码 | `search_providers/fetch.py` | 调研只依赖 Tavily 的 `raw_content`，中文站抽取质量参差时画像极薄 | 随 §2.2 接线 |
| **P1-7** | 信用代码锚点字段名不匹配：代码找 `unified_social_credit_code`/`credit_code`，DB 列名 `unified_credit_code`；且该列**全仓无写入路径** | `research_anchor.py:42` vs `001_initial_schema.sql:66` | 最强锚点从未生效，连锁导致锚点规则被放宽 | 随 §2.7 废弃，仅记录 |
| **P2-8** | 画像冲突用全文相等比较 | `research.py:426` | 同一事实换措辞即判"同期冲突"，重复调研产生噪音卡片 | 随 §2.4 消失 |
| **P2-9** | 建议无去重，重复调研累积重复卡片 | `_insert_research_proposal` 无 dedup | 复核队列越积越脏 | 中 |
| **P2-10** | `evidence_quote` 对不上原文时静默降级为 snippet | `research.py:413` | 展示给复核人的摘录未必支撑结论 | 随 §2.3 消失（不再要求摘录） |

**测试盲区**（同等重要）：

- `tests/test_research_anchor.py:13` 的 fixture 用了代码里那个不存在的字段名 `unified_social_credit_code`，因此 8 个锚点测试全绿而生产路径全空。**测试 fixture 必须使用真实列名**。
- 搜索 provider 的创建路径**无任何测试**，这是 P0-1 逃逸到生产的直接原因。

---

## 7. 实施顺序

| 批次 | 内容 | 依赖 | 验证方式 |
|---|---|---|---|
| **6c** | P0-1、P0-2、P0-3 三项修复 + 搜索 provider 创建路径的回归测试 | 无 | 生产配置 Tavily 并跑通连通性测试 |
| **6d** | `llm_client` 工具调用支持（§2.8）+ 单元测试（mock 端点） | 无 | 单测；不改动其他节点行为 |
| **6e** | 调研 handler 重写为 agent 循环（§2.1–2.4、2.9、2.10），删除锚点闸门/计数器/代码冲突判定 | 6c、6d | 生产端到端：单标的调研，检查 `ai_trace` 消息链与产出 JSON |
| **6f** | 画像审计链路（§4）——`action_application_log` 写入 + 回滚 + 采纳即 supersede | 6e | 生产：调研后在更新记录中看到画像变更并回滚成功 |
| **6g** | 标的信息层页面重构（§3）+ 调研重复触发二次确认（§5）+ 删 `research_retry_after` 列 | 6f | 前端 typecheck/build；生产页面验证 |
| **6h** | P2-9 建议去重（若 §2.5 全自动采纳后仍有 pending 概念则需要，否则取消） | 6e | —— |

每批次遵循 CLAUDE.md 约定：推送后轮询生产 `/health` 确认 commit hash 切换，再验证业务行为。含迁移的批次（6g 删列）必须先跑 `tests/test_migration_sql.py`。

---

## 8. 本方案否决 / 撤回的选项

记录于此，防止后续复议。

| 选项 | 结论 | 理由 |
|---|---|---|
| 代码侧实体锚点硬闸门 | **撤回** | 机械匹配解决不了同名污染（区分信息常不在页面上），实测过严→被迫放宽→形同虚设。改由审计+回滚兜底 |
| 要求 agent 输出 `identity_basis`（判断依据） | **否决** | 业务侧判断：增加输出负担而复核价值有限 |
| 代码核对 agent 引用的原文摘录是否逐字出现 | **否决** | agent 大概率不会逐字输出摘录，且无必要；输出带来源 URL 即可 |
| 固定三组检索词 + 证据配额计数器 | **撤回** | 应写进 prompt 作为工具使用指引，不写进代码 |
| 代码判定时效性与冲突类型 | **撤回** | LLM 判断更准；四分类作为**输出字段**保留 |
| 隐式 30 天退避（服务端静默跳过） | **撤回** | 改为前端二次确认，用户知情可覆盖 |
| 引入 Dify / LangChain 等 agent 框架 | **否决** | 工具循环核心仅约 10 行，框架带来的是周边能力而非机制差异，不值得引入依赖 |
| 人工复核所有调研产出 | **否决** | 500–1000 标的 × 6 栏的复核工作量不可接受；且同名污染对人工复核透明，拦不住 |
| 结构化事实纳入营收/利润/估值等数值字段 | **本轮不做** | 写错代价与纠错难度高一档，待 Golden Set 可度量后单独议 |
| 买家侧（意向）调研与画像 | **本轮不做** | 记为后续项。买家画像应挂在 intent 而非 buyer_party |
| 需求驱动自动触发调研（0720 §12.1） | **本轮不做** | 0720 原计划中的"推荐发现字段缺失→自动生成调研任务"未实现，当前为纯手工触发。保留为后续项，`recommendation_flow.py` 本轮不动 |

---

## 9. 关键代码位置（现状锚点）

| 位置 | 内容 |
|---|---|
| `backend/app/jobs/handlers/research.py` | 调研 handler，756 行，**6e 批次整体重写** |
| `backend/app/api/routes/research.py` | 调研 API（触发/状态/建议复核），568 行 |
| `backend/app/ai/llm_client.py:27` | `call_openai_compatible_chat`，**6d 批次增加 tools 支持** |
| `backend/app/services/search_providers/` | 搜索适配器层（base/tavily/registry/fetch），已完成 |
| `backend/app/services/search_service.py` | provider 查询、密钥解密、连通性探测 |
| `backend/app/services/profile_sections.py` | 六栏定义、加载、渲染、写入 |
| `backend/app/services/research_anchor.py` | 实体锚点，**6e 后不再进入主链路** |
| `backend/app/api/routes/model_config.py:36` | `PROVIDER_TYPES`，**P0-1** |
| `backend/app/api/routes/model_config.py:1366` | `_clear_default_provider`，**P0-2** |
| `backend/app/api/routes/update_logs.py:445` | 更新记录数据源 `action_application_log` |
| `backend/app/services/recommendation_flow.py:1651` | `CAPABILITY_DIMENSIONS`，§3.3 角标判定依据之一 |
| `frontend/src/pages/TargetDetail.tsx:142` | tab 定义，**6g 批次合并** |
| `frontend/src/pages/TargetDetail.tsx:308` | `InfoTab`，字段残缺 |
| `frontend/src/features/targets/ProfileSectionsPanel.tsx` | 画像面板，**6g 批次并入信息页** |
| `frontend/src/lib/api/index.ts:482` | 搜索 provider 创建，硬编码 `is_default: true`（P0-2 相关） |

---

## 10. 生产侧待办（业务方）

- [ ] Railway 设置 `MODEL_SECRET_ENCRYPTION_KEY`（搜索工具直填密钥的加密前提，未设置则无法保存）
- [ ] 6c 上线后在设置页配置 Tavily 并通过连通性测试
- [ ] `seller_target_researcher` 节点的 Prompt 需按 §2.3 输出契约更新（新增 `relation` / `sources` / `not_found`，移除摘录与锚点相关要求）。通过设置页发布，**不写 prompt seed 迁移**
- [ ] Golden Set 口径设计（0720 §13，业务侧自行设计）
