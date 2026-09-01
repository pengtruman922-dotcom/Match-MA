"""发布 `buyer_intent_parser` v0.10.0（买家需求方案化，0901）。

配套《买家需求方案化重构方案0901.md》。

**这个节点是两阶段解析的兜底。** `buyer_intent_semantic_parser → buyer_intent_normalizer`
两个都就绪时走两阶段，任一个没就绪就整体由它代跑（`registry/nodes.py` 的
`understudy` 声明）。所以它必须和 normalizer **产出同一个形状** —— 停在旧形状
不会报错，只会让兜底那条路解析出来的需求**没有任何门槛**：门槛字段现在住在
方案表上，顶层 fields 里写它们会被当成 unsupported 静默丢掉。

与 v0.9.0 的差别：

- **输出多一层 scenarios。** 一条需求 = 一个容器挂 1..N 个各自完整的方案，
  命中任意一个即算命中。**没有公共层** —— 实测生产库公共层与方案层的取值
  冲突 11 个格子，它是解析器猜不出某条约束属于哪一档时的兜底桶。
- **删掉整段行业口径**（0828 判决一：买家需求侧行业字典下线，六列退役），
  连带 `industry_l1_list` / `industry_l2_list` 两个变量从 NodeSpec 移除。
  **handler 仍然照常传这两个变量** —— 线上可能正跑着引用它们的 v0.9.0，
  撤掉传参会让那一版渲染成 "null"。
- **删掉控股/并表、股比、交易结构、风险清单、排除地区、负债率与两个利润率、
  PS、融资阶段、上市板块**的全部口径：0901 全部退役，实测 48 需求 x 71 标的
  全量对判，控股与并表这两个用得最多的字段**真淘汰 0 次**，股比/交易结构/
  风险清单的对手方录入率分别是 3% / 1% / 4%。内容进方案的 other_requirements_text。
- **新增拆分标准**（带反差示例）与**方案摘要口径**。

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
NODE_NAME = "buyer_intent_parser"
VERSION = "v0.10.0"

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scenarios"],
    "properties": {
        "fields": {"type": "object"},
        "scenarios": {"type": "array", "items": {"type": "object"}, "minItems": 1},
        "needs_confirmation": {"type": "array", "items": {"type": "object"}},
    },
}

# 与 v0.9.0 一字不差：这一版不改角色设定，只改规则正文与输出形状。
SYSTEM_PROMPT = """You parse one buyer acquisition requirement. Output one JSON object with a fields object and no Markdown. Do not output buyer_party. Do not invent facts. Use Chinese for user-facing text and exact canonical enum values where required.

只提取买家主体和买家意向当前有效的信息。与某个标的的沟通过程、反馈、推进状态和下一步必须忽略，不得写入意向摘要，也不得输出跟进或关系 action。"""

USER_PROMPT_TEMPLATE = """Raw buyer requirement:
{{ raw_requirement_text }}

Existing intent context JSON:
{{ buyer_profile_json }}

Return only supported fields that have evidence. Do not output null fields and do not repeat raw_requirement_text.

输出结构：
{
  "fields": { "intent_grade": "...", "status": "...", "pause_reason": "..." },
  "scenarios": [
    {"fields": {"方案字段": 值},
     "needs_confirmation": [{"field": "字段名", "proposed_value": "推断值", "reason": "为什么要顾问确认"}]}
  ],
  "needs_confirmation": [{"field": "容器字段", "proposed_value": "...", "reason": "..."}]
}

**一条需求 = 一个容器 + 1..N 个方案。**
顶层 fields 只装容器字段：intent_grade / status / pause_reason。
业务方向与全部门槛**只装在方案里** —— 顶层写门槛不会报错，会被静默丢掉。
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

━━ 方案的字段（**只有这十三个，别的一律不要输出**）━━

