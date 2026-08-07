# 标的调研 Agent 优化 施工单

> 2026-08-06。方案与判据：`标的调研Agent优化方案0806.md`。本单只写「改哪、改成什么、怎么验」。
> **范围只在调研链路内**：`research.py` / `research_map.py` / `research_apply.py` + 两个提示词。不碰筛选与打分。

---

## 一、代码改动

### 1.1 栏目目录按实体取——**两处**（P0-2）

`PROFILE_SECTION_LABELS` 是买卖两侧合成的展示表，喂给标的的调研会带上 `intent_scope` / `intent_financial` / `intent_deal`。实测 14 次输出被下游按 `unknown_section` 丢弃。

两处都要改成 `profile_sections_for("seller_target")`：

| 位置 | 说明 |
|---|---|
| `research.py:91` 的 `PROFILE_SECTION_CATALOG` | **源头**。它进 `research_context_json`，买家栏目码是 agent 先写进报告的，映射只是转发。它还让 `_current_profiles_for_prompt` 多列 3 个永远「missing」的栏目，诱导模型去填 |
| `research_map.py:259-261` | 映射节点的目录 |

只修映射不修 agent，报告里照样带着 `intent_*`。

### 1.1b agent 的可写字段列表用 AGENT 版（P0-2b）

`research.py:313` 给的是 `RESEARCH_STRUCTURED_FIELDS`（27 个），过滤用的是 `RESEARCH_AGENT_STRUCTURED_FIELDS`（25 个）。差的 `financial_period_end_date` / `financial_period_label` 是内部字段，由代码从每条 claim 的 `period_label` 派生。

改用 AGENT 版。「你可以写的字段」和「写了会被收下的字段」必须同一份。

### 1.2 多值闭集列自动带输出形状说明（P1-6）

同文件 `_mapping_context` 的字段目录生成处。`kind == "yuan"` 已有 note，多值 json 列没有。补一条由注册表派生的说明：输出数组、元素取自 `allowed_values`、查过确认干净与没查到是两回事。

新增闭集列时自动生效，不用改提示词正文。

### 1.3 核心财务的期间回退（P1-3）

`backend/app/jobs/handlers/research.py` 的 `_prepare_structured_claims`：核心财务 claim 的 `as_of_date` 缺失或非 ISO 时，用同一条 claim 的 `period_label` 经现成的 `_financial_period_from_label` 回退推导；推不出来才判 `validation_error`。

**「同批核心财务期间必须一致」这条校验不动** —— 回退发生在它之前，推出来的日期照样参与一致性检查。

> **0807 修订**：本节两条结论都被生产实测推翻了，实际形态见 §1.3b。回退不够，得改成标签优先；一致性校验也不能不动。

### 1.3b 期间：标签优先 + 主期间收敛（0807 追加）

判据是 2026-08-07 对「浙江水晶光电科技股份有限公司」的一次真实调研：**五个核心财务字段全被拒**，
标的的营收、净利润、经营现金流、总资产、资产负债率全空，数字只以散文留在「经营质量」栏目里。
拒绝理由 `同批核心财务指标期间不一致：2024-06-30, 2024-12-31, 2025-04-10`。

| 字段 | period_label | as_of_date | 摘录 |
|---|---|---|---|
| current_revenue_yuan | 2024年度 | **2025-04-10** | 「2025年4月10日，水晶光电发布2024年年报，营业总收入为62.78亿元」 |
| current_net_profit_yuan | 2024年度 | **2025-04-10** | 同上 |
| current_operating_cash_flow_yuan | 2024年度 | **2025-04-10** | 同上 |
| current_assets_yuan | 2024年度 | 2024-12-31 | 正确 |
| current_debt_ratio | 2024**半年度** | 2024-06-30 | 取自半年报，本来就是另一期 |

两个独立缺陷，任何一个单独存在都足以清空这批数据：

**（a）`as_of_date` 被填成公告日。** §1.3 的回退只在 `as_of_date` 缺失或非 ISO 时触发，
而 `2025-04-10` 是合法 ISO 日期，回退根本没机会跑。改为 **`period_label` 优先**：
标签是「这个数字属于哪一期」的语义陈述，日期格只是个格子；两者矛盾时错的一定是格子，
何况 `financial_period_label` 落库用的就是标签，让它俩自相矛盾没有意义。
标签解析不出来（「最近一期」）才退回 `as_of_date`。

