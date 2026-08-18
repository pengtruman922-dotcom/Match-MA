"""Shared safety checks for version-controlled Prompt publishing scripts."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.app.ai.prompting import extract_template_variables
from backend.app.registry.nodes import node_by_name


class PromptVersionConflict(RuntimeError):
    """The requested immutable version already exists with different content."""


def expected_prompt_variables(node_name: str) -> tuple[str, ...]:
    spec = node_by_name(node_name)
    if spec is None:
        raise RuntimeError(f"节点未在 NodeSpec 注册：{node_name}")
    return tuple(spec.prompt_variables)


def validate_prompt_contract(
    *,
    node_name: str,
    system_prompt: str,
    user_prompt_template: str,
) -> tuple[str, ...]:
    """Require the draft's double-brace variables to equal NodeSpec exactly."""
    expected = expected_prompt_variables(node_name)
    actual = tuple(extract_template_variables(system_prompt, user_prompt_template))
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise RuntimeError(
            f"Prompt 变量与 NodeSpec 不一致；缺少={missing or '无'}，多出={extra or '无'}"
        )

    body = f"{system_prompt}\n{user_prompt_template}"
    single_brace = re.compile(r"(?<!\{)\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}(?!\})")
    wrong = sorted(set(expected).intersection(single_brace.findall(body)))
    if wrong:
        raise RuntimeError(f"变量必须使用双花括号，发现单花括号：{', '.join(wrong)}")
    return expected


def ensure_prompt_version_compatible(
    rows: list[dict[str, Any]],
    *,
    version: str,
    system_prompt: str,
    user_prompt_template: str,
    output_schema: dict[str, Any],
    variables: tuple[str, ...],
) -> dict[str, Any] | None:
    """Return an identical existing row; reject same-version drift loudly."""
    matches = [row for row in rows if str(row.get("version") or "") == version]
    if not matches:
        return None
    if len(matches) > 1:
        raise PromptVersionConflict(f"版本冲突：{version} 在服务端存在 {len(matches)} 条记录")

    existing = matches[0]
    differences: list[str] = []
    if str(existing.get("system_prompt") or "") != system_prompt:
        differences.append("系统正文")
    if str(existing.get("user_prompt_template") or "") != user_prompt_template:
        differences.append("用户正文")
    if _canonical_json(existing.get("output_schema_json") or {}) != _canonical_json(output_schema):
        differences.append("schema")
    if list(existing.get("variables_json") or []) != list(variables):
        differences.append("变量集合")
    if differences:
        raise PromptVersionConflict(
            f"版本冲突：服务端已有 {version}，但{('、'.join(differences))}不同；"
            "不会覆盖、不会无声跳过，请改用新版本号或先人工核查。"
        )
    return existing


def validate_render_preview(
    preview: dict[str, Any],
    *,
    expected_variables: tuple[str, ...],
) -> tuple[str, str]:
    """Verify the server recognised and replaced every draft variable."""
    recognised = tuple(preview.get("variables") or [])
    if set(recognised) != set(expected_variables):
        raise RuntimeError(
            f"render-preview 变量不一致；期望={list(expected_variables)}，实际={list(recognised)}"
        )
    rendered_system = str(preview.get("rendered_system_prompt") or "")
    rendered_user = str(preview.get("rendered_user_prompt") or "")
    rendered = f"{rendered_system}\n{rendered_user}"
    unresolved = extract_template_variables(rendered)
    if unresolved:
        raise RuntimeError(f"render-preview 后仍有双花括号变量：{unresolved}")
    resolved = preview.get("resolved_variables") or {}
    missing_values = [
        name for name in expected_variables
        if str(resolved.get(name) or "") not in rendered
    ]
    if missing_values:
        raise RuntimeError(f"render-preview 未注入这些变量的实际/示例值：{missing_values}")
    return rendered_system, rendered_user


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
