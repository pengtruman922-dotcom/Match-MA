"""Turn an agent brief into the answer the consultant copies to their client.

Two rules shape this module:

1. The numbers come from the brief's `facts`, which came from SQL. The writer
   node is asked to quote them, never to recall them.
2. Target names become links here, in code, by exact string match against the
   candidates of this turn. The model is never asked to emit an id or a URL —
   a hallucinated id produces a link to somebody else's target, and that is the
   kind of error nobody notices until it has already been sent to a client.
"""

from __future__ import annotations

import re
from typing import Any

# 一个候选在正文里最多被链接一次，避免同名反复出现时满屏蓝字。
MAX_LINKS_PER_TARGET = 1


def build_answer_prompt_variables(brief: dict[str, Any]) -> dict[str, Any]:
    """What the writer node sees. The brief is already merged with facts."""
    return {"answer_brief_json": brief}


def target_link_map(brief: dict[str, Any]) -> dict[str, str]:
    """name -> target id, for the candidates this turn actually recommended."""
    mapping: dict[str, str] = {}
    for item in brief.get("recommended") or []:
        name = str(item.get("name") or "").strip()
        target_id = str(item.get("id") or "").strip()
        if name and target_id:
            mapping.setdefault(name, target_id)
    return mapping


def backfill_target_links(answer_text: str, link_map: dict[str, str]) -> str:
    """Replace exact target-name occurrences with markdown links.

    Longest name first so "杭州XX精密制造" is not eaten by a shorter name that
    happens to be a prefix of it. Names already inside a markdown link are left
    alone, and each target is linked at most once.
    """
    if not answer_text or not link_map:
        return answer_text
    names = sorted(link_map, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(name) for name in names))
    used: dict[str, int] = {}

    def already_linked(text: str, start: int, end: int) -> bool:
        # 命中点落在 [..](..) 的中括号里，或紧跟 ]( 的话就是已经链接过了。
        return (
            (start > 0 and text[start - 1] == "[")
            or text[end:end + 2] == "]("
        )

    def replace(match: re.Match[str]) -> str:
        name = match.group(0)
        target_id = link_map.get(name)
        if target_id is None:
            return name
        if already_linked(answer_text, match.start(), match.end()):
            return name
        if used.get(name, 0) >= MAX_LINKS_PER_TARGET:
            return name
        used[name] = used.get(name, 0) + 1
        return f"[{name}](/targets/{target_id})"

    return pattern.sub(replace, answer_text)


def plain_text_for_copy(answer_text: str) -> str:
    """Strip markdown links back to bare names, for pasting into WeChat."""
    return re.sub(r"\[([^\]]+)\]\((?:/[^)]*)\)", r"\1", answer_text or "")


def fallback_answer_markdown(brief: dict[str, Any]) -> str:
    """A usable answer when the writer node is unconfigured or fails.

    Rule-composed from the same facts, so the consultant still gets something
    to send rather than an error page.
    """
    lines: list[str] = []
    understanding = str(brief.get("understanding") or "").strip()
    total = brief.get("total_eligible")
    if understanding and total is not None:
        lines.append(f"按「{understanding}」筛选，符合基础条件的有 {total} 家。挑出以下几家：")
    elif understanding:
        lines.append(f"按「{understanding}」筛选，挑出以下几家：")
    else:
        lines.append("按你给的条件，挑出以下几家：")
    lines.append("")

    for index, item in enumerate(brief.get("recommended") or [], start=1):
        facts = item.get("facts") or {}
        head_parts = [
            value for value in (
                facts.get("net_profit_text") and f"净利 {facts['net_profit_text']}",
                facts.get("region"),
                facts.get("can_control") and f"可控股 {facts['can_control']}",
                facts.get("pe_ratio") is not None and f"PE {facts['pe_ratio']}",
            ) if value
        ]
        lines.append(f"{index}. {item.get('name') or '未命名标的'}"
                     + (f" —— {'，'.join(head_parts)}" if head_parts else ""))
        for point in item.get("reason_points") or []:
            lines.append(f"   {point}")
        if item.get("watch_out"):
            lines.append(f"   要留意：{item['watch_out']}")
        if item.get("already_in_progress"):
            lines.append("   （这家已经在推进中）")
        elif item.get("other_buyer_in_deep_progress"):
            lines.append("   （这家正与其他买家深入推进）")
        lines.append("")

    runner_ups = brief.get("runner_ups") or []
    if runner_ups:
        names = "、".join(str(item.get("name")) for item in runner_ups if item.get("name"))
        if names:
            lines.append(f"另外 {names} 也在候选里，条件差一些，需要的话我再展开。")
    return "\n".join(lines).strip()
