"""发布 `buyer_intent_normalizer` v0.5.0（买家需求字段精简，0828）。

配套《买家需求字段精简与反向检索方案0828.md》。**本轮的收益不在数据库，在这份提示词。**

代码侧已经把 32 个字段从 `writable_by` 里去掉了 `parse`，所以
`field_contract_json` 与 `enum_contract_json` 会自动变短（实测 54 项 15,602 字符
→ 27 项 7,621 字符；枚举 17 项 1,385 字符 → 7 项 468 字符）。**模型再也看不到
那些字段，也就永远写不进来** —— 提示词这一版要做的是把讲解那些字段的规则正文
一起删掉，否则正文还在教模型填一批它已经看不见的字段。

删掉的段落，以及为什么：

- **「行业口径」整段 + 「兜底原则」整段**。买家需求侧的行业字典下线（判决一）。
  实测人均只填 1.25 个一级行业、二级行业只有 21% 有值，而信息主要落在
  **不参与匹配的** industry_primary(92%) / industry_secondary(73%) 两个原文列里。
  换成三个自由字段：业务标签 / 业务说明 / 排除方向。
- **「百分比口径」表格里的四行**（负债率、净利率、毛利率、溢价率）。这四个字段
  在生产里合计只有 4 条真实数据（1/52、2/52、1/52、0/52），而这张表是全篇最长的
  段落之一。留下的两行是股比 —— 它有数据，单位陷阱也真实存在。
- **「倍数」那句里的 max_ps 与 return_investment_multiple**，两列都已退役。
- **「规则只有两态（写进 condition_effects_json）」整段**（判决三）。那一列的三个
  活消费方（前端角标、深评上下文、解析写入）本轮全部拆掉，筛选消费方在阶段五
  就已经没了。条件硬不硬改由需求业务说明的正文承载，由 LLM 读。
- **preferred_listed_status 那一段**：它是 acceptable_listed_status_json 的单向
  派生列，本来就不可手写。
- **financing_stage_requirement_summary** 的提及：该列已退役。

新增的段落：

- **业务方向口径**：三个自由字段怎么分工。重点是 intent_business_summary 的口径
  被重新定义了 —— 它是**反向检索首轮筛选唯一读的东西**，写成「符合公司战略的
  优质标的」这种话，那条需求在反向里就等于不存在。
- **地区新口径**：两个平铺数组，去掉 effect 三态。可接受与排除拆成两列，
  语义写在列名里；强弱交给 region_scope_summary 的原话。

⚠️ **大区展开放在代码里，不在提示词里。** 方案 §八 原本要求把「长三角 = 沪苏浙皖」
这类展开表写死进提示词，但 `region_dictionary.REGION_GROUPS` 早就在做这件事，
而且做得更稳：提示词里的表每次调用都要模型重新照抄一遍，改词表要发新版本，
模型还可能漏抄；代码里的表是确定的，改一次全链路生效，两个归一函数共享它。
所以这一版只告诉模型「说到大区就原样写大区名，不要自己猜一个省」。

变量集合同批收窄：`industry_l1_list` / `industry_l2_list` 从 NodeSpec 里移除
（这份提示词不再需要注入一百多个二级行业）。**handler 仍然照常传这两个变量** ——
线上可能正跑着引用它们的旧版本（v0.4.0 就引用），撤掉传参会让那一版渲染成 "null"。

默认只检查；只有显式 ``--apply`` 才写生产 Prompt。
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
for path in (str(REPO_ROOT), str(SCRIPT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from prompt_publish_utils import (  # noqa: E402
    PromptVersionConflict,
    ensure_prompt_version_compatible,
    validate_prompt_contract,
    validate_render_preview,
)

API_BASE = "https://match-ma-production.up.railway.app/api/v1"
NODE_NAME = "buyer_intent_normalizer"
VERSION = "v0.5.0"

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {"type": "object"},
        "scenarios": {"type": "array", "items": {"type": "object"}},
        "profile_sections": {"type": "array", "items": {"type": "object"}},
        "needs_confirmation": {"type": "array", "items": {"type": "object"}},
    },
}

# 与 v0.4.0 一字不差：这一版不改角色设定，只改规则正文。
SYSTEM_PROMPT = """你负责买家并购需求解析的第二阶段：把第一阶段拆好的语义结构落成规范字段。

