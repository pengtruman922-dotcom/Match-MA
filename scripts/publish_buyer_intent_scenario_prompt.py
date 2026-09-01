"""发布 `buyer_intent_normalizer` v0.5.0（买家需求方案化，0901）。

配套《买家需求方案化重构方案0901.md》。**这一版是整轮改动最大的一处。**

结构变了：**解析从「抽一组字段」变成「先把材料切成 N 个方案，再对每个方案抽一组
字段」。** 一条买家需求不再有公共层 —— 它是一个容器挂 1..N 个互相独立、各自完整
的方案，命中任意一个即算命中。

取消公共层不是重构口味，是修 bug。实测生产库公共层与方案层的取值**冲突了 11 个
格子**：广百股份的公共层挂着「估值上限 30 亿 + 地区山东/广东」，而它的两个方案是
「广州重奢奥莱项目」和「超市便利店零售业态」—— 那两条约束到底属于哪一个，原文里
根本看不出来。公共层就是解析器猜不出归属时的兜底桶，猜错了就把某一档的约束强加给
全部档。

代码侧的字段契约随之重排（实测 27 项 7,621 字符 → 17 项 4,045 字符，
枚举 7 项 468 → 3 项 153），每一项带上 `scope`：`intent` 落在需求容器上，
`scenario` 落在方案上。

本版删掉的规则正文：

- **控股/并表要求、期望股比上下限、可接受交易结构、不接受的重大风险、
  交易方式原文、风险容忍、排除地区** 的全部口径。实测 48 需求 x 71 标的全量对判：
  控股要求与并表要求是买家侧用得最多的两个字段（21 条和 18 条需求填了），
  **真淘汰 0 次** —— 它们只在标的 can_control 没录时开火；股比、交易结构、
  风险清单的对手方录入率分别是 3% / 1% / 4%。这些约束现在落进方案的
  other_requirements_text，由深评读。
- **百分比口径整张表**：唯一留下的两行（股比）随本轮退役，PE 的倍数口径改成一句话。
- **「多方案」那一段的旧写法**：「共有条件写顶层 fields、不同的写 scenarios」——
  那正是公共层。

新增的：

- **拆分标准**，带一组反差示例。这是本版最要紧的一段：拆多拆少直接决定召回。
- **方案摘要口径**。方案不设名称，摘要就是标题，它同时是反向检索首轮扫描读的材料。
- **其他要求口径**：AI 归纳，保留全部约束、去掉冗余表达，不是原话照抄。

⚠️ **大区展开放在代码里，不在提示词里。** `region_dictionary.REGION_GROUPS` 早就在
做这件事，而且更稳：提示词里的表每次调用都要模型重新照抄一遍，改词表要发新版本，
模型还可能漏抄。这一版只告诉模型「说到大区就原样写大区名」。

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

字段契约 JSON（字段名、所属模块 module、值类型、可选枚举、is_condition 是否参与
初筛，以及 **scope** —— `intent` 落在需求本身，`scenario` 落在方案里）：
{{ field_contract_json }}

标准省级行政区划清单：
{{ province_list }}

结构化字段候选值规则 JSON：
{{ enum_contract_json }}

只输出有证据支撑的内容。不要输出值为 null 的字段，不要重复原文。
**字段契约里没有的字段一律不要输出** —— 写了不会报错，会被静默丢弃。

输出结构：
{
  "fields": { "需求容器字段": 值 },
  "scenarios": [
    {"fields": {"方案字段": 值},
     "needs_confirmation": [{"field": "字段名", "proposed_value": "推断值", "reason": "为什么要顾问确认"}]}
  ],
  "profile_sections": [
    {"section_code": "intent_scope | intent_financial | intent_deal",
     "content_text": "整条需求层面、不属于任何单个方案的说明"}
  ],
  "needs_confirmation": [
    {"field": "需求容器字段", "proposed_value": "推断值", "reason": "为什么要顾问确认"}
  ]
}

**一条需求 = 一个容器 + 1..N 个方案。**
容器只装：需求名称、级别、状态、暂停原因。
业务方向与全部门槛**只装在方案里** —— 顶层 fields 里写门槛不会报错，会被丢掉。
**scenarios 至少要有一个元素。** 只有一种要求时就是一个方案，不是「不给方案」。

━━ 什么时候拆成多个方案（本段最要紧，拆多拆少直接决定召回）━━

把这条需求的各维度取值列出来 —— 业务、地区、上市状态、营收、净利、市值、估值、PE。
**如果任意组合都成立，就是一个方案；如果存在「A 维度取了这个值，B 维度就必须取那个
值」的绑定，就按绑定拆。**

**单个字段有多个值不算绑定。** 例：

  「聚焦大农业：粮油作物、畜禽（排除单纯养殖）、茶叶与中药材提取、果蔬加工、
   盐化工与调味品、现代种业、智慧农业与农机装备、生物制药。上市非上市均可，
   规模灵活，从四五亿估值、年营收三四千万的中小标的到五十亿级农机龙头都看。」
  → **一个方案**。十来个赛道是一个字段的多值，任一赛道配任一规模都成立。

  「一、酒店：行业排名前 60，100 间房以上，地址不限。
   二、旅游产业：旅行社批发商、渠道商，轻资产酒店运营公司。
   三、粮油食品：文商旅、食品、调味品，广东优先，收入 5-50 亿、
       净利润 1000 万以上、估值不超 50 亿。」
  → **拆三个方案**。拿酒店的业务配粮油食品的财务门槛不成立，业务与门槛成套对应。

  「上市公司：市值 50 亿以内、近三年净利润均在 1000 万以上。
   非上市公司：净利润 2000 万以上，PE 原则上不超过 13 倍。」
  → **拆两个方案**。上市状态与财务门槛成套绑定。

**轴不固定。** 拆的依据可能是业务板块、上市状态、交易结构、也可能是别的 ——
**不要预设「按上市/非上市拆」**，看材料自己怎么分。

**拿不准就拆。** 两个方向的代价不对称：拆多了每个方案门槛更少、召回更宽，损失有限；
该拆没拆，不兼容的条件会被 AND 在一起（上市 AND 非上市 = 空集），直接筛出零条。

━━ 方案的三个文本字段 ━━

scenario_summary（**摘要，同时是这个方案的标题**，方案不设名称）：
- 一段话说清这个方案**要买什么业务、什么地域、什么规模**。
- 它是反向检索首轮扫描唯一读的东西 —— 为标的找买家时，判断「这家买家想不想要
  这个项目」只读这一栏。所以要具体到能判断的程度。
  · 好：「收购文商旅、食品、调味品类企业，广东和珠三角优先；收入 5-50 亿、
    净利润 1000 万以上、估值不超 50 亿。」
  · 差：「符合公司战略方向的优质标的」（等于什么都没说，这个方案在反向检索里
    就等于不存在）
- 写成**一段话**，不要写成条目列表。
- 材料说得含糊时照实写含糊的原话，不要替买家编一个具体方向。

business_tags_json：自由标签数组，写这个方案关注的细分方向，5 个以内。
「薄膜电容器」「线控底盘」「固态电池」「宠物医疗」这类词直接写，
**不需要也不要去套任何行业分类**。

excluded_business_text：这个方案明确说不要的方向，自由文本。
「不看房地产」「排除单纯养殖环节」这类。没提就整个省略。

other_requirements_text（**其他要求**）：
- 装**结构化字段接不住的全部约束**：偏好语气（「广东优先」「上市公司优先」）、
  控股与并表诉求、股比、交易结构与支付方式、迁址、团队留任、对赌、返投、
  负债率、净利率、毛利率、溢价上限、市场地位（「细分前三」）、
  合规与风险要求（「无诉讼无冻结」「近三年无非标审计意见」）、买家自身产业优势。
- **是归纳，不是原话照抄**：保留全部约束信息，去掉冗余表达。
  「盈利能力：需"盈利比较好"，具备稳定的营收和利润表现」→「盈利稳定，营收与利润
  表现良好」。
- 阈值带弹性口径时，**数字进字段、口径进这里**：
  「市值 50 亿以内，可适当放宽到 100 亿」→ max_market_cap_yuan = 5000000000，
  这里写「市值 50 亿以内，可适当放宽至 100 亿」。
  「近三年净利润均在 1000 万以上」→ min_net_profit_yuan = 10000000，
  这里写「近三年净利润均需 1000 万以上，不是单年」。
- 写完整的句子，不要写成关键词堆。宁可多留也不要丢。

━━ 方案的门槛字段 ━━

required_regions_json（**要求地区**，硬要求）：
- 平铺数组，元素形如 {"province": "江苏省", "city": "苏州市"}，
  省名从「标准省级行政区划清单」里逐字取。
- **只填到材料说得准的层级**：只说「江苏」就是 [{"province": "江苏省"}]，
  那表示全省都可以。补全成三级会让它变成「江苏省某个具体的市」，筛错粒度。
- **只有硬性要求才填。**「广东优先」「最好在长三角」「以珠三角为主」这类
  **偏好一律不填这一列**，写进 other_requirements_text。
  实测 36 家买家里提到地域的 16 家中有 9 家说的是「优先/最好」——
  把偏好填成硬筛会把外地的好标的直接筛掉。
- **说到大区就原样写大区名**：「长三角」「大湾区」「京津冀」「华东」这类说法，
  直接写成 [{"province": "长三角"}]，系统会自动展开成省份清单。
  **不要自己猜一个省** —— 那正是历史上出错最多的地方（把「优选长三角」填成了
  买家自己所在的广东省）。
- **买家在哪个省，和它想买哪里的标的，是两件事。** 材料没说想买哪里，就不要
  拿买家自己的所在地去填。
- 「全国」「不限」「无地域限制」→ 整个字段省略（空数组正确地表示「无约束」）。

acceptable_listed_status_json：
- 逐项列出这个方案能接受的标的上市状态，取值只有 listed / unlisted / pre_ipo。
- 材料没提上市状态就**整个省略**；「上市不上市都行」也是省略
  （三个都能接受 = 没有这个门槛）。
- 材料说「已上市的不考虑」，要输出 ["unlisted", "pre_ipo"] —— 注意方向，
  把排除写成「都可以」是反的。

财务口径：
- min_valuation_yuan / max_valuation_yuan 是估值区间。
- min_market_cap_yuan / max_market_cap_yuan 只在明确出现市值证据时使用，
  **绝不能把估值搬进市值字段**。
- max_pe 是**倍数**不是百分比：「PE 不超过 15 倍」→ 15，不要乘 100 也不要除以 100。
- 金额一律换算成人民币元的数字，位数自己数一遍再写：
  「三千万」→ 30000000（3 后面 7 个 0）、「5000万」→ 50000000、
  「1.2亿」→ 120000000、「6亿」→ 600000000（6 后面 8 个 0）。
  少写一个 0 就差十倍，而十倍的门槛不会报错，只会静静地筛错人。

━━ 需求层的「其他」（profile_sections）━━
- 只装**整条需求层面**、不属于任何单个方案的说明：这次沟通的背景、
  下一步安排、顾问的观察。
- 属于某个方案的说明写进那个方案的 other_requirements_text，不要写在这里。
- 每个模块最多一条，section_code 用 intent_scope / intent_financial / intent_deal。

━━ 待确认 ━━
- 语义结果里的 unknowns 逐条进 needs_confirmation。
- 属于某个方案的待确认项写进那个方案的 needs_confirmation，
  只有落在容器字段（级别、状态）上的才写顶层。
- **拆不开的条件分叉整句进 needs_confirmation，绝不挑一个留下、把另一个丢掉。**

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
        "name": "买家需求字段规范化 v0.5.0（方案化：先拆方案再抽字段）",
        "description": (
            "0901 买家需求方案化。解析从「抽一组字段」变成「先把材料切成 N 个方案、"
            "再对每个方案抽一组字段」，取消公共层（实测它与方案层冲突 11 个格子）；"
            "新增拆分标准与方案摘要口径；控股/并表/股比/交易结构/风险清单/排除地区"
            "六项退役，内容并入方案的其他要求。"
        ),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_buyer_intent_scenario_prompt.py"},
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
        # 0901 方案化退役的七项
        "requires_control",
        "requires_consolidation",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "transaction_types_json",
        "unacceptable_risk_flags_json",
        "excluded_regions_json",
        "major_risk_tolerance_summary",
        "acceptable_regions_json",
        "intent_business_summary",
        "intent_business_tags_json",
    ):
        assert retired not in USER_PROMPT_TEMPLATE, f"正文里还在讲已退役的 {retired}"
    print("[OK] 正文里没有任何已退役字段的规则")

    # 方案字段的口径必须在正文里，否则模型只从字段契约看到一个字段名。
    for column in (
        "scenario_summary",
        "business_tags_json",
        "excluded_business_text",
        "other_requirements_text",
        "required_regions_json",
        "acceptable_listed_status_json",
    ):
        assert column in USER_PROMPT_TEMPLATE, f"方案字段 {column} 没有口径说明"
    print("[OK] 六个方案字段的口径都在正文里")

    # 拆分标准是本版最要紧的一段：拆多拆少直接决定召回，而拆错不报错。
    assert "如果任意组合都成立" in USER_PROMPT_TEMPLATE, "缺拆分判据"
    assert "单个字段有多个值不算绑定" in USER_PROMPT_TEMPLATE, "缺「多值不等于分叉」"
    assert "拿不准就拆" in USER_PROMPT_TEMPLATE, "缺默认倾向"
    assert "不要预设" in USER_PROMPT_TEMPLATE, "必须写明轴不固定"
    assert "一个方案" in USER_PROMPT_TEMPLATE and "拆三个方案" in USER_PROMPT_TEMPLATE, (
        "拆分标准必须带一组反差示例：只讲规则的话，模型会把每个小标题都拆成一个方案"
    )
    print("[OK] 拆分标准、反差示例、默认倾向都在")

    assert "只读这一栏" in USER_PROMPT_TEMPLATE, "摘要口径必须点明它是首轮扫描唯一读的东西"
    assert "系统会自动展开" in USER_PROMPT_TEMPLATE, "大区展开在代码侧，正文要告诉模型原样写"
    assert "偏好一律不填这一列" in USER_PROMPT_TEMPLATE, (
        "要求地区是硬要求，偏好必须明确指向 other_requirements_text —— "
        "实测提到地域的买家里 56% 说的是「优先/最好」"
    )
    assert "scenarios 至少要有一个元素" in USER_PROMPT_TEMPLATE, (
        "门槛只住在方案里，一个方案都不给等于这条需求什么都没说"
    )
    print("[OK] 摘要口径、大区、偏好去向、方案非空四条都在")

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
    print("⚠️ 上线后必须对存量 48 条需求批量重跑一次解析。")
    print("   迁移 023 的回填只是把旧内容搬进方案，它**猜不出**公共层的某条约束")
    print("   属于哪一档 —— 那正是这一版要解决的问题，只有重跑能真正解决。")
    print("   生产库 524 条字段来源记录里人工修改为 0，重跑不会覆盖任何人的手工成果；")
    print("   88 条来自业务更新采纳的会走待确认，不直接覆盖。")


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
