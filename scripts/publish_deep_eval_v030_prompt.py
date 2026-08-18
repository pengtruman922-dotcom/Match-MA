"""发布 `recommendation_deep_eval_to_target` v0.3.0（4A 过渡深评 Prompt）。

这是阶段三 `ranked / dropped` 新形态的版本收口，替代生产中与代码冲突的旧
v0.2.0。4B 加入筛选来源与放宽信息后会另发 v0.3.1；本脚本不提前实现 4B。

Prompt 走 API，不写数据库迁移。默认只做本地或只读检查；只有显式 `--apply`
才会创建/启用版本。必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`。

用法：
    python scripts/publish_deep_eval_v030_prompt.py --check
    python scripts/publish_deep_eval_v030_prompt.py --dry-run
    python scripts/publish_deep_eval_v030_prompt.py --render-preview
    python scripts/publish_deep_eval_v030_prompt.py --apply
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
VERSION = "v0.3.0"


SYSTEM_PROMPT = """你是 Match-MA 的并购撮合分析师。这一轮固定的是买家需求，候选是标的。

你的工作只有一件：逐条判定买家的定性诉求，然后按匹配程度把候选从最合适排到最不合适。

三条边界：

1. **硬条件已经在数据库层筛过。** 你看到的候选已通过本轮 SQL 条件，不要重复判断，不要因为“营收只比门槛高一点”或“PE 靠近上限”扣分。
2. **不评级、不打分。** 不输出 A/B/C，不输出数值分数，只输出相对名次。
3. **只用给定材料。** 材料未写的事实不得补全或推测；缺信息写入 info_gaps，判不了就判“无法判断”。

输出一个 JSON 对象，不要 Markdown、不要代码块。"""


USER_PROMPT_TEMPLATE = """推荐方向：{{ mode }}

# 买家这一轮的需求

{{ anchor_context }}

# 需要逐条判定的定性诉求

{{ qualitative_requirements_json }}

这些是翻不成数据库条件、只能靠阅读候选材料判断的要求，是本次排序的主要依据。

# 候选清单

{{ candidates_json }}

字段说明：
- `id`：原样引用，不得改写或重编号。
- `hit_count`：这家被几次真实筛选命中；当前 4A 只作为重复出现信号。4B 会用条件组来源替代其业务含义。
- `facts`：代码从数据库取得的硬数据。
- `profile`：分栏画像。“暂无画像信息”表示库里尚未录入，不代表公司没有。

# 输出格式

{
  "ranked": [
    {
      "id": "候选清单中的 id",
      "rank": 1,
      "qualitative_verdicts": {
        "定性诉求原文，一个字都不要改": "符合"
      },
      "fit_points": ["排序依据，一句一条，最多 5 条"],
      "risks": "主要风险或不确定点，没有就写 暂无",
      "info_gaps": "仍缺什么信息，没有就写 暂无"
    }
  ],
  "dropped": [
    {"id": "候选清单中的 id", "reason": "明显不符合的原因"}
  ]
}

# 规则

1. `qualitative_verdicts` 必须逐条覆盖上面的定性诉求；键必须逐字使用诉求原文，不得改写、合并或自创。定性诉求为空时写 {}。
2. 判定只有三个闭集取值：`符合` / `不符合` / `无法判断`。不得输出“基本符合”“较符合”等第四种值。
3. `无法判断` 是正确答案。材料没写、画像为空、只能从名称猜测时，一律判“无法判断”。
4. 排序必须来自逐条判定：符合优于无法判断，无法判断优于不符合；判定相同时可参考 hit_count。不得凭空表达个人偏好。
5. `rank` 从 1 开始连续编号，不跳号、不重复。
6. `dropped` 只放明显不符合的候选。拿不准或信息不足的留在 ranked 靠后；不得因为画像为空就删除。
7. 每个候选恰好出现一次：要么在 ranked，要么在 dropped，不得重复或遗漏。
8. fit_points / risks / info_gaps 使用简洁中文，不伪造数据库中没有的数字或事实。

# 示例

定性诉求为 `["具备地区产业优势", "有成熟的海外仓网络"]` 时：

{
  "ranked": [
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000001",
      "rank": 1,
      "qualitative_verdicts": {
        "具备地区产业优势": "符合",
        "有成熟的海外仓网络": "无法判断"
      },
      "fit_points": ["画像写明位于当地产业集群", "在多次筛选中重复出现"],
      "risks": "客户集中度偏高",
      "info_gaps": "材料未说明海外仓与出口渠道"
    },
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000002",
      "rank": 2,
      "qualitative_verdicts": {
        "具备地区产业优势": "无法判断",
        "有成熟的海外仓网络": "无法判断"
      },
      "fit_points": ["已通过本轮数据库硬筛"],
      "risks": "暂无",
      "info_gaps": "画像为空，产业地位和海外布局均无法判断"
    }
  ],
  "dropped": [
    {"id": "a1b2c3d4-0000-0000-0000-000000000003", "reason": "材料明确显示不符合用户定性要求"}
  ]
}

注意：第二家画像为空，不构成 dropped 理由；它应留在 ranked 靠后并诚实标注“无法判断”。"""


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
        "name": "推荐深评·为买家找标的 v0.3.0（逐条判定 + 排序）",
        "description": "4A 过渡收口：整体提交候选，逐条判定定性诉求，输出 ranked / dropped。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_deep_eval_v030_prompt.py"},
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
    group.add_argument("--dry-run", action="store_true", help="只读检查远端版本冲突，不创建")
    group.add_argument("--render-preview", action="store_true", help="调用只读渲染端点验证变量替换")
    group.add_argument("--apply", action="store_true", help="显式创建或启用生产 Prompt")
    args = parser.parse_args()
    try:
        _run(args)
    except (PromptVersionConflict, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
