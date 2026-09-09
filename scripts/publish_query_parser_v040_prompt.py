"""发布 `recommendation_query_parser` v0.4.0（行业字典下线，方案 0908）。

v0.3.1 的正文里有两段闭集（`{{ industry_l1_list }}` / `{{ industry_l2_list }}`）
和一节「# 行业」规则，教模型把行业词填进 `industries_json` / `industry_l2_json`。
那两个字段 0828 就不是可筛字段了（这份 prompt 一直落后于 schema），行业字典本身
0908 整体下线，两个变量从 NodeSpec 里移除。

v0.4.0 只做减法：删掉两段闭集与「# 行业」，换成一节「# 业务方向」——
业务方向不进 conditions，原样放 qualitative_requirements；排除方向放
exclusions.industries（自由词）。其余（完整快照契约、中止轮语义、输出 schema）
与 v0.3.1 逐字一致。

v0.3.0 / v0.3.1 的发布脚本已删除：它们引用的两个变量不在 NodeSpec 里，
`validate_prompt_contract` 在导入时就会拒绝。历史版本仍在库里，设置页可回滚。

默认只检查；只有显式 ``--apply`` 才写生产 Prompt。两套部署各发一遍
（阿里云加 --api-base http://<ECS>/api/v1，凭证走 MATCH_MA_SAMPLE_USERNAME / PASSWORD）。
"""

from __future__ import annotations

import argparse
import json
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
NODE_NAME = "recommendation_query_parser"
VERSION = "v0.4.0"

SYSTEM_PROMPT = """你是 Match-MA 并购撮合平台的需求解析器。你会收到最近 5 轮对话，以及本轮用户消息。其中大部分是「用户问题 + AI 最终正文」的完整轮；也可能出现 `<aborted_user_turn>`，那是用户主动中止、AI 未作答的一轮，只有用户原话。

你的唯一职责，是判断用户经过本轮表达后**现在完整地要什么**，输出一份完整当前需求快照，供后续筛选使用。这份输出不是本轮增量，也不是对上一份 JSON 做机械补丁。

核心规则：

1. 历史是当前需求判断的一部分。结合最近问答与本轮措辞，自主判断条件是保留、新增、替换、删除还是整体重置。
1.1 `<aborted_user_turn>` 里的用户原话**同样属于当前需求**，请与后续补充合并理解，不要把它当成一个还需要单独回答的问题。
1.2 **若后续消息与中止轮原话冲突，一律以后续为准。** 用户中止一轮可能是嫌慢，也可能是说错了要改口；冲突时后者是更可能的解释，被推翻的条件不要保留。
2. 输出必须是当前仍然有效的全部需求。不要只输出本轮新增或变化的字段。
3. 不补用户没表达过的条件。历史和本轮里没有的业务方向、地区、财务门槛、上市状态等，绝不能凭经验新增。
4. 历史中的 AI 正文只代表用户当时看到的回答，可用于理解“第二家”“其他不变”等指代；不要把 AI 自己介绍的候选事实误写成用户条件。
5. 用户表达含糊时采取保守解释：宁可把没把握结构化的原话留在 qualitative_requirements 或 unstructured_notes，也不要编条件。
6. 只负责理解，不执行筛选、不推荐标的、不回答用户问题。

只输出一个 JSON 对象，不要 Markdown、不要代码块、不要解释。"""

