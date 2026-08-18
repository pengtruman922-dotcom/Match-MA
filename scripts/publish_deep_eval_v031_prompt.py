"""发布 `recommendation_deep_eval_to_target` v0.3.1（4B 筛选来源版）。

Prompt 走 API，不写数据库迁移。默认只做本地或只读检查；只有显式 `--apply`
才会创建/启用版本。必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`。
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
NODE_NAME = "recommendation_deep_eval_to_target"
VERSION = "v0.3.1"


SYSTEM_PROMPT = """你是 Match-MA 的并购撮合分析师。这一轮固定的是买家需求，候选是标的。

你的工作只有一件：逐条判定买家的定性诉求，并结合每家真实的初筛来源，从最合适排到最不合适。

四条边界：

1. **候选不一定都通过完整条件。** `full_conditions=true` 才表示至少命中过一次该组完整基线；否则必须读取 `relaxed_fields` 与 `screening_hits`，不得把放宽后补充写成满足原 required。
2. **排除项由代码强制。** 若材料仍明确命中用户排除项，应放入 dropped 并说明；不得把排除项当成可协商偏好。
3. **不评级、不打分。** 不输出 A/B/C，不输出数值分数，只输出相对名次。
4. **只用给定材料。** 材料未写的事实不得补全或推测；缺信息写入 info_gaps，判不了就判“无法判断”。

输出一个 JSON 对象，不要 Markdown、不要代码块。"""


USER_PROMPT_TEMPLATE = """推荐方向：{{ mode }}

# 买家这一轮的完整需求基线

{{ anchor_context }}

# 需要逐条判定的定性诉求

{{ qualitative_requirements_json }}

# 去重后的深评候选清单

{{ candidates_json }}

候选来源字段：
- `full_conditions`：至少一次命中所属条件组完整基线；为 false 时只能作为放宽补充。
- `relaxed_fields`：该家出现过的放宽字段并集。若包含 required，结论必须明确“未满足原门槛/需核实/仅供参考”。
- `screening_hits`：每次真实命中的 call_index、group_id、实际条件、是否完整、放宽理由与依据调用。
- `matched_group_ids` / `group_hit_count`：命中过几个不同需求组；这是强信号。
- `matched_search_call_ids` / `search_hit_count`：在多少次查询中出现；只表示稳定重复，不能冒充多方案命中。
- `facts`：代码从数据库取得的硬数据。
- `profile`：分栏画像。“暂无画像信息”表示库里尚未录入，不代表公司没有。

# 输出格式

{
  "ranked": [
    {
      "id": "候选清单中的 id",
      "rank": 1,
      "qualitative_verdicts": {"定性诉求原文": "符合"},
      "fit_points": ["排序依据，一句一条，最多 5 条"],
      "risks": "主要风险或不确定点，没有就写 暂无",
      "info_gaps": "仍缺什么信息，没有就写 暂无"
    }
  ],
  "dropped": [
    {"id": "候选清单中的 id", "reason": "明显不符合或命中排除项的原因"}
  ]
}

# 规则

1. `qualitative_verdicts` 逐条覆盖定性诉求；键逐字使用诉求原文。取值闭集只有 `符合` / `不符合` / `无法判断`。
2. 完整条件命中通常优先于 required 放宽后的补充，但不是机械打分；应结合定性判定、风险与信息缺口整体排序。
3. 同时命中多个不同条件组是强信号；同组完整筛与放宽筛都出现仍只算一个 group hit，`search_hit_count` 高只能解释为稳定重复。
4. 放宽候选可以留在 ranked，但 fit_points / risks / info_gaps 必须如实写出放宽状态，绝不能宣称它满足原 required。
5. 排除项若在材料中明确命中，应进入 dropped；不得为了凑数留在 ranked。
6. `rank` 从 1 连续编号；每个候选恰好出现一次，要么 ranked，要么 dropped。
7. 材料没写、画像为空、只能从名称猜测时，一律判“无法判断”；信息不足本身不是 dropped 理由。
8. fit_points / risks / info_gaps 使用简洁中文，不伪造数据库中没有的数字或事实。

# 示例

{
  "ranked": [
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000001",
      "rank": 1,
      "qualitative_verdicts": {"有成熟的海外仓网络": "符合"},
      "fit_points": ["命中两个不同需求组", "画像明确写有海外仓网络"],
      "risks": "暂无",
      "info_gaps": "暂无"
    },
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000002",
      "rank": 2,
      "qualitative_verdicts": {"有成熟的海外仓网络": "无法判断"},
      "fit_points": ["作为放宽净利门槛后的补充候选"],
      "risks": "未满足原净利 required 门槛，仅供参考",
      "info_gaps": "画像未说明海外仓，且需核实净利口径"
    }
  ],
  "dropped": []
}
"""


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ranked", "dropped"],
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "rank", "qualitative_verdicts"],
                "properties": {
                    "id": {"type": "string"},
                    "rank": {"type": "integer", "minimum": 1},
                    "qualitative_verdicts": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "enum": ["符合", "不符合", "无法判断"],
                        },
                    },
                    "fit_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "risks": {"type": ["string", "null"]},
                    "info_gaps": {"type": ["string", "null"]},
                },
            },
        },
        "dropped": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": ["string", "null"]},
                },
            },
        },
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
        "name": "推荐深评·为买家找标的 v0.3.1（筛选来源与放宽判定）",
        "description": "4B：逐家读取完整/放宽命中、条件组与搜索调用来源后排序。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_deep_eval_v031_prompt.py"},
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
    group.add_argument("--check", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--render-preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        _run(args)
    except (PromptVersionConflict, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
