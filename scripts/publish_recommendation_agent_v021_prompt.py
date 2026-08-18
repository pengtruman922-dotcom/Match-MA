"""发布 `recommendation_agent_to_target` v0.2.1（追问芯片改为用户口吻）。

v0.2.1 只收紧追问芯片语态；4B 的受控筛选、深评回灌与输出 schema 均不变。
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

import publish_recommendation_agent_v020_prompt as base_prompt  # noqa: E402
from prompt_publish_utils import (  # noqa: E402
    PromptVersionConflict,
    ensure_prompt_version_compatible,
    validate_prompt_contract,
    validate_render_preview,
)

API_BASE = base_prompt.API_BASE
NODE_NAME = base_prompt.NODE_NAME
VERSION = "v0.2.1"
SYSTEM_PROMPT = base_prompt.SYSTEM_PROMPT
OUTPUT_SCHEMA: dict[str, Any] = base_prompt.OUTPUT_SCHEMA

_CHIP_RULES = """# 追问芯片语态（硬规则）

`follow_up_suggestions` 里的每一条都是**用户下一句要说的话本身**：使用第一人称、祈使或陈述语气，原样发送就是一条合理的用户消息。它不是给用户的建议、不是待确认事项，也不是让用户再改写的问句选项。

反例 → 正例：

- ✗ 明确是否要求控股 → ✓ 只看能控股的
- ✗ 考虑是否放宽净利要求 → ✓ 净利放宽到 500 万
- ✗ 建议补充地区限制 → ✓ 只要江苏的
- ✗ 可以进一步了解 XX 公司 → ✓ 详细说说 XX
- ✗ 确认是否接受对赌 → ✓ 排除掉要对赌的

"""

USER_PROMPT_TEMPLATE = base_prompt.USER_PROMPT_TEMPLATE.replace(
    "# 最终 JSON（只有看过深评结果后才输出）",
    _CHIP_RULES + "# 最终 JSON（只有看过深评结果后才输出）",
).replace(
    '"follow_up_suggestions": ["下一轮可直接发送的短句"]',
    '"follow_up_suggestions": ["用户下一句要说的话本身；第一人称、祈使或陈述"]',
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
        "name": "推荐编排 Agent·为买家找标的 v0.2.1（用户口吻追问芯片）",
        "description": "4D：沿用 v0.2.0 编排契约，追问芯片必须可作为用户下一句话原样发送。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_recommendation_agent_v021_prompt.py"},
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
