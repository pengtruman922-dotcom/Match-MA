"""发布 `buyer_intent_update_parser` v0.4.0（买家需求方案化，0901）。

配套《买家需求方案化重构方案0901.md》。

**这个节点管业务更新**：顾问在某条需求下写一段话（「市值放宽到 100 亿」），
它把那段话变成 `buyer_intent_update` 动作。0901 起门槛住在方案里，
所以一条更新其实是在改**某个方案** —— 而它必须说清楚是哪一个。

与 v0.3.0 的差别只有一处，但那一处不改就会出错：

- **多方案需求必须给 `scenario_index`。** 不给就默认打到第一个方案，于是
  「非上市档的 PE 放宽到 15」会被写进上市档。**那不报错** ——
  库里安安静静地存了一个错的数字，而两档的数字本来就不一样，人不去对根本看不出来。
  上下文里现在带着这条需求的全部方案（`bound_buyer_intents[].scenarios`，
  每个方案带 `scenario_index` 与它的摘要），模型据此判断这次改的是哪一档。
- 顺带删掉 `intent_summary` 这个示例字段：它 0828 已退役。

字段名白名单在代码侧是**两张表的并集**（`handlers/common.py` 的
`BUYER_INTENT_CHANGE_FIELDS`），分流在 `extracted_action_apply` 做 ——
所以这份提示词只需要教模型「哪些字段属于方案、怎么定位方案」，
不需要它自己判断该写哪张表。

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
NODE_NAME = "buyer_intent_update_parser"
VERSION = "v0.4.0"

# 与 v0.3.0 一字不差。
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["actions"],
    "properties": {
        "actions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "action_type",
                    "target_entity_type",
                    "target_entity_id",
                    "proposed_changes_json",
                ],
                "properties": {
                    "confidence": {"type": ["number", "null"]},
                    "action_type": {"type": "string"},
                    "target_entity_id": {"type": ["string", "null"]},
                    "raw_evidence_text": {"type": ["string", "null"]},
                    "target_entity_type": {"type": ["string", "null"]},
                    "proposed_changes_json": {"type": "object"},
                },
            },
        }
    },
}

# 与 v0.3.0 一字不差：这一版不改角色设定。
SYSTEM_PROMPT = """You parse updates for one known buyer acquisition intent. Output one JSON object with an actions array and no Markdown. Every action item MUST use exactly these keys: action_type, target_entity_type, target_entity_id, proposed_changes_json. Never use the aliases action, target, target_id, proposed_changes, or changes. Never create seller facts, target follow-ups, buyer-party changes, relations, or target links. Do not invent facts or UUIDs.

只提取买家主体和买家意向当前有效的信息。与某个标的的沟通过程、反馈、推进状态和下一步必须忽略，不得写入意向摘要，也不得输出跟进或关系 action。"""

USER_PROMPT_TEMPLATE = """Context JSON: {{ context_json }}

Raw input: {{ raw_text }}

Return exactly this shape (repeat one object per extracted action):
{"actions":[{"action_type":"buyer_intent_update","target_entity_type":"buyer_intent","target_entity_id":"<copy the bound buyer intent UUID from context, or null>","proposed_changes_json":{"scenario_index":0,"min_net_profit_yuan":20000000},"confidence":0.9,"raw_evidence_text":"concise supporting excerpt"}]}

Allowed action_type values for this node:
1. buyer_intent_update when acquisition requirements changed.
2. unresolved_item only when neither applies.

━━ 一条需求 = 一个容器 + 1..N 个方案 ━━

**业务方向与全部门槛住在方案里**，容器只有 intent_name / intent_grade /
status / pause_reason。

上下文的 `bound_buyer_intents[].scenarios` 列出了这条需求现有的全部方案，
每个方案带 `scenario_index`（从 0 开始）和它的摘要与门槛。

**改方案字段时必须在 proposed_changes_json 里带上 `scenario_index`，
指明改的是哪一个方案。**

- 只有一个方案时写 `"scenario_index": 0`。
- 多个方案时，**读方案的摘要判断这段话在说哪一档**，写对应的序号。
  例：需求有「上市公司收购方案」(index 0) 和「非上市公司收购方案」(index 1)，
  输入是「非上市那档的 PE 可以放宽到 15 倍」→ `{"scenario_index": 1, "max_pe": 15}`。
- **判不出是哪一档就不要猜。** 输出 unresolved_item，把原话留在
  raw_evidence_text 里交给顾问 —— 猜错不会报错，库里会安安静静地存一个错的数字，
  而两档的数字本来就不一样，人不去对根本看不出来。
- 改容器字段（级别、状态、暂停原因）时**不要带 scenario_index**。

━━ 方案字段 ━━