输入是语义解析的产物，不是原始材料 —— 不要再去推断材料里可能有什么，
只处理已经拆出来的内容。输出一个 JSON 对象，不要 Markdown。
不要输出 buyer_party。不要臆造事实。

用户可见文本用中文；需要标准值的字段必须使用给定清单里的精确取值。"""

USER_PROMPT_TEMPLATE = """语义解析结果 JSON：
{{ semantic_parse_json }}

买家已有信息 JSON：
{{ buyer_profile_json }}

字段契约 JSON（字段名、所属模块 module、值类型、可选枚举、是否支持多方案，
以及 is_condition —— 参与初筛/排序的条件，还是只供深度评估阅读的描述）：
{{ field_contract_json }}

标准省级行政区划清单：
{{ province_list }}

结构化字段候选值规则 JSON：
{{ enum_contract_json }}

只输出有证据支撑的内容。不要输出值为 null 的字段，不要重复原文。
**字段契约里没有的字段一律不要输出** —— 写了不会报错，会被静默丢弃。

输出结构：
{
  "fields": { "字段名": 值 },
  "profile_sections": [
    {"section_code": "intent_scope | intent_financial | intent_deal",
     "content_text": "这个模块里标准化不了、也不适合拿去初筛的说法"}
  ],
  "scenarios": [
    {"name": "方案一", "fields": {"字段名": 值}}
  ],
  "needs_confirmation": [
    {"field": "字段名", "value": "推断值", "reason": "为什么需要顾问确认"}
  ]
}

三块「其他」（profile_sections）怎么写：
- 每个模块最多一条，section_code 用 intent_scope / intent_financial / intent_deal。
- 装这个模块里**装不进结构化字段**的说法：协同性诉求、资质与认证偏好、
  尽调关注点、买方自身产业背景、对团队与治理的期待等。
- **也装条件的软硬**：「营收 1 亿是底线」「地域最好但不强求」「负债率高一点也能谈」
  这类语气，现在没有专门的字段承载，写进这里由后续深度评估阅读。
- 它不参与初筛和排序，会随需求一起交给后续深度评估通读，所以写完整的句子，
  不要写成关键词堆。宁可多留也不要丢。
- 结构化字段已经表达清楚的阈值，不要在这里重复一遍。

业务方向口径（三个自由字段，**都不过任何词表**）：
- intent_business_summary 写清楚**这个买家要买什么样的业务**。
  这一条是整份需求里最重要的字段：为标的找买家时，判断「这家买家想不想要这个
  项目」**只读这一栏**。所以要具体到能判断的程度 ——
  · 好：「找华东地区做半导体设备精密结构件的，最好已进入头部设备厂供应链」
  · 差：「符合公司战略方向的优质标的」（等于什么都没说，这条需求在反向检索里
    就等于不存在）
  材料里说得含糊时照实写含糊的原话，不要替买家编一个具体方向。
- intent_business_tags_json 是自由标签数组，写买家关注的细分方向，5 个以内。
  「薄膜电容器」「线控底盘」「固态电池」「宠物医疗」这类词直接写，
  **不需要也不要去套任何行业分类**。
- excluded_business_text 写买家明确说不要的方向，自由文本。
  「不看房地产」「不接触教培」这类。没提就整个省略。
- buyer_industry_advantage_summary 写买家自身的产业背景与能做的协同
  （「本地国资，手上有三家同类企业」），它帮后续判断这桩交易有没有产业逻辑。

地域口径（两个数组 + 一段原话，**必须一起产出**）：
- acceptable_regions_json 是买家能接受的地区，excluded_regions_json 是明确排除的。
  两个都是平铺数组，元素形如 {"province": "江苏省", "city": "苏州市"}，
  省名从「标准省级行政区划清单」里逐字取。