配套加**未来期间守卫** `_reported_period`：标签优先之后，「2026年度」在 2026 年 8 月会被折算成
2026-12-31，一旦落库，此后任何真实期间都会撞上「不许旧期覆盖新期」，这一行被永久锁死。
已披露的财务期间不可能在未来，超过今天的一律不认。

**（b）整批作废改为主期间收敛。** 一行只能挂一个 `financial_period_end_date`，
所以同批必须收敛到一个期间 —— 这个前提没错，错的是「发现两个期间就全杀」：
上表里一个次要指标取自半年报，就带走了四个来自年报的核心数字。
改为**取最新的那一期为主期间**，落选的逐条拒绝并写明它属于哪一期。
同一次调研在新规则下会写入年报的四项，只拒资产负债率一项 ——
这也是正确结论：半年报的负债率不是年报的负债率。

按新旧选而不是按「哪一期覆盖字段多」选，是因为**批内批外必须同一套规则**：
单条 claim 的「不许旧期覆盖新期」守卫就是按新旧判的。若批内按数量判，
某行先按数量写进年报那一期之后，下一轮拿到新一期的少数几个指标时，
行级守卫放行、批内规则却判它「不是主期间」，**这一行就永久锁死在旧期**。
代价是承认的：新一期只有零星指标时，会挤掉旧一期更完整的一组。
映射提示词的规则 9 已经要求模型「选最新的**完整**报告期、有更新的零散数据也优先取完整年报」，
这个代价由上游来避免；代码只保证不会出现自相矛盾的两套新旧判据。

回归在 `tests/test_research_context_and_periods.py`，其中
`test_one_stray_period_no_longer_takes_the_whole_batch_down` 用的就是上表五条 claim 的原始形态。

### 1.4 调研 Agent 的标的视图改注册表派生（P1-4）

`backend/app/jobs/handlers/research.py` 的 `_get_research_target`：12 列手写投影改为从注册表派生，与解析侧 `seller_target_context_columns()` 同一个做法。

agent 因此能看到库里已有什么、缺什么，也能看到本轮新增的三个字段。

---

## 二、两个提示词（设置页发布，不发版）

**保存后必须回读一次，确认中文没有被替换成 `?`** —— 生产上两个提示词的尾段各有 199 / 若干个问号，就是这么来的。验收项见 §四。

### 2.1 `seller_target_researcher` → v0.6.1

System 不变。User 模板整段替换为：

> **v0.6.1（0807）**：只改了 `as_of_date` 的定义（输出结构里两处 + 规则 4）并新增规则 4b。
> 已经发过 v0.6.0 的，可以只改这三处；下面是含改动的全文。判据见 §1.3b。

