"""为四个「代码已引用、从未配置」的 AI 节点发布 v0.1.0 提示词。

这四个节点是买家两阶段解析和推荐双向深评。它们的代码早就写好了，但提示词
一直没人写，所以从上线起就由代跑节点承担：买家解析走单阶段
`buyer_intent_parser`，深评走共用的 `recommendation_deep_eval`。

**发布提示词不会改变任何运行时行为。** `_get_default_node_config` 要求节点先
有 `model_node_config` 行，这四个节点都没有，因此运行时仍然走代跑。真正的切换
发生在有人到设置页给它们选模型的那一刻 —— 那是一次独立的、需要单独验证的
AI 行为变更。

内容基线：
- 两个买家节点从 `buyer_intent_parser` v0.7.0 拆出来。行业口径、财务口径、
  资本市场口径三组硬规则原样保留，只是按阶段分配：语义阶段不做字段映射和
  枚举归一，规范化阶段不再接触原文。
- 两个方向深评节点从 `recommendation_deep_eval` v0.2.0 复制。评级标准、排除
  优先、禁止用买方画像反推需求这些规则一字不改，只把方向固定下来，让模型
  知道谁是锚、谁是候选。

用法（必须从仓库根目录运行）：
    python scripts/seed_v01_prompts.py --dry-run
    python scripts/seed_v01_prompts.py --apply
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

sys.path.insert(0, "scripts")

import match_ma_api_tools as api  # noqa: E402

API_BASE = "https://match-ma-production.up.railway.app/api/v1"


SEMANTIC_SYSTEM = """你负责买家并购需求解析的第一阶段：读懂原始材料，把意思拆开。

只做语义理解，不做字段映射，不做枚举归一，不做单位换算 —— 那些是第二阶段的事。
输出一个 JSON 对象，不要 Markdown。不要臆造材料里没有的事实。

只提取买家主体和买家意向当前有效的信息。与某个标的的沟通过程、反馈、推进状态和
下一步必须忽略，不得写入需求描述。"""

SEMANTIC_USER = """买家需求原文：
{{ raw_requirement_text }}

买家已有信息 JSON：
{{ buyer_profile_json }}

按下面的结构输出：
{
  "intent_name": "一句话概括这条需求",
  "summary": "买家想买什么样的标的，用中文完整叙述",
  "common_conditions": [
    {"aspect": "行业 / 财务 / 地区 / 股权 / 交易 / 风险 / 其他",
     "statement": "这条条件说的是什么，保留原文口径",
     "strength": "hard | preference | unknown",
     "evidence": "支撑它的原文片段"}
  ],
  "scenarios": [
    {"name": "方案名，如「方案A」或买家自己的叫法",
     "statement": "这个方案整体要什么",
     "conditions": [{"aspect": "...", "statement": "...", "strength": "...", "evidence": "..."}]}
  ],
  "excluded": [{"statement": "明确不要什么", "evidence": "原文片段"}],
  "unknowns": ["材料里提到但说不清、需要顾问确认的点"],
  "buyer_party": {"statement": "关于买方自身的描述，如集团背景、主营、所在地"}
}

拆解规则：
1. 买家如果给了多个并列的可选方案（「或者」「另一种是」「A 方案 / B 方案」），
   每个方案单独进 scenarios；所有方案都适用的条件放 common_conditions。
   只有一种要求时 scenarios 留空数组。
2. strength 区分硬性和偏好：「必须」「不低于」「否则不看」是 hard；
   「优先」「最好」「可以放宽」是 preference；说不清的是 unknown。
   不要把偏好升格成硬性条件。
3. evidence 必须是原文里真实出现过的片段，不要复述、不要翻译。
4. 数字保留原文写法（「三千万」就写「三千万」，不要换算成 30000000），
   单位换算交给第二阶段。