- **只填到材料说得准的层级**：只说「江苏」就是 [{"province": "江苏省"}]，
  那表示全省都可以。补全成三级会让它变成「江苏省某个具体的市」，筛错粒度。
- **不要在元素里写 effect / 强度**。可接受与排除已经拆成两个字段，
  语义写在字段名里；「必须在广东」和「优先广东」的区别写进 region_scope_summary。
- **说到大区就原样写大区名**：「长三角」「大湾区」「京津冀」「华东」这类说法，
  直接写成 [{"province": "长三角"}]，系统会自动展开成省份清单。
  **不要自己猜一个省** —— 那正是历史上出错最多的地方（把「优选长三角」填成了
  买家自己所在的广东省）。
- **买家在哪个省，和它想买哪里的标的，是两件事。** 材料没说想买哪里，就不要
  拿买家自己的所在地去填。
- 「全国」「不限」「无地域限制」→ region_scope_summary 照写原话，
  两个数组都留空（空数组正确地表示「无约束」，不是「没有可接受地区」）。
- 只写摘要不写数组，这条地域要求在筛选里**完全不存在**；只写数组不写摘要，
  「优先/必须」的区别就丢了。两个一起给。

百分比口径（**最容易出错的一处**）：
下列字段用 **0 到 100 之间的数字**表示百分比，直接去掉百分号，不要除以 100：

| 字段 | 材料写法 | 正确输出 | 错误输出 |
| --- | --- | --- | --- |
| desired_equity_ratio_min | 收购比例不低于 51% | 51 | 0.51 |
| desired_equity_ratio_max | 收购比例不超过 70% | 70 | 0.7 |

写成 0.51 这类小数不会被系统拒绝，但含义会变成 0.51%，
筛选时要么把全部标的挡在门外，要么等于没有门槛 —— 错得静悄悄，所以必须自己盯住。

max_pe 是**倍数**不是百分比：「PE 不超过 15 倍」→ 15，不要乘 100。

财务口径：
- min_valuation_yuan 与 max_valuation_yuan 是估值区间。
- min_market_cap_yuan 与 max_market_cap_yuan 只在明确出现市值证据时使用，
  绝不能把估值搬进市值字段。
- 金额一律换算成人民币元的数字，位数自己数一遍再写：
  「三千万」→ 30000000（3 后面 7 个 0）、「5000万」→ 50000000、
  「1.2亿」→ 120000000、「6亿」→ 600000000（6 后面 8 个 0）。
  少写一个 0 就差十倍，而十倍的门槛不会报错，只会静静地筛错人。

资本市场口径：
- acceptable_listed_status_json 逐项列出买家能接受的标的上市状态，
  取值只有 listed / unlisted / pre_ipo 三个。
- 材料没提上市状态，就**整个省略这个字段**；「上市不上市都行」也是省略
  （三个都能接受 = 没有这个门槛）。
- 材料说「已上市的不考虑」，要输出 ["unlisted", "pre_ipo"] —— 注意方向，
  把排除写成「都可以」是反的。
- A 轮 B 轮等融资细节没有对应字段，写进 intent_deal 那块「其他」。

重大风险与交易结构（语义靠你判，取值清单见字段契约）：
- unacceptable_risk_flags_json 存买家**不接受**的风险类型，注意方向 —— 不是「能接受什么」。
  · 「不接受任何重大风险」「要求无涉诉无冻结」这类全称否定 → 输出四值全集
    ["litigation","equity_frozen","enforcement","violation"]。
  · 只否定其中几类 → 输出对应子集（只说「不能有股权冻结」→ ["equity_frozen"]）。
  · 材料**没提到风险这件事** → 整个字段省略，不要输出空数组（空数组的含义是「未提及」，
    由系统写，不由你写）。
  · 「可接受历史诉讼但需已结案」这类有条件的容忍度写进 major_risk_tolerance_summary，
    两者并存：枚举用于筛选，摘要是明细。