````
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
      "as_of_date": "<END DATE of the reporting period, YYYY-MM-DD, or null>",
      "period_label": "<e.g. 2024年度, or null>"
    }
  ],
  "structured_facts": [
    {
      "field_path": "<one of context.allowed_structured_fields>",
      "value": "<value>",
      "sources": ["https://..."],
      "source_excerpt": "<verbatim substring>",
      "as_of_date": "<END DATE of the reporting period, YYYY-MM-DD, or null>",
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
4. `as_of_date` is the END DATE OF THE REPORTING PERIOD — never the date the
   report was published, the announcement was made, or the article was written.
   2024年度 → 2024-12-31; 2024年半年度 → 2024-06-30; 2025年三季度 → 2025-09-30.
   "2025年4月10日发布2024年年报，营业总收入62.78亿元" is a 2024-12-31 figure,
   not a 2025-04-10 one. Always give `period_label` alongside it, and make the
   two agree. If sources conflict, report both with their own periods and quotes.
4b. 营业收入、净利润、利润总额、总资产、资产负债率、经营性现金流这六项要尽量取自
   **同一个报告期**（同一份定期报告）。同一期取不到的宁可省略 —— 一个标的只能
   记录一个财务期间，混期的那一项不会被采纳。
5. Company websites can support products and technical capability claims;
   ranking or market-leader claims need regulatory, government or independent
   authoritative evidence.
6. `source_excerpt` must be a verbatim substring of the cited page, not a
   paraphrase.

## 检索模块

按顺序推进。M0 是入口：主体锚定不上就不要继续往下查。

M0 主体锚定 —— 工商登记、统一社会信用代码、成立时间、注册地与办公地、
   曾用名与英文名、股权结构与实际控制人、上市/挂牌状态与上市地。
   已上市或已挂牌的，给出股票代码（stock_code），照抄原文形式，
   如 "688981.SH"、"00700.HK"；未上市的省略该字段。
   先确认你查到的是同一家公司：名称相近的不同主体、母子公司、同名分公司
   都要排除。锚定不上就停下，只输出你能确认的主体信息。
M1 业务与行业 —— 主营业务、收入构成、商业模式、主要客户与集中度、
   主要供应商、渠道、在手订单与重大合同；据此给出行业归类。
   同时给出 main_products_text：主要产品或产品线本身，一行，逗号分隔，
   如「锂电池正极材料、隔膜、电解液」。它不是业务描述的复述 ——
   business_summary 讲这家公司做什么生意，main_products_text 只列它卖什么。
   不要写行业规模、增速、产业政策 —— 那是行业研究，不是这家公司的信息。
M2 财务与经营质量 —— 营业收入、净利润、利润总额、总资产、资产负债率、
   经营性现金流及其所属期间；盈利状况、现金流状况。
M3 技术、资质与团队 —— 专利与软著、行业资质与许可、研发投入、
   核心团队履历、是否依赖单一关键人。（本模块没有可写字段，
   产出全部进画像正文，检索预算最小。）
M4 资本与估值 —— 历轮融资时间/金额/估值/投资方、市值、PE。
M5 风险与合规 —— 诉讼与仲裁、执行与失信、行政处罚（税务/环保/安全/
   市场监管/劳动）、股权质押与冻结、负面舆情。

   本模块要产出两样东西，不是一样：

   1. major_risk_flags_json —— 可筛选的风险类型数组，取值只能来自
      context.allowed_structured_fields 里该字段的 allowed_values：
      litigation（涉诉）、equity_frozen（股权冻结）、enforcement（被执行）、
      violation（违规违法，含行政处罚与立案）、none（已核查，无重大风险）。
      · 查到了对应风险 → 列出命中的类型，可多选。
      · 在裁判文书网、执行信息公开网、信用公示系统等渠道**实际查过**
        且都没有记录 → 输出 ["none"]。
      · **根本没查到风险类信息、或没能力核查 → 整个字段省略。**
        不要输出空数组 —— 空数组在系统里的含义是「尚未核查」，
        那是系统的默认状态，不是你能得出的结论。把「已核查无风险」
        和「没查过」混为一谈，会让顾问把一个没查过的标的当成干净的。
   2. risk_summary —— 明细：哪个案子、涉及金额、当前进展、信息来源。
      枚举是它的可筛选投影，两者都要给，不要用一个代替另一个。

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

## 经营现金流的口径

current_operating_cash_flow_yuan 只表示公司层面的「经营活动产生的现金流量
净额」，是一个总额。

- 每股经营现金流、每股经营活动现金流量净额（元/股）**不是**这个字段。
- 看到「元/股」「每股」字样，不要写进这个字段，也**不得用股本去倒推**总额 ——
  倒推出来的数字看起来合理，但它不是原文里的事实。
- 自由现金流、投资活动现金流、筹资活动现金流都不是这个字段。
- 只有在原文里直接读到「经营活动产生的现金流量净额」这一行数字时才输出它。

## 不要检索、也不要输出的内容

以下属于卖方私下向顾问表达的交易诉求，公开渠道不存在，
为它们花费检索预算只会逼你编造：

报价与报价时点、出售比例与转让灵活度、能否取得控制权、能否并表、
是否接受少数股权 / 迁址 / 返投、对赌依赖度、是否在售、
管理层是否留任、标的形态、交易方案摘要、溢价率、可接受交易结构。

## 覆盖清单（必填）

检索不到的内容不要写进正文。但必须在 JSON 顶层给出覆盖清单，否则系统
无法区分「查过但确实没有」和「根本没查」：

"coverage": {
  "covered": ["<本轮实际检索过的 section_code>"],
  "no_public_information": ["<检索过但公开渠道确实没有的 section_code>"]
}
````

**相对 v0.5.0 的改动**：M0 加股票代码；M1 加主要产品并划清与 `business_summary` 的界；M2 删「经营稳定性」（该字段已随迁移 `015` 判死）；M5 从「汇总进 risk_summary」改成枚举 + 明细两样都要，并写死三态语义；新增「经营现金流的口径」一节（**替换掉原来那段 199 个问号**）；禁查清单补「可接受交易结构」。

### 2.2 `seller_target_research_mapper` → v0.4.1

System 不变。User 模板的规则 1–12 原样保留，**把坏掉的第 13、14 条替换成**：

````
13. `current_operating_cash_flow_yuan` 只接受公司层面的「经营活动产生的现金流量
    净额」总额。报告里若只有每股口径（元/股）或只有自由现金流、投资/筹资活动
    现金流，一律省略该字段，且不得用股本倒推总额。`source_excerpt` 必须是直接
    支撑该总额的那一句原文。
14. `kind` 为 `yuan` 的字段，`unit` 必须取自 `context.money_units`；报告里没有
    写明单位时用 "元"，不要自己猜一个数量级，也不要把报告里的单位改写成别的
    说法。单位与数字都必须能在 `source_excerpt` 里找到。
15. 字段目录里带 `multi_value: true` 的字段，值是**数组**，元素只能取自该字段
    的 `allowed_values[].value`。报告没有支持任何一个取值时省略该字段，
    不要输出空数组。
````

#### 2.2b v0.4.1（0807）——补 `as_of_date` 的定义

v0.4.0 的规则 9、10 已经要求「六项核心财务取自同一期、`as_of_date` 与 `period_label` 都一致」，
模型照样交出了三个不同的 `as_of_date`（而 `period_label` 四条都对）。原因是整份提示词里
**从没说过 `as_of_date` 是什么**，只写了 `"YYYY-MM-DD or null"`；模型于是填成了原文里出现的
那个日期 —— 年报发布日。规则再严也管不住一个没有定义的字段。

在规则 10 之后插入：

````
10b. `as_of_date` is the END DATE of that reporting period, never the date the
     report was published, the announcement was made, or the article was
     written. 2024年度 → 2024-12-31; 2024年半年度 → 2024-06-30;
     2025年三季度 → 2025-09-30. A sentence like "2025年4月10日发布2024年年报，
     营业总收入62.78亿元" carries as_of_date 2024-12-31 and period_label
     2024年度 — not 2025-04-10.
````

代码侧已经不再依赖模型答对这个（`period_label` 优先，见 §1.3b），这条只是把上游也修正，
少一次无谓的拒绝。

---

## 三、发布顺序

1. 先发代码（四处改动，无迁移）。
2. `/health` 的 commit hash 切换后，再在设置页发布两个提示词新版本并设为默认。
   —— 顺序不能反：提示词讲的字段目录要等新代码生成的上下文到位才有意义。
3. 保存后**回读两个提示词**，确认没有问号（§四）。

---

## 四、验收

### 4.1 静态

- [ ] `python -m pytest -q` 全绿
- [ ] 新增回归用例：栏目目录不含买家码 / 财务期间回退 / 视图注册表派生 / 多值列带 note

### 4.2 提示词保存后必查（本轮的教训）

```bash
python - <<'PY'
import json, pathlib, urllib.request
auth = json.loads(pathlib.Path(".match-ma-local-auth.json").read_text(encoding="utf-8-sig"))
base = "https://match-ma-production.up.railway.app/api/v1"
h = {"Authorization": f"Bearer {auth['token']}"}
ps = json.loads(urllib.request.urlopen(urllib.request.Request(base+"/model-config/prompts", headers=h), timeout=60).read())
for p in ps:
    if p.get("is_default") and p.get("node_name", "").startswith("seller_target_research"):
        t = p["user_prompt_template"]
        cjk = sum(1 for c in t if '一' <= c <= '鿿')
        print(p["node_name"], p["version"], "| ?:", t.count("?"), "| 中文:", cjk)
PY
```

- [ ] 两个提示词的 `?` 数量都是**个位数**（正常标点），中文字符数**上千**

### 4.3 真机（发完提示词后跑一次调研）

- [ ] `normalization_notes` 里**不再出现** `unknown_section:intent_*`
- [ ] 一家有诉讼记录的标的：`major_risk_flags_json` 落库且值在闭集内，`risk_summary` 同时有明细
- [ ] 一家干净的标的：`major_risk_flags_json = ["none"]`，而不是 `[]`
- [ ] 一家查不到风险信息的标的：该字段**不出现在建议里**（保持 `[]` 未核查）
- [ ] 一家上市标的：`stock_code` 落库；`main_products_text` 落库且不是 `business_summary` 的复述
- [ ] `apply_errors` 里不再出现「缺少合法财务期间截止日」
- [ ] 记录本次 `prompt_tokens` —— 视图从 12 列变全量后输入会涨，涨幅要能接受

---

## 五、本轮不做（方案 §四 / §五）

- 报告的顾问可见入口（P2-8）：**待拍板**，默认不做
- 检索策略与 36% 查不到（P2-7）：依赖上一条的数据
- 上下文外置（P2-9）、900 秒超时、`ai_trace` 事务时间：都有理由挂着，见方案 §五