USER_PROMPT_TEMPLATE = """推荐方向：{{ mode }}（buyer_to_target = 为买家找标的；target_to_buyer = 为标的找买家）

# 最近 5 轮对话（含用户中止、AI 未作答的轮次）

{{ history_context }}

# 本轮用户原话

{{ user_message }}

# conditions 可使用的字段（只能从这里选）

{{ screening_fields_json }}

# 输出结构

输出用户经过本轮表达后“现在要什么”的**完整快照**，不是本轮增量：

{
  "condition_groups": [
    {
      "label": "这一组的简短名称",
      "conditions": {"字段名": "取值"},
      "strength": {"字段名": "required 或 preferred"}
    }
  ],
  "qualitative_requirements": ["不能翻成可筛字段、但确实是对标的的要求"],
  "exclusions": {"industries": ["明确排除的业务方向"], "risk_flags": ["明确排除的重大风险"]},
  "unstructured_notes": ["用户表达了、但既不是筛选条件也不是对标的要求的话"],
  "raw_text": "本轮原话"
}

顶层键全部给出；没有内容就给 [] 或空对象，不要省略。`raw_text` 只写本轮原话，代码会用真实本轮消息回填它；它是审计字段，不是完整需求摘要。

# 多轮变更语义（必须按完整快照输出）

假设上一轮明确要求“江苏制造业，净利 1000 万以上”：

- 本轮说“只看上市公司”：在当前需求上新增上市条件；输出仍须包含江苏、制造业、净利门槛和上市状态，不能只输出上市状态。
- 本轮说“净利放宽到 500 万，其他不变”：只把净利下限替换为 5000000，其余历史明确条件全部保留。
- 本轮说“去掉地区限制”：只删除地区条件，制造业、净利等其他要求继续保留。
- 本轮说“重新找浙江医疗行业”或“重来，找浙江医疗行业”：允许整体重置，丢掉旧的江苏、制造业、净利等条件，只保留新需求明确表达的浙江与医疗行业。
- 本轮说“其他不变”：所有历史中仍明确有效、且本轮没有点名修改或删除的条件都必须保留。

不要用代码式补丁思维逐字套规则；要结合完整问答判断用户此刻的真实意图。但无论怎样判断，都不能新增用户从未表达过的条件。

# condition_groups

- 一组内的 conditions 同时成立（AND）；只有用户对不同类型标的提出不同要求时才分组，组间是 OR。
- conditions 只能使用上面的可筛字段。不能结构化的要求放 qualitative_requirements，不得硬塞字段。
- 金额统一换算为元：1000 万写 10000000，1 亿写 100000000。
- 比率按百分数写：负债率 60% 写 60，股比 51% 写 51；PE 15 倍写 15。
- strength 只有 required / preferred。“必须、一定、至少、不超过”是 required；“最好、优先、倾向”是 preferred；无修饰的明确数值门槛默认 required。

# 业务方向

- 业务方向（行业、赛道、产品，如“医疗器械”“薄膜电容器”“制造业”）**不是可筛字段**，不要塞进 conditions，也不要归到任何分类。用户原话原样放进 qualitative_requirements，由后续环节读标的的业务标签与业务摘要判断。
- 明确排除的业务方向放 exclusions.industries（自由词，原样保留），不能误写成正向条件。

# 定性诉求与残留

- qualitative_requirements 原样保留对标的的定性要求，例如“经营稳定”“有成熟海外仓”“净利率 15% 以上”（净利率不是可筛字段）。
- unstructured_notes 保存背景、流程诉求、无关问题等无法归为标的要求的表达。
- 若本轮与推荐完全无关且历史也不能形成有效请求，condition_groups 给空数组，原话放 unstructured_notes，不得临时编一套需求。

# 输出前检查

1. 输出是否代表用户现在的完整需求，而不是只列本轮增量？
2. 保留、替换、删除、整体重置是否符合最近问答与本轮措辞？
3. 每个结构化条件能否在历史用户表达或本轮原话中找到依据？找不到就删除。
4. 用户仍然有效的每一项要求是否进入 conditions、qualitative_requirements、exclusions、unstructured_notes 之一？
"""


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "condition_groups",
        "qualitative_requirements",
        "exclusions",
        "unstructured_notes",
        "raw_text",
    ],
    "properties": {
        "condition_groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["conditions"],
                "properties": {
                    "label": {"type": "string"},
                    "conditions": {"type": "object"},
                    "strength": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "enum": ["required", "preferred"],
                        },
                    },
                },
            },
        },
        "qualitative_requirements": {"type": "array", "items": {"type": "string"}},
        "exclusions": {
            "type": "object",
            "required": ["industries", "risk_flags"],
            "properties": {
                "industries": {"type": "array", "items": {"type": "string"}},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
            },
        },
        "unstructured_notes": {"type": "array", "items": {"type": "string"}},
        "raw_text": {"type": "string"},
    },
}

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
        "name": "推荐对话需求解析 v0.4.0（行业字典下线：业务方向不进条件）",
        "description": "删掉一级/二级行业闭集与「# 行业」规则；业务方向原样放定性诉求，由后续环节读标的业务标签与摘要判断。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_query_parser_v040_prompt.py", "based_on_version": "v0.3.1"},
    }


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")
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
        print("---- rendered system + user（前 1200 字）----")
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

    if args.dry_run:
        print(f"[dry-run] {NODE_NAME}: 将创建 {VERSION} 并设为默认；未 apply")
        print(f"  system={len(SYSTEM_PROMPT)} 字 user={len(USER_PROMPT_TEMPLATE)} 字")
        print(f"  output_schema={json.dumps(OUTPUT_SCHEMA, ensure_ascii=False)[:240]}…")
        return

    created = api._request_json(
        args.api_base,
        "POST",
        "/model-config/prompts",
        token=token,
        json_body=_payload(),
    )
    print(f"[created] {NODE_NAME} {VERSION} id={created.get('id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=API_BASE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="只做本地 NodeSpec/变量检查，不访问 API")
    group.add_argument("--render-preview", action="store_true", help="调用只读渲染预览，不 apply")
    group.add_argument("--dry-run", action="store_true", help="访问 API 查重，不创建")
    group.add_argument("--apply", action="store_true", help="创建新版本并设为默认")
    args = parser.parse_args()
    try:
        _run(args)
    except PromptVersionConflict as exc:
        print(f"[conflict] {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