- transaction_types_json 只装**交易结构**这一个维度：
  借壳重组、吸收合并、并购 → merger；老股转让、股权转让 → equity_transfer；
  定增、增资扩股 → capital_increase；资产收购 → asset_purchase。
  · 支付方式（现金、股份、现金+股份、全现金、换股）**不进这一列**，写进 transaction_type 原话。
  · 控制权诉求（控股收购、少数股权、战略投资）**不进这一列**，它已经由 requires_control /
    requires_consolidation / desired_equity_ratio_* 表达，重复写会互相打架。
- transaction_type 存交易方式原文，照抄材料措辞（「全现金收购」「控股收购或分阶段并购」）。
  它不参与匹配，作用是保住闭集装不下的那两个维度。

多方案（语义结果里 scenarios 非空，即买家给了两个及以上并列可选方案）：
- 各方案**共有**的条件写进顶层 fields。
- 方案之间**不同**的条件写进顶层 scenarios 数组（与 fields 平级），每个元素：
  {"name": "方案一", "fields": {"字段名": 值}}
  fields 里只放这个方案自己的取值，字段名和顶层用同一套规范字段。
- 条件分叉也算方案：「营收上市要 10 亿、非上市 4-5 亿」是两个方案，
  **拆不开就整句进 needs_confirmation，绝不挑一个留下、把另一个丢掉**。
- 只有一种要求时 scenarios 留空数组。

条件强度：
- 语义结果标为 preference 的条件不要写成硬性阈值字段。
- 语义结果里的 unknowns 逐条进 needs_confirmation。

