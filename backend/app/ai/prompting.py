from __future__ import annotations

import json
import re
from typing import Any


_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


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
