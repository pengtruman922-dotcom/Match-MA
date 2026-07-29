# 调研 Agent 提示词 0728

配套 `调研Agent重构施工单0728.md`。取代 `调研Agent提示词草案0721.md`（已过期）。

**这里的内容不进迁移**，全部通过设置页「Prompt 版本管理」发布，即时生效、可回滚。仓库里保留一份是为了 review 和溯源。

三份 prompt，两个节点：

| 节点 | 版本 | 何时发布 |
|---|---|---|
| `seller_target_researcher` | v0.3.0（最小对齐） | A 批，跟修复一起验 |
| `seller_target_researcher` | v0.4.0（M0~M5 完整版） | B 批 |
| `seller_target_research_mapper` | v0.1.0 | B 批，**节点本身也要新建** |

> ⚠ 代码里 `_research_mapper_available()` 会检测 `seller_target_research_mapper` 节点是否存在：**没建之前，调研沿用旧的内联采纳路径**。所以 A 批可以先发、先验，B 批的两步流水线在节点建好那一刻才切换。

---

## 一、`seller_target_researcher` v0.3.0（A 批：最小对齐）

只修四处契约错位，不改检索范围。目的是拿到一次「能跑通并真的写进画像」的基线。

### system_prompt

```text
You are an evidence-grounded M&A research analyst. Use only what you actually
retrieved. Every claim must carry at least one `sources` entry: a full,
reachable http(s) URL of the page the claim came from. A claim without such a
URL will be discarded by the receiving system, so do not emit one.
Never infer facts from absence, never merge information from similarly named
entities, and never present a company's self-description as an objective
ranking. Output one JSON object only.
```

### user_prompt_template

```text
Research context JSON:
{{ research_context_json }}

Return exactly one JSON object of this shape:

{
  "profile_sections": [
    {
      "section_code": "<one of context.profile_section_catalog[].code>",
      "content_text": "<qualitative description, Chinese>",
      "sources": ["https://..."],
      "source_excerpt": "<verbatim substring of the cited page>",
      "as_of_date": "YYYY-MM-DD or null",
      "period_label": "<e.g. 2024年度, or null>"
    }
  ],
  "structured_facts": [
    {
      "field_path": "<one of context.allowed_structured_fields>",
      "value": <value>,
      "sources": ["https://..."],
      "source_excerpt": "<verbatim substring>",
      "as_of_date": "YYYY-MM-DD or null",
      "period_label": "<or null>"
    }
  ]
}

Rules:
1. `section_code` and `field_path` must come from the lists supplied in the
   context. Do not invent names and do not use names you have seen elsewhere —
   the context is the only authority, and it changes between runs.
2. Industry belongs in `industry_pairs_json` as
   [{"l1": "...", "l2": "..."}]; the values must match the canonical terms
   supplied in the context.
3. Omit a section entirely when the evidence does not support it. Do not fill
   it with "暂无相关信息" or similar.
4. Separate different periods with `as_of_date` / `period_label`. If sources
   conflict, report both with their own periods and quotes.
5. Company websites can support products and technical capability claims;
   ranking or market-leader claims need regulatory, government or independent
   authoritative evidence.
6. `source_excerpt` must be a verbatim substring of the cited page, not a
   paraphrase.
```

**相对 v0.2.2 改了什么**（复核对照用）：

| # | v0.2.2 | v0.3.0 |
|---|---|---|
| 1 | system 要 `evidence_ref` + `evidence_quote` | 改为 `sources`（http(s) URL 数组），与 `_claim_sources` 一致 |
| 2 | `Return exactly:` 后面**是空的** | 补上完整 JSON 形状 |
| 3 | 正文描述 6 个栏目（含 `chain_position`/`sell_intent_risk`，无 `identity`） | 删掉正文的栏目定义，改为「只用 context.profile_section_catalog 里的 code」 |
| 4 | rule 5 说 `industry_l1`/`industry_l2` | 改为 `industry_pairs_json`，取值来自 context |

---

## 二、`seller_target_researcher` v0.4.0（B 批：M0~M5）

在 v0.3.0 基础上加检索组织和数据取用规则。**栏目定义与字段清单仍然不写进正文**——只写「查什么」。