Grade rule (mandatory): intent_grade is the recommendation gate — A/B/C/D keep the requirement in the recommendation pool, E removes it. Emit intent_grade ONLY when the material explicitly states a grade letter (A, B, C or D) for this requirement, or explicitly says the requirement is paused, stopped, ended, completed, or terminated. In every other case omit both intent_grade and status entirely: never emit a guessed value, and never echo back the value already shown in context. When the requirement is temporarily paused, emit intent_grade "E" together with status "paused"; when it is ended, completed, or terminated, emit intent_grade "E" together with status "closed". Never emit intent_grade merely because the requirement looks vague, stale, or hard to match — that judgement belongs to the consultant, not to this parse."""

EXPECTED_VARIABLES = validate_prompt_contract(
    node_name=NODE_NAME,
    system_prompt=SYSTEM_PROMPT,
    user_prompt_template=USER_PROMPT_TEMPLATE,
)


def ensure_existing_version_compatible(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return ensure_prompt_version_compatible(
        rows,
        version=VERSION,
        system_prompt=SYSTEM_PROMPT,
        user_prompt_template=USER_PROMPT_TEMPLATE,
        output_schema=OUTPUT_SCHEMA,
        variables=EXPECTED_VARIABLES,
    )


def _api_client():
    import match_ma_api_tools as api

    return api


def _payload() -> dict[str, Any]:
    return {
        "node_name": NODE_NAME,
        "version": VERSION,
        "name": "买家需求字段规范化 v0.5.0（字段精简：业务方向自由化 + 地区两数组）",
        "description": (
            "0828 买家需求字段精简。行业字典下线，业务方向改走自由标签 + 业务说明 + "
            "排除方向；地区拆成可接受/排除两个平铺数组并去掉 effect 三态；"
            "删掉条件作用、四行百分比口径与已退役字段的全部规则正文。"
        ),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_buyer_intent_normalizer_v050_prompt.py"},
    }


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")

    # 退役字段的规则正文一条都不许留下 —— 留着就是在教模型填它已经看不见的字段。
    for retired in (
        "condition_effects_json",
        "max_debt_ratio",
        "min_net_margin",
        "min_gross_margin",
        "max_premium_rate",
        "max_ps",
        "industries_json",
        "industry_l2_json",
        "industry_focus_tags_json",
        "excluded_industries_json",
        "region_constraints_json",
        "preferred_listed_status",
        "financing_stage_requirement_summary",
        "return_investment_multiple",
    ):
        assert retired not in USER_PROMPT_TEMPLATE, f"正文里还在讲已退役的 {retired}"
    print("[OK] 正文里没有任何已退役字段的规则")

    # 新字段的口径必须在正文里，否则模型只从字段契约看到一个字段名。
    for column in (
        "intent_business_summary",
        "intent_business_tags_json",
        "excluded_business_text",
        "acceptable_regions_json",
        "excluded_regions_json",
    ):
        assert column in USER_PROMPT_TEMPLATE, f"新字段 {column} 没有口径说明"
    assert "只读这一栏" in USER_PROMPT_TEMPLATE, "业务说明的口径必须点明它是首轮筛选唯一读的东西"
    assert "系统会自动展开" in USER_PROMPT_TEMPLATE, "大区展开在代码侧，正文要告诉模型原样写"
    print("[OK] 五个新字段的口径都在正文里")

    shrunk = len(USER_PROMPT_TEMPLATE)
    print(f"[info] 规则正文 {shrunk} 字符（v0.4.0 为 5615）")

    if args.check:
        print(f"[check] {NODE_NAME} {VERSION}；未访问 API，未 apply")
        return
    api = _api_client()
    token = api._resolve_token(args.api_base)
    if args.render_preview:
        preview = api._request_json(
            args.api_base,
            "POST",
            "/model-config/prompts/render-preview",
            token=token,
            json_body={"system_prompt": SYSTEM_PROMPT, "user_prompt_template": USER_PROMPT_TEMPLATE},
        )
        rendered_system, rendered_user = validate_render_preview(
            preview,
            expected_variables=EXPECTED_VARIABLES,
        )
        print(f"[OK] render-preview 已替换全部 {len(EXPECTED_VARIABLES)} 个双花括号变量")
        print((rendered_system + "\n" + rendered_user)[:1200])
        print("[render-preview] 只读渲染完成；未 apply")
        return
    rows = api._request_json(
        args.api_base,
        "GET",
        "/model-config/prompts",
        token=token,
        query={"node_name": NODE_NAME, "include_inactive": "true"},
    )
    existing = ensure_existing_version_compatible(rows if isinstance(rows, list) else rows.get("items", []))
    if existing is not None:
        print(f"[exists-identical] {NODE_NAME} {VERSION} 正文/schema/变量一致，不会重复创建")
        if args.apply and (not existing.get("is_active") or not existing.get("is_default")):
            updated = api._request_json(
                args.api_base,
                "PATCH",
                f"/model-config/prompts/{existing['id']}",
                token=token,
                json_body={"is_active": True, "is_default": True},
            )
            print(f"[activated] id={updated.get('id')}")
        else:
            print("[no-op] 未改生产 Prompt")
        return
    if not args.apply:
        print(f"[dry-run] 将创建 {NODE_NAME} {VERSION} 并设为默认；加 --apply 才真正写入")
        return
    created = api._request_json(
        args.api_base,
        "POST",
        "/model-config/prompts",
        token=token,
        json_body=_payload(),
    )
    print(f"[created] id={created.get('id')} version={created.get('version')}")
    print("")
    print("⚠️ 上线后记得对存量 52 条需求批量重跑一次解析：迁移 022 的回填只是把旧内容")
    print("   拼起来，intent_business_summary 的新口径要靠重跑才能收敛。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--check", action="store_true", help="只做本地契约校验，不访问 API")
    parser.add_argument("--render-preview", action="store_true", help="只读渲染预览")
    parser.add_argument("--apply", action="store_true", help="真正写入生产 Prompt")
    args = parser.parse_args()
    if not (args.check or args.render_preview or args.apply):
        args.check = True
    try:
        _run(args)
    except (PromptVersionConflict, RuntimeError, AssertionError) as error:
        print(f"[FAIL] {error}")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
