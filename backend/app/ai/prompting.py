from __future__ import annotations

import json
import re
from typing import Any


_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

# 行业字典 2026-09-08 整体下线（方案 0908）后不再有值的两个模板变量。
# prompt_template 是库里的版本化数据，线上可能还跑着引用它们的旧版本；
# render_template 对未绑定变量渲染成字面量 "null"，模型会收到「闭集：null」。
# 过渡期各 handler 把它们传成空串，旧版本渲染出来是空清单。阶段 B 删这个常量。
RETIRED_TEMPLATE_VARIABLES: dict[str, str] = {
    "industry_l1_list": "",
    "industry_l2_list": "",
}


def extract_template_variables(*templates: str | None) -> list[str]:
    """Return the unique `{{ var }}` names across templates in first-seen order."""
    seen: list[str] = []
    for template in templates:
        if not template:
            continue
        for match in _VARIABLE_PATTERN.finditer(template):
            name = match.group(1)
            if name not in seen:
                seen.append(name)
    return seen


def render_template(template: str | None, variables: dict[str, Any]) -> str:
    if not template:
        return ""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name)
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    return _VARIABLE_PATTERN.sub(replace, template)