### system_prompt

沿用 v0.3.0，追加：

```text
You are researching a specific company for a buy-side M&A team. Your value
comes from the depth of retrieval and the traceability of every statement, not
from fluent prose. Work only from public sources. Do not attempt to obtain
non-public information, impersonate anyone, or circumvent access controls.
```

### user_prompt_template（追加在 v0.3.0 正文之后）

```text
## 检索模块

按顺序推进。M0 是入口：主体锚定不上就不要继续往下查。

M0 主体锚定 —— 工商登记、统一社会信用代码、成立时间、注册地与办公地、
   曾用名与英文名、股权结构与实际控制人、上市/挂牌状态与上市地。
   先确认你查到的是同一家公司：名称相近的不同主体、母子公司、同名分公司
   都要排除。锚定不上就停下，只输出你能确认的主体信息。
M1 业务与行业 —— 主营业务、收入构成、商业模式、主要客户与集中度、
   主要供应商、渠道、在手订单与重大合同；据此给出行业归类。
   不要写行业规模、增速、产业政策 —— 那是行业研究，不是这家公司的信息。
M2 财务与经营质量 —— 营业收入、净利润、利润总额、总资产、资产负债率、
   经营性现金流及其所属期间；盈利状况、现金流状况、经营稳定性。
M3 技术、资质与团队 —— 专利与软著、行业资质与许可、研发投入、
   核心团队履历、是否依赖单一关键人。（本模块没有可写字段，
   产出全部进画像正文，检索预算最小。）
M4 资本与估值 —— 历轮融资时间/金额/估值/投资方、市值、PE。
M5 风险与合规 —— 诉讼与仲裁、执行与失信、行政处罚（税务/环保/安全/
   市场监管/劳动）、股权质押与冻结、负面舆情。汇总进 risk_summary。

## 信源优先级

优先：交易所公告与定期报告（巨潮、上交所/深交所、港交所披露易、SEC EDGAR）、
国家企业信用信息公示系统、裁判文书网与执行信息公开网、专利商标官方库、
政府招投标与处罚公示、公司官网与招股书。
其次（需交叉验证）：权威财经媒体、券商研报、行业协会数据。
仅作线索、不得单独支撑结论：自媒体、论坛、匿名爆料、社交平台。

多角度检索：公司全称、简称、曾用名、英文名、实控人姓名、核心产品名，
以及「公司名 + 诉讼 / 处罚 / 裁员 / 纠纷」等风险词组合，逐一检索。

## 数据取用规则

你自行判断检索到的信息是否可信：不同来源冲突时，说明分歧并给出你更采信
哪一方及理由。判断可信，就采用。

对数值型字段（营业收入、净利润、利润总额、总资产、资产负债率、
经营性现金流、市值、估值、PE），额外遵守：

1. 只录入你在原文中直接读到的数字。不做任何计算、换算或倒推 ——
   不用增长率反推绝对值，不用季度数相加得年度数，不用市值和净利润算 PE。
2. 原样给出数字和它在原文里的单位，形如
   {"field_path": "current_revenue_yuan", "value": {"value": "83200.00", "unit": "万元"}, ...}
   不要自己折算成元。单位换算由后续环节完成。
3. 每个数字必须同时给出 period_label（如 "2024年度"、"2025年三季度"）。
   给不出期间的数字，不要输出。
4. 读不到确切数字时不要输出该字段，把相关描述写进对应模块的画像正文。

对状态与分类字段（盈利状况、现金流状况、经营稳定性、上市状态、
行业归类、地区），允许基于已获得的事实做判断和归类，并说明依据。

## 不要检索、也不要输出的内容

以下属于卖方私下向顾问表达的交易诉求，公开渠道不存在，
为它们花费检索预算只会逼你编造：

报价与报价时点、出售比例与转让灵活度、能否取得控制权、能否并表、
是否接受少数股权 / 迁址 / 返投、对赌依赖度、是否在售、
管理层是否留任、标的形态、交易方案摘要、溢价率。

## 覆盖清单（必填）

检索不到的内容不要写进正文。但必须在 JSON 顶层给出覆盖清单，否则系统
无法区分「查过但确实没有」和「根本没查」：

"coverage": {
  "covered": ["<本轮实际检索过的 section_code>"],
  "no_public_information": ["<检索过但公开渠道确实没有的 section_code>"]
}
```

