"""发布 `recommendation_query_parser` v0.3.1（中止轮也是需求的一部分）。

v0.3.1 只改历史的读法：0819 起 `history_context` 会带 `<aborted_user_turn>`
—— 用户主动停掉、AI 没回答的那一轮，只有用户原话。

为什么要认它：按停止常常不是「这个需求不要了」，而是「还是这个需求，只是先别跑」。
把它整轮丢掉，下一句补充（「那就江苏吧」）就没有可依附的对象。

⚠️ 同时必须写明**冲突以后续为准**：按停止也可能是「我说错了」。少了这一句，
那种停止会把说错的需求一路带进后续所有轮 —— 这是零 UI 成本能覆盖掉的一半场景。

筛选字段、行业闭集、输出 schema 与 v0.3.0 完全一致。
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

import publish_query_parser_v030_prompt as base_prompt  # noqa: E402
from prompt_publish_utils import (  # noqa: E402
    PromptVersionConflict,
    ensure_prompt_version_compatible,
    validate_prompt_contract,
    validate_render_preview,
)

API_BASE = base_prompt.API_BASE
NODE_NAME = base_prompt.NODE_NAME
VERSION = "v0.3.1"
OUTPUT_SCHEMA: dict[str, Any] = base_prompt.OUTPUT_SCHEMA

SYSTEM_PROMPT = base_prompt.SYSTEM_PROMPT.replace(
    "你会收到最近 5 轮已经完成、未中止的用户问题与 AI 最终正文，以及本轮用户消息。",
    "你会收到最近 5 轮对话，以及本轮用户消息。其中大部分是「用户问题 + AI 最终正文」的完整轮；"
    "也可能出现 `<aborted_user_turn>`，那是用户主动中止、AI 未作答的一轮，只有用户原话。",
    1,
).replace(
    "1. 历史是当前需求判断的一部分。结合最近问答与本轮措辞，自主判断条件是保留、新增、替换、删除还是整体重置。",
    "1. 历史是当前需求判断的一部分。结合最近问答与本轮措辞，自主判断条件是保留、新增、替换、删除还是整体重置。\n"
    "1.1 `<aborted_user_turn>` 里的用户原话**同样属于当前需求**，"
    "请与后续补充合并理解，不要把它当成一个还需要单独回答的问题。\n"
    "1.2 **若后续消息与中止轮原话冲突，一律以后续为准。** "
    "用户中止一轮可能是嫌慢，也可能是说错了要改口；冲突时后者是更可能的解释，"
    "被推翻的条件不要保留。",
    1,
)

USER_PROMPT_TEMPLATE = base_prompt.USER_PROMPT_TEMPLATE.replace(
    "# 最近 5 轮已完成问答",
    "# 最近 5 轮对话（含用户中止、AI 未作答的轮次）",
    1,
)

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
        "name": "推荐对话需求解析 v0.3.1（中止轮并入当前需求）",
        "description": "沿用 v0.3.0 的快照契约；中止轮的用户原话并入当前需求，冲突以后续为准。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_query_parser_v031_prompt.py"},
    }


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")
    assert "aborted_user_turn" in SYSTEM_PROMPT, "新版必须描述中止轮标签"
    assert "以后续为准" in SYSTEM_PROMPT, "新版必须写明冲突时以后续消息为准"
    print("[OK] 中止轮语义与冲突优先级都在正文里")
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
    except PromptVersionConflict as exc:
        print(f"[conflict] {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