scenario_summary（摘要，同时是这个方案的标题）· business_tags_json（自由标签数组）·
excluded_business_text（明确不要的方向）· other_requirements_text（其他要求）·
required_regions_json（要求地区，[{"province":"江苏省","city":"苏州市"}]）·
acceptable_listed_status_json（listed / unlisted / pre_ipo 的子集）·
min_revenue_yuan · min_net_profit_yuan · max_pe ·
min_market_cap_yuan · max_market_cap_yuan · min_valuation_yuan · max_valuation_yuan

几条口径：
- **要求地区只装硬性要求。**「广东优先」「最好在长三角」这类偏好写进
  other_requirements_text —— 填进硬筛会把外地的好标的直接筛掉。
  「长三角」「大湾区」原样写成 [{"province": "长三角"}]，系统会展开成省份。
- **市值两项只在明确出现市值证据时使用**，绝不能把估值搬进市值字段。
- max_pe 是**倍数**：「PE 不超过 15 倍」→ 15。
- 金额换算成人民币元的数字，位数自己数一遍：「三千万」→ 30000000、
  「1.2亿」→ 120000000。少写一个 0 就差十倍，而十倍的门槛不会报错。
- 阈值带弹性口径时**数字进字段、口径进 other_requirements_text**：
  「市值 50 亿以内，可适当放宽到 100 亿」→ max_market_cap_yuan = 5000000000，
  另外把那句口径写进 other_requirements_text。

━━ 新增方案 ━━

材料在讲一个**现有方案都装不下的新方向**（原来只找酒店，现在还要找粮油食品，
两者的业务与门槛成套对应、互不兼容）时，输出 unresolved_item 说明需要新增方案，
不要把新方向硬塞进某个现有方案 —— 那会让两档的条件混成一档，直接筛出零条。

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
        "name": "买家需求更新解析 v0.4.0（方案定位）",
        "description": (
            "0901 买家需求方案化。门槛住在方案里，一条更新必须用 scenario_index 指明"
            "改的是哪一档；判不出就走 unresolved_item 交给顾问，不猜。"
            "同批删掉已退役的 intent_summary 示例。"
        ),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_buyer_intent_update_parser_v040_prompt.py"},
    }


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

    for retired in (
        "intent_summary",
        "industries_json",
        "region_constraints_json",
        "region_scope_summary",
        "requires_control",
        "requires_consolidation",
        "desired_equity_ratio_min",
        "transaction_types_json",
        "unacceptable_risk_flags_json",
        "excluded_regions_json",
        "max_debt_ratio",
        "preferred_listed_status",
        "intent_business_summary",
        "intent_business_tags_json",
    ):
        assert retired not in USER_PROMPT_TEMPLATE, f"正文里还在讲已退役的 {retired}"
    print("[OK] 正文里没有任何已退役字段")

    from backend.app.registry.indicators import writable_columns

    declared = set(writable_columns("parse", "buyer_intent_scenario"))
    assert declared == set(SCENARIO_FIELDS), (
        f"方案字段清单与注册表不一致；注册表多出={sorted(declared - set(SCENARIO_FIELDS))}，"
        f"脚本多出={sorted(set(SCENARIO_FIELDS) - declared)}"
    )
    for column in SCENARIO_FIELDS:
        assert column in USER_PROMPT_TEMPLATE, f"方案字段 {column} 没有出现在正文里"
    print(f"[OK] {len(SCENARIO_FIELDS)} 个方案字段都在正文里，且与注册表逐字段一致")

    # 方案定位是这一版存在的理由。少了它，多方案需求的更新会静默打到第一个方案。
    assert "scenario_index" in USER_PROMPT_TEMPLATE
    assert USER_PROMPT_TEMPLATE.count("scenario_index") >= 4, "方案定位要讲清楚，一句话不够"
    assert "判不出是哪一档就不要猜" in USER_PROMPT_TEMPLATE, (
        "猜错不报错、库里静静存一个错的数字，这条必须写明"
    )
    assert "不要带 scenario_index" in USER_PROMPT_TEMPLATE, "容器字段不该带方案定位"
    print("[OK] 方案定位、判不出就不猜、容器字段例外三条都在")

    # 代码侧的白名单必须收得住 scenario_index，否则模型给了也会被当成越权字段丢掉。
    from backend.app.jobs.handlers.common import BUYER_INTENT_CHANGE_FIELDS

    assert "scenario_index" in BUYER_INTENT_CHANGE_FIELDS, (
        "handlers/common.BUYER_INTENT_CHANGE_FIELDS 必须放行 scenario_index"
    )
    assert declared <= BUYER_INTENT_CHANGE_FIELDS, "方案字段没有全部进入抽取白名单"
    print("[OK] 代码侧白名单收得住 scenario_index 与全部方案字段")

    print(f"[info] 规则正文 {len(USER_PROMPT_TEMPLATE)} 字符（v0.3.0 为 1396）")

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