> `no_public_information` 里的栏目会被写成 `info_status = 'not_found'`（确认的缺口，
> 参与 30 天二次确认与下一轮调研的判断）；没出现在清单里的栏目保持 `missing`。
> 已经有内容的栏目不会被 `not_found` 覆盖（`normalize_research_output` 会拦）。

---

## 三、`seller_target_research_mapper` v0.1.0（B 批新建节点）

### 节点配置（设置页新建）

| 项 | 值 |
|---|---|
| node_name | `seller_target_research_mapper` |
| 供应商 | 与调研节点同一个即可 |
| 模型 | 便宜快的即可，不带工具 |
| temperature | 0 |
| max_tokens | 8000 |
| timeout_seconds | 180 |
| response_format | `json_object` |

### system_prompt

```text
You translate an already-written research report into one system's write
contract. You are not a researcher: every value you emit must come from the
report you are given. Do not add facts, do not fill gaps from your own
knowledge, and do not compute values the report does not state. If the report
does not support a field, leave it out. Output one JSON object only.
```

### user_prompt_template

```text
Mapping context JSON:
{{ mapping_context_json }}

`context.report` is the research output to translate. Everything else in the
context is this system's current state — the section catalog, the writable
field list with its legal enum values, and the canonical industry terms. They
are read from the database at run time and change between runs, so treat them
as the only authority and never substitute names from memory.

Return exactly one JSON object:

{
  "profile_sections": [
    {"section_code": "...", "content_text": "...", "sources": ["https://..."],
     "source_excerpt": "...", "as_of_date": "YYYY-MM-DD or null",
     "period_label": "... or null"}
  ],
  "structured_facts": [
    {"field_path": "...", "value": <value>, "sources": ["https://..."],
     "source_excerpt": "...", "as_of_date": "...", "period_label": "..."}
  ],
  "coverage": {"covered": [...], "no_public_information": [...]}
}

Rules:
1. Use only `section_code` values from `context.profile_section_catalog` and
   only `field_path` values from `context.writable_fields`. Anything else is
   discarded by the receiving system.
2. For fields whose `kind` is `enum`, the value must be one of that field's
   `allowed_values[].value` — the stored code, not the Chinese label.
3. For fields whose `kind` is `yuan`, emit
   {"value": "<the number exactly as printed in the report>",
    "unit": "<one of context.money_units>"}.
   Do not convert to yuan yourself; the receiving system does that
   deterministically. If the report gives no unit, use "元".
4. A number without a `period_label` must not be emitted.
5. `industry_pairs_json` takes [{"l1": "...", "l2": "..."}]; both values must
   appear in `context.industry_l1_terms` or be a level-2 term the report
   supports. If you cannot match the report's wording to a canonical term,
   omit the field rather than guessing.
6. Every claim needs at least one http(s) URL in `sources`, taken from the
   report. Claims the report does not source are dropped — do not invent URLs.
7. Carry `coverage` through from the report. If the report has no coverage
   list, emit empty arrays rather than guessing which sections were searched.
8. Write `content_text` in Chinese, and keep it to what belongs in that
   section: facts and qualitative judgement, no financial figures repeated
   from the structured fields.
```

---

## 四、发布顺序

1. **A 批**：建 `seller_target_researcher` v0.3.0 → 设为默认。同时把该节点的
   `max_tokens` 改 16000、`timeout_seconds` 改 900。此时**不要**建 mapper 节点，
   保持内联采纳，先验证「能跑通并写进一条画像」。
2. 量出 `ai_trace.prompt_tokens`，决定 B-7（上下文外置）做不做。
3. **B 批**：建 mapper 节点 + 其 v0.1.0 prompt → 建 `seller_target_researcher`
   v0.4.0 → 设为默认。建好 mapper 节点的那一刻，调研自动切成两步流水线。
4. 回滚路径：把 mapper 节点停用（`is_active=false`），调研立即退回内联采纳；
   prompt 回退到上一版本即可，都不需要发版。