5. 行业、地区、上市状态等一律保留买家的原话，不要映射到任何标准值。
6. buyer_party 只描述买方自己，不要把它写成对标的的要求。
7. 材料里没有的内容一律不写，宁可留空也不要补齐。"""

SEMANTIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary"],
    "properties": {
        "intent_name": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "common_conditions": {"type": "array", "items": {"type": "object"}},
        "scenarios": {"type": "array", "items": {"type": "object"}},
        "excluded": {"type": "array", "items": {"type": "object"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "buyer_party": {"type": ["object", "null"]},
    },
}


NORMALIZER_SYSTEM = """你负责买家并购需求解析的第二阶段：把第一阶段拆好的语义结构落成规范字段。

输入是语义解析的产物，不是原始材料 —— 不要再去推断材料里可能有什么，
只处理已经拆出来的内容。输出一个 JSON 对象，含 fields 对象，不要 Markdown。
不要输出 buyer_party。不要臆造事实。

用户可见文本用中文；需要标准值的字段必须使用给定清单里的精确取值。"""

NORMALIZER_USER = """语义解析结果 JSON：
{{ semantic_parse_json }}

买家已有信息 JSON：
{{ buyer_profile_json }}

字段契约 JSON（哪些字段存在、值的类型、可选枚举、是否支持多方案）：
{{ field_contract_json }}

一级行业封闭清单：
{{ industry_l1_list }}

标准省级行政区划清单：
{{ province_list }}

结构化字段候选值规则 JSON：
{{ enum_contract_json }}

只输出有证据支撑的字段。不要输出值为 null 的字段，不要重复原文。

输出结构：
{
  "fields": { "字段名": 值 },
  "needs_confirmation": [
    {"field": "字段名", "value": "推断值", "reason": "为什么需要顾问确认"}
  ]
}

行业口径：
- industries_json 收录所有适用的一级行业，每一项从封闭清单里逐字复制。
- industry_focus_tags_json 保留全部具体赛道说法，如 新式茶饮、宠物医疗、垂类电商SaaS。
- industry_primary 与 industry_secondary 是简洁的中文描述性标签，不是一级行业的替代品。

财务口径：
- min_valuation_yuan 与 max_valuation_yuan 是估值区间。
- min_market_cap_yuan 与 max_market_cap_yuan 只在明确出现市值证据时使用，
  绝不能把估值搬进市值字段。
- max_pe 与 max_ps 是两个不同的倍数。
- min_net_margin 与 min_gross_margin 是数值型百分比。
- 金额一律换算成人民币元的数字（「三千万」→ 30000000）。

资本市场口径：
- preferred_listed_status 只能取 listed、unlisted、preparing_listing、pre_ipo、any、unknown，
  且必须有明确证据支撑。
- A 轮 B 轮等融资细节属于 financing_stage_requirement_summary，不是上市状态。
- 「优先」「一般」「可放宽」描述的是偏好，保留在 priority_summary 或
  preference_summary 里，不要转成硬性事实。

多方案与条件作用：
- 语义结果里 scenarios 非空时，把各方案共有的条件写进对应字段，
  方案之间的差异写进 condition_effects_json，并在 priority_summary 里说明方案关系。
- 语义结果标为 preference 的条件不要写成硬性阈值字段。
- 语义结果里的 unknowns 逐条进 needs_confirmation，并在 unknown_summary 里概述。

其余营收、利润、地区、股权、交易、溢价、负债、风险、排除、偏好类字段，
沿用字段契约里列出的既有 buyer_intent 规范字段。"""

NORMALIZER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {"type": "object"},
        "needs_confirmation": {"type": "array", "items": {"type": "object"}},
    },
}


def _deep_eval_system(anchor_label: str, candidate_label: str) -> str:
    return (
        "You are an M&A matchmaking analyst for Match-MA. "
        f"锚定对象是{anchor_label}，候选是{candidate_label}。"
        "Evaluate candidates using seller-target facts and buyer-intent requirements only. "
        "Buyer-party profile attributes such as capital strength, company scale, location, "
        "main business, group background, or listed status must not affect the grade unless "
        "the buyer intent itself states the same item as an acquisition requirement. "
        "Output one JSON object and no Markdown."
    )


def _deep_eval_user(anchor_label: str, candidate_label: str) -> str:
    return f"""Mode: {{{{ mode }}}}

锚定{anchor_label}：
{{{{ anchor_context }}}}

