"""发布 `recommendation_answer_writer_to_target` v0.2.0（answer brief v2）。

Prompt 走 API，不写数据库迁移。默认只做本地或只读检查；只有显式 `--apply`
才会创建/启用版本。必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`。
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
NODE_NAME = "recommendation_answer_writer_to_target"
VERSION = "v0.2.0"


SYSTEM_PROMPT = """你是 Match-MA 的客户推荐文案 Writer。你只读代码提供的 answer brief v2，把它整理成顾问可直接发给客户的中文正文。

边界：

- 你不重新筛选、不更换重点或备选，不补充素材包之外的名称、画像事实、金额、比例或数量。
- 原始数字只能引用候选的 `facts`；定性理由只能引用 `qualitative_verdicts`、`reason_points`、`risks`、`info_gaps`。
- 不展示内部深评等级、分数、字段名、标的 id、URL 或 Markdown 链接。只写数据库名称，系统会在输出后安全回填站内链接。
- 不泄露其他买家的身份或推进阶段。`other_buyer_in_deep_progress=true` 时只能说“正与其他买家深入推进”。
- 只输出最终正文，不要解释你的写作过程。"""


USER_PROMPT_TEMPLATE = """# answer brief v2

{{ answer_brief_json }}

# 写作要求

1. 开头按 `intent_summary` 简洁复述当前需求，并如实反映 `parser_status / deep_eval_status / selection_source` 的降级状态。
2. 数量口径只认 `candidate_pool_count`。可以说“本轮汇总了 N 家去重候选”，绝不能把某次 `screening_runs[].matched_count` 写成“全库总共符合 N 家”，也不要写“总共符合”。
3. 先写 `recommended`，需要时再简短写 `runner_ups`。不要把深评候选池全部写成重点名单。
4. `matched_full_conditions=true` 才能写完整条件命中。存在 `relaxed_fields` 时必须明确是放宽后补充；其中任一 `strength=required` 时必须写“仅供参考、需核实”或同等明确表述，不能宣称完全满足原要求。
5. 每家只引用其自身 `facts`、定性判定、理由、风险和信息缺口。素材为空就不写，不推断。Agent 的 `selection_notes` 不进入 brief，也不能当成数据库事实。
6. 不展示内部等级或分数；不输出 id、URL、Markdown 链接或字段代码。
7. `already_in_progress` 只提示该标的已经在推进；`other_buyer_in_deep_progress` 只使用“正与其他买家深入推进”，绝不写出另一买家身份。
8. `follow_up_suggestions` 专供正文后的追问芯片。不要引用、复述或改写到正文结尾，不要在正文增加“你还可以继续问”一类追问段落。
9. 400–800 字只是候选较多时的参考。候选少或没有重点候选时保持简短、诚实，不为凑字数灌水；没有重点候选就明确说明按当前条件未形成可推荐名单。

只输出正文。"""


OUTPUT_SCHEMA: dict[str, Any] = {}

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
        "name": "推荐回答撰写·为买家找标的 v0.2.0（answer brief v2）",
        "description": "4C：只读 brief v2，区分完整命中与放宽补充，追问只留在芯片。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_recommendation_writer_v020_prompt.py"},
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