scenario_summary（**摘要，同时是这个方案的标题**，方案不设名称）：
- 一段话说清这个方案**要买什么业务、什么地域、什么规模**。
- 它是反向检索首轮扫描唯一读的东西 —— 为标的找买家时，判断「这家买家想不想要
  这个项目」只读这一栏。所以要具体到能判断的程度。
  · 好：「收购文商旅、食品、调味品类企业，广东和珠三角优先；收入 5-50 亿、
    净利润 1000 万以上、估值不超 50 亿。」
  · 差：「符合公司战略方向的优质标的」（等于什么都没说，这个方案在反向检索里
    就等于不存在）
- 写成**一段话**，不要写成条目列表。材料含糊时照实写含糊的原话。

business_tags_json：自由标签数组，这个方案关注的细分方向，5 个以内。
「薄膜电容器」「线控底盘」「固态电池」这类词直接写，**不套任何行业分类**。

excluded_business_text：这个方案明确说不要的方向，自由文本。没提就省略。

other_requirements_text（**其他要求**）：
- 装**结构化字段接不住的全部约束**：偏好语气（「广东优先」「上市公司优先」）、
  控股与并表诉求、股比、交易结构与支付方式、迁址、团队留任、对赌、返投、
  负债率、净利率、毛利率、溢价上限、市场地位（「细分前三」）、
  合规与风险要求（「无诉讼无冻结」「近三年无非标审计意见」）、买家自身产业优势。
- **是归纳，不是原话照抄**：保留全部约束信息，去掉冗余表达。
- 阈值带弹性口径时，**数字进字段、口径进这里**：
  「市值 50 亿以内，可适当放宽到 100 亿」→ max_market_cap_yuan = 5000000000，
  这里写「市值 50 亿以内，可适当放宽至 100 亿」。
  「近三年净利润均在 1000 万以上」→ min_net_profit_yuan = 10000000，
  这里写「近三年净利润均需 1000 万以上，不是单年」。
- 写完整的句子，不要写成关键词堆。宁可多留也不要丢。

required_regions_json（**要求地区**，硬要求）：
- 平铺数组，元素形如 {"province": "江苏省", "city": "苏州市"}。
- **只填到材料说得准的层级**：只说「江苏」就是 [{"province": "江苏省"}]，表示全省都可以。
- **只有硬性要求才填。**「广东优先」「最好在长三角」这类**偏好一律不填这一列**，
  写进 other_requirements_text —— 实测 36 家买家里提到地域的 16 家中有 9 家说的是
  「优先/最好」，把偏好填成硬筛会把外地的好标的直接筛掉。
- **说到大区就原样写大区名**：「长三角」「大湾区」「京津冀」直接写成
  [{"province": "长三角"}]，系统会自动展开成省份清单。**不要自己猜一个省** ——
  那正是历史上出错最多的地方（把「优选长三角」填成了买家自己所在的广东省）。
- **买家在哪个省，和它想买哪里的标的，是两件事。**
- 「全国」「不限」→ 整个字段省略（空数组正确地表示「无约束」）。

acceptable_listed_status_json：
- 取值只有 listed / unlisted / pre_ipo。
- 材料没提就**整个省略**；「上市不上市都行」也是省略（三个都接受 = 没有门槛）。
- 「已上市的不考虑」→ ["unlisted", "pre_ipo"]，注意方向。

财务七项：min_revenue_yuan / min_net_profit_yuan / max_pe /
min_market_cap_yuan / max_market_cap_yuan / min_valuation_yuan / max_valuation_yuan
- 市值两项**只在明确出现市值证据时使用**，绝不能把估值搬进市值字段。
- max_pe 是**倍数**：「PE 不超过 15 倍」→ 15，不要乘 100 也不要除以 100。
- 金额一律换算成人民币元的数字，位数自己数一遍再写：
  「三千万」→ 30000000（3 后面 7 个 0）、「1.2亿」→ 120000000、
  「6亿」→ 600000000（6 后面 8 个 0）。少写一个 0 就差十倍，而十倍的门槛
  不会报错，只会静静地筛错人。

