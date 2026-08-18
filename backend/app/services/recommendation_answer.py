"""Build and render the final recommendation answer contract.

The main Agent owns selection, but never owns facts. This module is the single
join boundary for Agent choices, deep-eval judgements, SQL screening sources,
and database-held names/numbers. The Writer and the rule fallback both consume
the same v2 brief produced here.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from backend.app.registry.indicators import indicator_by_column
from backend.app.services.recommendation_agent_policy import CandidatePool
from backend.app.services.screening_schema import SCREENING_FIELDS_BY_COLUMN


MAX_LINKS_PER_TARGET = 1
MAX_RECOMMENDED = 6
MIN_RECOMMENDED = 3
MAX_RUNNER_UPS = 5
MAX_FOLLOW_UPS = 4
MAX_FOLLOW_UP_LENGTH = 80
MAX_SELECTION_NOTE_LENGTH = 300

_URL_OR_LINK = re.compile(r"https?://|www\.|\[[^\]]+\]\([^)]+\)|/targets/", re.IGNORECASE)
_PROMISES_FULL_LIST = re.compile(r"(?:列出|展示|看看?|给我).{0,8}(?:全部|所有|完整).{0,8}(?:候选|名单|\d+\s*家)")
_ADVISER_STYLE_FOLLOW_UP = re.compile(
    r"^(?:建议|可补充|可以考虑|考虑是否|明确是否|确认一下|需要进一步|可以进一步)"
)


def build_answer_prompt_variables(brief: dict[str, Any]) -> dict[str, Any]:
    """The Writer sees only the code-normalised v2 brief."""
    return {"answer_brief_json": brief}


def build_answer_brief_v2(
    raw_output: dict[str, Any] | None,
    *,
    mode: str,
    intent_snapshot: dict[str, Any],
    candidates_by_id: dict[str, dict[str, Any]],
    candidate_pool: CandidatePool,
    deep_eval: dict[str, Any] | None,
    screening_runs: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return ``(brief, normalised Agent output, trace notes)``.

    A healthy deep evaluation narrows the executable id set to ``ranked``.
    Degraded deep evaluation explicitly falls back to the fair SQL pool. Names,
    facts, progress flags, screening sources and deep-eval fields are always
    joined from code-held data; similarly named model fields are ignored.
    """
    deep = deep_eval if isinstance(deep_eval, dict) else {}
    deep_status = str(deep.get("deep_eval_status") or "not_run")
    ranked_items = [item for item in deep.get("ranked") or [] if isinstance(item, dict)]
    ranked_by_id = {
        str(item.get("id") or "").strip(): item
        for item in ranked_items
        if str(item.get("id") or "").strip()
    }
    dropped_ids = {
        str(item.get("id") or "").strip()
        for item in deep.get("dropped") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    pool_ids = [candidate_id for candidate_id in candidate_pool.candidate_ids if candidate_id in candidates_by_id]
    if deep_status == "ok":
        allowed_order = [candidate_id for candidate_id in ranked_by_id if candidate_id in candidates_by_id]
    else:
        allowed_order = pool_ids

    normalised, notes, had_valid_agent_choice = normalize_agent_final_output(
        raw_output,
        allowed_ids=allowed_order,
        pool_ids=pool_ids,
        dropped_ids=dropped_ids,
    )
    if deep_status == "ok":
        selection_source = "deep_eval"
    elif had_valid_agent_choice:
        selection_source = "agent_fallback"
    else:
        selection_source = "screening_fallback"

    groups = _group_strengths(intent_snapshot)

    def material(candidate_id: str) -> dict[str, Any]:
        candidate = candidates_by_id[candidate_id]
        ranked = ranked_by_id.get(candidate_id) or {}
        source = candidate_pool.source_for(candidate_id)
        screening_hits = [
            _enrich_screening_hit(hit, groups)
            for hit in source.get("screening_hits") or []
            if isinstance(hit, dict)
        ]
        relaxed_fields = _collect_relaxed_fields(screening_hits)
        return {
            "id": candidate_id,
            "name": candidate.get("seller_target_name"),
            "facts": deepcopy(candidate.get("facts") or {}),
            "qualitative_verdicts": deepcopy(ranked.get("qualitative_verdicts") or {}),
            "reason_points": [str(value) for value in ranked.get("fit_points") or [] if str(value or "").strip()],
            "risks": _text(ranked.get("risks")),
            "info_gaps": _text(ranked.get("info_gaps")),
            "matched_group_ids": list(source.get("matched_group_ids") or []),
            "matched_search_call_ids": list(source.get("matched_search_call_ids") or []),
            "group_hit_count": int(source.get("group_hit_count") or 0),
            "search_hit_count": int(source.get("search_hit_count") or 0),
            "screening_hits": screening_hits,
            "matched_full_conditions": any(bool(hit.get("full_conditions")) for hit in screening_hits),
            "relaxed_fields": relaxed_fields,
            "required_relaxation": any(item.get("strength") == "required" for item in relaxed_fields),
            "already_in_progress": candidate.get("relation_status"),
            "other_buyer_in_deep_progress": bool(candidate.get("seller_target_has_other_deep_progress")),
        }

    brief = {
        "brief_version": 2,
        "mode": mode,
        "intent_summary": render_intent_summary(intent_snapshot),
        "parser_status": str(intent_snapshot.get("parser_status") or "fallback"),
        "selection_source": selection_source,
        "deep_eval_status": deep_status,
        "candidate_pool_count": candidate_pool.unique_after_cap,
        "candidate_pool_capped": candidate_pool.capped,
        "screening_runs": [_screening_run_for_brief(run, groups) for run in screening_runs],
        "recommended": [material(candidate_id) for candidate_id in normalised["recommended_ids"]],
        "runner_ups": [material(candidate_id) for candidate_id in normalised["runner_up_ids"]],
        "follow_up_suggestions": list(normalised["follow_up_suggestions"]),
    }
    return brief, normalised, notes


def normalize_agent_final_output(
    raw_output: dict[str, Any] | None,
    *,
    allowed_ids: list[str],
    pool_ids: list[str],
    dropped_ids: set[str],
) -> tuple[dict[str, Any], list[str], bool]:
    """Normalise the final Agent JSON to the 4C contract.

    The deployed 4B Prompt emits ``recommended``/``runner_ups`` objects. The 4C
    contract uses id arrays plus ``selection_notes``. Supporting both shapes
    keeps in-flight turns safe while the stored brief and trace use one shape.
    """
    data = raw_output if isinstance(raw_output, dict) else {}
    notes: list[str] = []
    pool_set = set(pool_ids)
    allowed_set = set(allowed_ids)

    raw_recommended = data.get("recommended_ids")
    legacy_recommended = data.get("recommended")
    if not isinstance(raw_recommended, list):
        raw_recommended = legacy_recommended if isinstance(legacy_recommended, list) else []
    raw_runners = data.get("runner_up_ids")
    legacy_runners = data.get("runner_ups")
    if not isinstance(raw_runners, list):
        raw_runners = legacy_runners if isinstance(legacy_runners, list) else []

    recommended_valid = _validate_id_list(
        raw_recommended,
        label="recommended_ids",
        allowed_set=allowed_set,
        pool_set=pool_set,
        dropped_ids=dropped_ids,
        notes=notes,
    )
    runner_valid = _validate_id_list(
        raw_runners,
        label="runner_up_ids",
        allowed_set=allowed_set,
        pool_set=pool_set,
        dropped_ids=dropped_ids,
        notes=notes,
    )
    had_valid_agent_choice = bool(recommended_valid or runner_valid)

    overflow = recommended_valid[MAX_RECOMMENDED:]
    if overflow:
        notes.append(f"recommended_ids 超过 {MAX_RECOMMENDED} 家，已截断并把溢出项按备选处理")
    recommended = recommended_valid[:MAX_RECOMMENDED]

    desired_minimum = min(MIN_RECOMMENDED, len(allowed_ids))
    if len(recommended) < desired_minimum:
        for candidate_id in runner_valid:
            if candidate_id not in recommended:
                recommended.append(candidate_id)
                notes.append(f"重点名单不足 {desired_minimum} 家，已从 Agent 备选中补入 {candidate_id}")
            if len(recommended) >= desired_minimum:
                break
    if len(recommended) < desired_minimum:
        for candidate_id in allowed_ids:
            if candidate_id not in recommended:
                recommended.append(candidate_id)
            if len(recommended) >= desired_minimum:
                break
        notes.append(f"Agent 有效重点选择不足 {desired_minimum} 家，已按可执行排序补足最低数量")

    runner_candidates = [*overflow, *runner_valid]
    runner_up_ids: list[str] = []
    for candidate_id in runner_candidates:
        if candidate_id in recommended:
            notes.append(f"runner_up_ids 与重点名单重复，已丢弃：{candidate_id}")
            continue
        if candidate_id not in runner_up_ids:
            runner_up_ids.append(candidate_id)
    if len(runner_up_ids) > MAX_RUNNER_UPS:
        notes.append(f"runner_up_ids 超过 {MAX_RUNNER_UPS} 家，已截断")
        runner_up_ids = runner_up_ids[:MAX_RUNNER_UPS]

    raw_selection_notes = data.get("selection_notes")
    selection_notes: dict[str, str] = {}
    if isinstance(raw_selection_notes, dict):
        for raw_id, raw_note in raw_selection_notes.items():
            candidate_id = str(raw_id or "").strip()
            if candidate_id not in pool_set:
                notes.append(f"selection_notes 含池外 id，已丢弃：{candidate_id or '(空)'}")
                continue
            note = _bounded_text(raw_note, MAX_SELECTION_NOTE_LENGTH, candidate_id, notes)
            if note:
                selection_notes[candidate_id] = note

    # Backward-compatible extraction from the deployed 4B Prompt. Names and
    # facts are ignored; only qualitative selection commentary is retained.
    legacy_items = [
        *(legacy_recommended if isinstance(legacy_recommended, list) else []),
        *(legacy_runners if isinstance(legacy_runners, list) else []),
    ]
    for raw in legacy_items:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("id") or "").strip()
        if candidate_id in selection_notes or candidate_id not in allowed_set:
            continue
        parts = [str(value).strip() for value in raw.get("reason_points") or [] if str(value or "").strip()]
        watch_out = _text(raw.get("watch_out")) or _text(raw.get("note"))
        if watch_out:
            parts.append(watch_out)
        note = _bounded_text("；".join(parts), MAX_SELECTION_NOTE_LENGTH, candidate_id, notes)
        if note:
            selection_notes[candidate_id] = note

    selected = set(recommended) | set(runner_up_ids)
    selection_notes = {candidate_id: note for candidate_id, note in selection_notes.items() if candidate_id in selected}
    follow_ups = _normalise_follow_ups(data.get("follow_up_suggestions"), pool_ids=pool_ids, notes=notes)
    return (
        {
            "understanding": _text(data.get("understanding")),
            "recommended_ids": recommended,
            "runner_up_ids": runner_up_ids,
            "selection_notes": selection_notes,
            "follow_up_suggestions": follow_ups,
        },
        notes,
        had_valid_agent_choice,
    )


