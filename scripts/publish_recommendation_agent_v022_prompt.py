"""发布 `recommendation_agent_to_target` v0.2.2（中止轮不是一个待回答的问题）。

0819 起 `history_context` 里可能出现 `<aborted_user_turn>`：用户主动停掉、
AI 没作答的一轮，只有用户原话。解析器已经把它并进当前需求快照（v0.3.1）。

主 Agent 这边要防的是另一个方向的误解：看到一句「没人回答过」的用户话，
顺手把它当成本轮要额外回答的问题，于是绕开快照自己发明条件。
所以这一版只加一条硬规则 —— 条件仍然只能来自快照。

工具集、预算、输出 schema 与 v0.2.1 完全一致。
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

import publish_recommendation_agent_v021_prompt as base_prompt  # noqa: E402
from prompt_publish_utils import (  # noqa: E402
    PromptVersionConflict,
    ensure_prompt_version_compatible,
    validate_prompt_contract,
    validate_render_preview,
)

API_BASE = base_prompt.API_BASE
NODE_NAME = base_prompt.NODE_NAME
VERSION = "v0.2.2"
SYSTEM_PROMPT = base_prompt.SYSTEM_PROMPT
OUTPUT_SCHEMA: dict[str, Any] = base_prompt.OUTPUT_SCHEMA

_ABORTED_TURN_RULE = """0. **历史里的 `<aborted_user_turn>` 不是一个待回答的问题。** 那是用户主动中止、AI 未作答的一轮，只有用户原话。解析器已经把它并进当前需求快照，你要做的就是照常执行快照 —— 不要为它单独补一段回答，也不要因为"它看起来没被回答"就绕开快照自己发明条件。快照与它冲突时以快照为准。

"""

USER_PROMPT_TEMPLATE = base_prompt.USER_PROMPT_TEMPLATE.replace(
    "# 最近 5 轮已完成对话",
    "# 最近 5 轮对话（含用户中止、AI 未作答的轮次）",
    1,
).replace(
    "# 硬规则\n\n1. **只读当前快照。**",
    "# 硬规则\n\n" + _ABORTED_TURN_RULE + "1. **只读当前快照。**",
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
        "name": "推荐编排 Agent·为买家找标的 v0.2.2（中止轮不单独作答）",
        "description": "沿用 v0.2.1 编排契约；历史里的中止轮只作为需求背景，条件仍只能来自快照。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_recommendation_agent_v022_prompt.py"},
    }


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")
    assert "aborted_user_turn" in USER_PROMPT_TEMPLATE, "新版必须描述中止轮标签"
    assert "只读当前快照" in USER_PROMPT_TEMPLATE, "不能把 v0.2.1 的快照硬规则挤掉"
    print("[OK] 中止轮规则已插入，且原有硬规则仍在")
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