━━ 待确认 ━━
属于某个方案的待确认项写进那个方案的 needs_confirmation，只有落在容器字段
（级别、状态）上的才写顶层。**拆不开的条件分叉整句进 needs_confirmation，
绝不挑一个留下、把另一个丢掉。**

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
        "name": "买家新建解析 v0.10.0（方案化：先拆方案再抽字段）",
        "description": (
            "0901 买家需求方案化。兜底节点跟上两阶段的输出形状：一条需求 = 容器 + "
            "1..N 个各自完整的方案，取消公共层；删掉行业口径与六项退役条件的规则正文；"
            "新增拆分标准与方案摘要口径。"
        ),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_buyer_intent_parser_v0100_prompt.py"},
    }


RETIRED_FIELDS = (
    "industries_json",
    "industry_l2_json",
    "industry_focus_tags_json",
    "industry_primary",
    "industry_secondary",
    "excluded_industries_json",
    "region_constraints_json",
    "region_scope_summary",
    "preferred_listed_status",
    "financing_stage_requirement_summary",
    "listing_board_requirement_summary",
    "max_debt_ratio",
    "min_net_margin",
    "min_gross_margin",
    "max_ps",
    "max_premium_rate",
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
    "transaction_types_json",
    "transaction_type",
    "unacceptable_risk_flags_json",
    "major_risk_tolerance_summary",
    "excluded_regions_json",
    "acceptable_regions_json",
    "intent_business_summary",
    "intent_business_tags_json",
    "intent_summary",
)

SCENARIO_FIELDS = (
    "scenario_summary",
    "business_tags_json",
    "excluded_business_text",
    "other_requirements_text",
    "required_regions_json",
    "acceptable_listed_status_json",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "max_pe",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "min_valuation_yuan",
    "max_valuation_yuan",
)


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")

    for retired in RETIRED_FIELDS:
        assert retired not in USER_PROMPT_TEMPLATE, f"正文里还在讲已退役的 {retired}"
    print(f"[OK] 正文里没有任何已退役字段的规则（查了 {len(RETIRED_FIELDS)} 个）")

    # 兜底节点拿不到 field_contract_json，字段清单只能写在正文里 ——
    # 漏一个的表现是「那个字段永远解析不出来」，而它不报错。
    from backend.app.registry.indicators import writable_columns

    declared = set(writable_columns("parse", "buyer_intent_scenario"))
    assert declared == set(SCENARIO_FIELDS), (
        f"方案字段清单与注册表不一致；注册表多出={sorted(declared - set(SCENARIO_FIELDS))}，"
        f"脚本多出={sorted(set(SCENARIO_FIELDS) - declared)}"
    )
    for column in SCENARIO_FIELDS:
        assert column in USER_PROMPT_TEMPLATE, f"方案字段 {column} 没有出现在正文里"
    print(f"[OK] {len(SCENARIO_FIELDS)} 个方案字段都在正文里，且与注册表逐字段一致")

    assert "如果任意组合都成立" in USER_PROMPT_TEMPLATE, "缺拆分判据"
    assert "单个字段有多个值不算绑定" in USER_PROMPT_TEMPLATE, "缺「多值不等于分叉」"
    assert "拿不准就拆" in USER_PROMPT_TEMPLATE, "缺默认倾向"
    assert "不要预设" in USER_PROMPT_TEMPLATE, "必须写明轴不固定"
    assert "一个方案" in USER_PROMPT_TEMPLATE and "拆三个方案" in USER_PROMPT_TEMPLATE, (
        "拆分标准必须带一组反差示例：只讲规则的话，模型会把每个小标题都拆成一个方案"
    )
    assert "scenarios 至少要有一个元素" in USER_PROMPT_TEMPLATE
    assert "偏好一律不填这一列" in USER_PROMPT_TEMPLATE
    print("[OK] 拆分标准、反差示例、默认倾向、方案非空、偏好去向都在")

    # 兜底节点与两阶段必须产出同一个形状，否则「走了哪条路」会决定数据长什么样。
    assert OUTPUT_SCHEMA["required"] == ["scenarios"], "scenarios 必须是必填"
    print("[OK] 输出 schema 要求 scenarios 非空")

    print(f"[info] 规则正文 {len(USER_PROMPT_TEMPLATE)} 字符（v0.9.0 为 3590）")

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