def render_intent_summary(snapshot: dict[str, Any]) -> str:
    """Render the current parser snapshot without trusting Agent prose."""
    parts: list[str] = []
    groups = snapshot.get("condition_groups") if isinstance(snapshot.get("condition_groups"), list) else []
    for index, raw_group in enumerate(groups, start=1):
        if not isinstance(raw_group, dict):
            continue
        label = str(raw_group.get("label") or "").strip() or f"方案{index}"
        conditions = raw_group.get("conditions") if isinstance(raw_group.get("conditions"), dict) else {}
        strength = raw_group.get("strength") if isinstance(raw_group.get("strength"), dict) else {}
        rendered: list[str] = []
        for column, value in conditions.items():
            field = SCREENING_FIELDS_BY_COLUMN.get(str(column))
            field_label = field.label if field else str(column)
            effect = "优先" if str(strength.get(column) or "required") == "preferred" else "必须"
            rendered.append(f"{field_label}{_condition_operator_text(field)}{_condition_value_text(field, value)}（{effect}）")
        if rendered:
            parts.append(f"{label}：" + "、".join(rendered))

    qualitative = _unique_texts(snapshot.get("qualitative_requirements"))
    if qualitative:
        parts.append("定性诉求：" + "；".join(qualitative))
    exclusions = snapshot.get("exclusions") if isinstance(snapshot.get("exclusions"), dict) else {}
    excluded = [*_unique_texts(exclusions.get("industries")), *_unique_texts(exclusions.get("risk_flags"))]
    if excluded:
        parts.append("排除：" + "、".join(excluded))
    unstructured = _unique_texts(snapshot.get("unstructured_notes"))
    if unstructured:
        parts.append("补充：" + "；".join(unstructured))
    if parts:
        return "；".join(parts)
    return "本轮按用户当前表达进行候选筛选"