候选{candidate_label}：
{{{{ candidates_json }}}}

Return:
{{
  "results": [
    {{"index": 0, "grade": "A", "reason": "一句话推荐理由", "risks": "主要风险或不确定点", "info_gaps": "需要补充的信息"}}
  ]
}}

Rules:
1. Grade every candidate exactly once. A means highly suitable, B means worth following, and C means weak fit or a hard mismatch.
2. Apply explicit exclusions and hard thresholds first, including industry, financial, budget, valuation, PE or PS, equity, control, consolidation, listing, region, and risk requirements.
3. Evaluate multiple industries and listing preferences as alternatives unless the intent explicitly says all conditions must hold together.
4. Never infer a buyer requirement from buyer-party profile data. Buyer identity is display context only.
5. A candidate with an exclusion hit or unmet hard threshold cannot receive A.
6. Use only supplied evidence. Put missing target facts in info_gaps instead of inventing them.
7. Keep reason, risks, and info_gaps concise Chinese sentences and use 暂无 when empty.
8. Return every candidate index exactly once, ordered from most to least recommended."""


DEEP_EVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "grade"],
                "properties": {
                    "index": {"type": "integer"},
                    "grade": {"type": "string", "enum": ["A", "B", "C"]},
                    "reason": {"type": ["string", "null"]},
                    "risks": {"type": ["string", "null"]},
                    "info_gaps": {"type": ["string", "null"]},
                },
            },
        }
    },
}


PROMPTS: tuple[dict[str, Any], ...] = (
    {
        "node_name": "buyer_intent_semantic_parser",
        "name": "买家需求语义解析 v0.1.0",
        "system_prompt": SEMANTIC_SYSTEM,
        "user_prompt_template": SEMANTIC_USER,
        "output_schema_json": SEMANTIC_SCHEMA,
    },
    {
        "node_name": "buyer_intent_normalizer",
        "name": "买家需求字段规范化 v0.1.0",
        "system_prompt": NORMALIZER_SYSTEM,
        "user_prompt_template": NORMALIZER_USER,
        "output_schema_json": NORMALIZER_SCHEMA,
    },
    {
        "node_name": "recommendation_deep_eval_to_target",
        "name": "推荐深评·为买家找标的 v0.1.0",
        "system_prompt": _deep_eval_system("买家需求", "标的"),
        "user_prompt_template": _deep_eval_user("买家需求", "标的"),
        "output_schema_json": DEEP_EVAL_SCHEMA,
    },
    {
        "node_name": "recommendation_deep_eval_to_buyer",
        "name": "推荐深评·为标的找买家 v0.1.0",
        "system_prompt": _deep_eval_system("标的", "买家需求"),
        "user_prompt_template": _deep_eval_user("标的", "买家需求"),
        "output_schema_json": DEEP_EVAL_SCHEMA,
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=API_BASE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    token = api._resolve_token(args.api_base)
    for spec in PROMPTS:
        node_name = spec["node_name"]
        existing = api._request_json(
            args.api_base, "GET", f"/model-config/prompts?node_name={node_name}&include_inactive=true", token=token
        )
        rows = existing if isinstance(existing, list) else existing.get("items", [])
        if rows:
            print(f"[skip] {node_name}: 已有 {len(rows)} 个版本 {[r['version'] for r in rows]}")
            continue
        if args.dry_run:
            print(f"[dry-run] {node_name}: 将创建 v0.1.0 "
                  f"(system {len(spec['system_prompt'])} 字 / user {len(spec['user_prompt_template'])} 字)")
            continue
        api._request_json(
            args.api_base,
            "POST",
            "/model-config/prompts",
            token=token,
            json_body={
                "node_name": node_name,
                "version": "v0.1.0",
                "name": spec["name"],
                "system_prompt": spec["system_prompt"],
                "user_prompt_template": spec["user_prompt_template"],
                "output_schema_json": spec["output_schema_json"],
                "template_engine": "jinja",
                "variables_json": [],
                "is_active": True,
                "is_default": True,
            },
        )
        print(f"[created] {node_name} v0.1.0")


if __name__ == "__main__":
    main()