def target_link_map(brief: dict[str, Any]) -> dict[str, str]:
    """Name -> target id for every final selection in the v2 brief."""
    mapping: dict[str, str] = {}
    for bucket in ("recommended", "runner_ups"):
        for item in brief.get(bucket) or []:
            name = str(item.get("name") or "").strip()
            target_id = str(item.get("id") or "").strip()
            if name and target_id:
                mapping.setdefault(name, target_id)
    return mapping


def sanitize_writer_output(
    answer_text: str,
    *,
    forbidden_ids: list[str] | None = None,
    forbidden_phrases: list[str] | None = None,
) -> str:
    """Remove model-authored links, URLs and executable ids before link backfill."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", answer_text or "")
    # ``\S+`` is unsafe in Chinese prose: there is often no whitespace after
    # the URL, so it can consume the rest of the paragraph together with the
    # target name.  Internal ids have a deliberately narrow alphabet; public
    # URLs stop at Markdown punctuation or whitespace.
    text = re.sub(
        r"https?://[^\s)\]]+|www\.[^\s)\]]+|/targets/[A-Za-z0-9-]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    for candidate_id in sorted({str(value) for value in (forbidden_ids or []) if str(value)}, key=len, reverse=True):
        text = text.replace(candidate_id, "")
    for phrase in sorted({str(value).strip() for value in (forbidden_phrases or []) if str(value).strip()}, key=len, reverse=True):
        text = text.replace(phrase, "")
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def backfill_target_links(answer_text: str, link_map: dict[str, str]) -> str:
    """Replace target names, or safe unique abbreviations, with internal links.

    Writer prose often drops a legal suffix.  Full database names always win;
    an abbreviation is accepted only when it is at least four characters and
    unique inside this turn's final brief, so a short/common prefix cannot link
    to the wrong target.
    """
    if not answer_text or not link_map:
        return answer_text
    replacements = dict(link_map)
    aliases: dict[str, set[str]] = {}
    for name, target_id in link_map.items():
        alias = _target_name_alias(name)
        if alias and alias != name and len(alias) >= 4:
            aliases.setdefault(alias, set()).add(target_id)
    for alias, target_ids in aliases.items():
        if len(target_ids) == 1 and alias not in replacements:
            replacements[alias] = next(iter(target_ids))

    names = sorted(replacements, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(name) for name in names))
    used_target_ids: dict[str, int] = {}

    def already_linked(text: str, start: int, end: int) -> bool:
        has_opening_bracket = start > 0 and text[start - 1] == "["
        has_link_suffix = text[end : end + 2].startswith("](")
        return has_opening_bracket or has_link_suffix

    def replace(match: re.Match[str]) -> str:
        name = match.group(0)
        target_id = replacements.get(name)
        if target_id is None or already_linked(answer_text, match.start(), match.end()):
            return name
        if used_target_ids.get(target_id, 0) >= MAX_LINKS_PER_TARGET:
            return name
        used_target_ids[target_id] = used_target_ids.get(target_id, 0) + 1
        return f"[{name}](/targets/{target_id})"

    return pattern.sub(replace, answer_text)


_TARGET_LEGAL_SUFFIXES = (
    "集团股份有限公司",
    "股份有限公司",
    "有限责任公司",
    "集团有限公司",
    "有限公司",
)


def _target_name_alias(name: str) -> str:
    value = str(name or "").strip()
    for suffix in _TARGET_LEGAL_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)].strip()
    return value


def plain_text_for_copy(answer_text: str) -> str:
    """Strip internal links back to bare names for pasting into chat."""
    return re.sub(r"\[([^\]]+)\]\((?:/[^)]*)\)", r"\1", answer_text or "")


def fallback_answer_markdown(brief: dict[str, Any]) -> str:
    """Rule fallback using exactly the same v2 facts and statuses as the Writer."""
    summary = str(brief.get("intent_summary") or "").strip()
    count = int(brief.get("candidate_pool_count") or 0)
    recommended = [item for item in brief.get("recommended") or [] if isinstance(item, dict)]
    lines: list[str] = []
    if summary:
        lines.append(f"按当前需求「{summary}」进行了筛选。")
    else:
        lines.append("已按本轮当前需求进行了筛选。")
    if count:
        capped = "（候选较多，已公平收口至 40 家）" if brief.get("candidate_pool_capped") else ""
        lines.append(f"本轮汇总了 {count} 家去重候选{capped}。")

    if brief.get("selection_source") != "deep_eval":
        lines.append("本轮深评未能完整返回，以下仅按初筛结果整理，均需进一步核实。")

    if not recommended:
        lines.append("按当前条件未形成可推荐名单。可以补充或调整行业、地区、规模等条件后再试。")
        return "\n\n".join(lines)

    lines.append("\n重点候选：")
    for index, item in enumerate(recommended, start=1):
        lines.extend(_fallback_candidate_lines(item, prefix=f"{index}. "))

    runner_ups = [item for item in brief.get("runner_ups") or [] if isinstance(item, dict)]
    if runner_ups:
        lines.append("\n备选候选：")
        for index, item in enumerate(runner_ups, start=1):
            lines.extend(_fallback_candidate_lines(item, prefix=f"{index}. "))
    return "\n".join(lines).strip()


def _fallback_candidate_lines(item: dict[str, Any], *, prefix: str) -> list[str]:
    facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
    fact_text = "，".join(_fact_fragments(facts))
    lines = [f"{prefix}{item.get('name') or '未命名标的'}" + (f" —— {fact_text}" if fact_text else "")]
    relaxed = item.get("relaxed_fields") or []
    if item.get("matched_full_conditions"):
        lines.append("   筛选状态：命中至少一组完整条件。")
    elif relaxed:
        labels = "、".join(str(value.get("label") or value.get("field")) for value in relaxed if isinstance(value, dict))
        if item.get("required_relaxation"):
            lines.append(f"   筛选状态：放宽必须条件（{labels}）后补充，仅供参考，需重点核实。")
        else:
            lines.append(f"   筛选状态：放宽偏好条件（{labels}）后补充。")
    verdicts = item.get("qualitative_verdicts") if isinstance(item.get("qualitative_verdicts"), dict) else {}
    if verdicts:
        lines.append("   定性判断：" + "；".join(f"{key}：{value}" for key, value in verdicts.items()))
    for point in item.get("reason_points") or []:
        if str(point or "").strip():
            lines.append(f"   推荐理由：{str(point).strip()}")
    if item.get("risks"):
        lines.append(f"   风险：{item['risks']}")
    if item.get("info_gaps"):
        lines.append(f"   信息缺口：{item['info_gaps']}")
    if item.get("already_in_progress"):
        lines.append("   （这家已经在推进中）")
    elif item.get("other_buyer_in_deep_progress"):
        lines.append("   （这家正与其他买家深入推进）")
    return lines


def _fact_fragments(facts: dict[str, Any]) -> list[str]:
    mapping = (
        ("industry", "行业"), ("region", "地区"), ("revenue_text", "营收"),
        ("net_profit_text", "净利"), ("total_profit_text", "利润总额"),
        ("valuation_text", "估值"), ("asking_price_text", "要价"),
        ("market_cap_text", "市值"), ("pe_ratio", "PE"), ("debt_ratio", "负债率"),
        ("can_control", "控股"), ("can_consolidate", "并表"),
        ("transfer_ratio_max", "最高转让比例"), ("listed_status", "上市状态"),
        ("cash_flow_status", "现金流"), ("profitability_status", "盈利状态"),
        ("management_retention_possible", "管理层留任"),
    )
    fragments: list[str] = []
    for key, label in mapping:
        value = facts.get(key)
        if value is None or value == "":
            continue
        suffix = "%" if key in {"debt_ratio", "transfer_ratio_max"} else ""
        fragments.append(f"{label} {value}{suffix}")
    return fragments


def _validate_id_list(
    raw: Any,
    *,
    label: str,
    allowed_set: set[str],
    pool_set: set[str],
    dropped_ids: set[str],
    notes: list[str],
) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        candidate_id = str(item.get("id") if isinstance(item, dict) else item or "").strip()
        if not candidate_id:
            continue
        if candidate_id in seen:
            notes.append(f"{label} 含重复 id，已丢弃：{candidate_id}")
            continue
        seen.add(candidate_id)
        if candidate_id in dropped_ids:
            notes.append(f"{label} 选择了 dropped id，已丢弃：{candidate_id}")
            continue
        if candidate_id not in pool_set:
            notes.append(f"{label} 含候选池外 id，已丢弃：{candidate_id}")
            continue
        if candidate_id not in allowed_set:
            notes.append(f"{label} 含不在 deep-eval ranked 的 id，已丢弃：{candidate_id}")
            continue
        values.append(candidate_id)
    return values


def _normalise_follow_ups(raw: Any, *, pool_ids: list[str], notes: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for index, item in enumerate(raw):
        suggestion = str(item or "").strip()
        if not suggestion:
            continue
        if _URL_OR_LINK.search(suggestion) or any(candidate_id in suggestion for candidate_id in pool_ids):
            notes.append(f"follow_up_suggestions[{index}] 含 id 或链接，已丢弃")
            continue
        if _PROMISES_FULL_LIST.search(suggestion):
            notes.append(f"follow_up_suggestions[{index}] 承诺超预算全集，已丢弃")
            continue
        if _ADVISER_STYLE_FOLLOW_UP.match(suggestion):
            notes.append(f"follow_up_suggestions[{index}] 是顾问建议口吻，已丢弃：{suggestion}")
            continue
        if len(suggestion) > MAX_FOLLOW_UP_LENGTH:
            suggestion = suggestion[:MAX_FOLLOW_UP_LENGTH].rstrip("，,。；; ")
            notes.append(f"follow_up_suggestions[{index}] 超过 {MAX_FOLLOW_UP_LENGTH} 字，已截断")
        if suggestion and suggestion not in values:
            values.append(suggestion)
        elif suggestion:
            notes.append(f"follow_up_suggestions 含重复短句，已去重：{suggestion}")
    if len(values) > MAX_FOLLOW_UPS:
        notes.append(f"follow_up_suggestions 超过 {MAX_FOLLOW_UPS} 条，已截断")
    return values[:MAX_FOLLOW_UPS]


def _group_strengths(snapshot: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    raw_groups = snapshot.get("condition_groups") if isinstance(snapshot.get("condition_groups"), list) else []
    group_number = 0
    for raw in raw_groups:
        if not isinstance(raw, dict) or not isinstance(raw.get("conditions"), dict) or not raw.get("conditions"):
            continue
        group_number += 1
        raw_strength = raw.get("strength") if isinstance(raw.get("strength"), dict) else {}
        result[f"group-{group_number}"] = {
            str(column): "preferred" if str(raw_strength.get(column) or "required") == "preferred" else "required"
            for column in raw["conditions"]
        }
    return result


def _enrich_screening_hit(hit: dict[str, Any], groups: dict[str, dict[str, str]]) -> dict[str, Any]:
    group_id = str(hit.get("group_id") or "")
    strengths = groups.get(group_id) or {}
    return {
        "call_index": hit.get("call_index"),
        "group_id": group_id or None,
        "full_conditions": bool(hit.get("full_conditions")),
        "applied_conditions": deepcopy(hit.get("applied_conditions") or {}),
        "relaxed_fields": [
            _relaxed_field(str(column), strengths.get(str(column), "required"))
            for column in hit.get("relaxed_fields") or []
            if str(column or "").strip()
        ],
        "relaxation_reason": _text(hit.get("relaxation_reason")),
        "based_on_call_index": hit.get("based_on_call_index"),
    }


def _relaxed_field(column: str, strength: str) -> dict[str, str]:
    field = SCREENING_FIELDS_BY_COLUMN.get(column)
    return {
        "field": column,
        "label": field.label if field else column,
        "strength": "preferred" if strength == "preferred" else "required",
    }


def _collect_relaxed_fields(hits: list[dict[str, Any]]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        for item in hit.get("relaxed_fields") or []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("field") or ""), str(item.get("strength") or ""))
            if key[0] and key not in seen:
                seen.add(key)
                values.append(dict(item))
    return values


def _screening_run_for_brief(run: dict[str, Any], groups: dict[str, dict[str, str]]) -> dict[str, Any]:
    if run.get("valid") is False:
        return {
            "call_index": run.get("call_index"),
            "valid": False,
            "group_id": run.get("group_id"),
            "count_only": bool(run.get("count_only")),
            "note": run.get("note"),
            "error_code": run.get("error_code"),
            "error": run.get("error"),
        }
    group_id = str(run.get("group_id") or "")
    strengths = groups.get(group_id) or {}
    return {
        "call_index": run.get("call_index"),
        "valid": True,
        "group_id": group_id or None,
        "note": run.get("note"),
        "count_only": bool(run.get("count_only")),
        "matched_count": run.get("eligible_count"),
        "returned_count": run.get("returned_count"),
        "full_conditions": bool(run.get("full_conditions")),
        "applied_conditions": deepcopy(run.get("filters") or {}),
        "relaxed_fields": [
            _relaxed_field(str(column), strengths.get(str(column), "required"))
            for column in run.get("relaxed_fields") or []
            if str(column or "").strip()
        ],
        "relaxation_reason": _text(run.get("relaxation_reason")),
        "based_on_call_index": run.get("based_on_call_index"),
        "excluded_by_condition": deepcopy(run.get("excluded_by_condition") or {}),
    }


def _bounded_text(raw: Any, limit: int, label: str, notes: list[str]) -> str | None:
    value = _text(raw)
    if value and len(value) > limit:
        notes.append(f"{label} 的文本超过 {limit} 字，已截断")
        return value[:limit]
    return value


def _text(value: Any) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _unique_texts(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def _condition_operator_text(field: Any) -> str:
    if field is None:
        return "="
    return {"gte": "≥", "lte": "≤", "not_overlap": "排除", "region_any": "="}.get(field.operator, "=")


def _condition_value_text(field: Any, value: Any) -> str:
    if field and field.value_type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if field.unit_hint.startswith("单位元"):
            return _money_text(number)
        suffix = "%" if "百分数" in field.unit_hint else ""
        return f"{number:g}{suffix}"
    if field and field.value_type == "boolean":
        return "是" if bool(value) else "否"
    if field and field.value_type == "region_list" and isinstance(value, list):
        rendered = []
        for item in value:
            if isinstance(item, dict):
                rendered.append("".join(str(item.get(key) or "") for key in ("province", "city", "district")))
        return "或".join(part for part in rendered if part)
    if isinstance(value, list):
        return "或".join(str(item) for item in value)
    if field and field.value_type in {"enum", "enum_list"}:
        try:
            options = dict(indicator_by_column("buyer_intent", field.column).enum_options or ())
            return str(options.get(str(value), value))
        except KeyError:
            pass
    return str(value)


def _money_text(number: float) -> str:
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:g}亿"
    if abs(number) >= 10_000:
        return f"{number / 10_000:g}万"
    return f"{number:g}元"
