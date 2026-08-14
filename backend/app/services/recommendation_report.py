"""Customer-facing recommendation report context and Markdown fallbacks.

The report itself remains text-first Markdown.  This module only prepares a
complete, bounded fact package so the LLM can combine structured indicators,
long-form profile sections and deep-evaluation findings without inventing data.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import groups_for, indicators_for
from backend.app.services.profile_sections import PROFILE_SECTION_LABELS, load_profile_sections

BUYER_FACING_TARGET_REPORT = "buyer_facing_target_report"
SELLER_FACING_BUYER_REPORT = "seller_facing_buyer_report"
REPORT_TYPES = frozenset({BUYER_FACING_TARGET_REPORT, SELLER_FACING_BUYER_REPORT})
REPORT_RECOMMENDED_MIN_ITEMS = 3
REPORT_RECOMMENDED_MAX_ITEMS = 5
REPORT_MAX_ITEMS = 10
REPORT_CONTEXT_VERSION = 1
REPORT_MAX_FIELD_TEXT_CHARS = 2000
REPORT_MAX_MARKDOWN_CHARS = 120_000

_SELLER_EXTRA_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("industry_l1", "一级行业（兼容）", "业务与产品"),
    ("industry_l2", "二级行业（兼容）", "业务与产品"),
    ("gap_summary", "信息缺口摘要", "交易属性与出售诉求"),
)

_BUYER_INTENT_EXTRA_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("intent_name", "需求名称", "需求原文与摘要"),
    ("budget_min_yuan", "预算下限", "经营与财务"),
    ("budget_max_yuan", "预算上限", "经营与财务"),
    ("relocation_target_regions_json", "迁址目标地区", "交易与能力要求"),
    ("needs_confirmation_json", "待确认信息", "其他信息"),
)

_BUYER_PARTY_COLUMNS = (
    "buyer_name",
    "aliases_json",
    "industries_json",
    "industry_l2_json",
    "region_province",
    "region_city",
    "notes",
)

_REPORT_FIELD_EXCLUSIONS = frozenset(
    {
        "information_status",
        # 级别与它的 E 细分原因是管理字段，不是推荐报告要讲的业务事实。
        "target_grade",
        "lifecycle_status",
        "intent_grade",
        "status",
        "pause_reason",
        "condition_effects_json",
    }
)


def default_report_type(mode: str) -> str:
    if mode == "buyer_to_target":
        return BUYER_FACING_TARGET_REPORT
    if mode == "target_to_buyer":
        return SELLER_FACING_BUYER_REPORT
    raise ValueError(f"Unsupported recommendation mode: {mode}")


def report_type_matches_mode(report_type: str, mode: str) -> bool:
    return report_type == default_report_type(mode)


def default_report_title(
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
    report_type: str,
) -> str:
    if report_type == BUYER_FACING_TARGET_REPORT:
        anchor = selected_items[0].get("buyer_intent_name") or "买家需求"
        return f"{anchor} - 推荐标的报告"
    anchor = selected_items[0].get("seller_target_name") or "标的项目"
    return f"{anchor} - 推荐买家报告"


def ensure_report_item_count(selected_items: list[dict[str, Any]]) -> None:
    if not selected_items:
        raise ValueError("At least one active selected item is required.")
    if len(selected_items) > REPORT_MAX_ITEMS:
        raise ValueError(f"A recommendation report supports at most {REPORT_MAX_ITEMS} items.")


def build_recommendation_report_context(
    db: Session,
    *,
    report: dict[str, Any],
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Load the complete current fact package for one report generation run."""
    ensure_report_item_count(selected_items)
    mode = str(session["mode"])
    report_type = str(report["report_type"])
    if not report_type_matches_mode(report_type, mode):
        raise ValueError(f"Report type {report_type} does not match session mode {mode}.")

    target_ids = _unique_ids(item.get("seller_target_id") for item in selected_items)
    intent_ids = _unique_ids(item.get("buyer_intent_id") for item in selected_items)
    party_ids = _unique_ids(item.get("buyer_party_id") for item in selected_items)

    targets = _load_entity_rows(db, "seller_target", target_ids)
    intents = _load_entity_rows(db, "buyer_intent", intent_ids)
    parties = _load_buyer_parties(db, party_ids)
    target_sections = load_profile_sections(
        db, entity_type="seller_target", entity_ids=target_ids
    )
    intent_sections = load_profile_sections(
        db, entity_type="buyer_intent", entity_ids=intent_ids
    )
    scenarios = _load_buyer_intent_scenarios(db, intent_ids)
    candidate_snapshots = _load_latest_candidate_snapshots(db, UUID(str(session["id"])))

    def target_package(target_id: Any) -> dict[str, Any]:
        key = str(target_id or "")
        row = targets.get(key, {})
        return {
            "object_type": "标的",
            "name": row.get("target_name"),
            "field_groups": _grouped_entity_fields("seller_target", row),
            "supplementary_sections": _profile_section_package(target_sections.get(key, {})),
        }

    def buyer_package(intent_id: Any, party_id: Any) -> dict[str, Any]:
        intent_key = str(intent_id or "")
        party_key = str(party_id or "")
        intent = intents.get(intent_key, {})
        party = parties.get(party_key, {})
        return {
            "object_type": "买家需求",
            "name": intent.get("intent_name"),
            "buyer_party": _json_safe(
                {key: value for key, value in party.items() if key != "id"}
            ),
            "field_groups": _grouped_entity_fields("buyer_intent", intent),
            "supplementary_sections": _profile_section_package(intent_sections.get(intent_key, {})),
            "active_scenarios": scenarios.get(intent_key, []),
        }

    first = selected_items[0]
    if mode == "buyer_to_target":
        anchor = buyer_package(first.get("buyer_intent_id"), first.get("buyer_party_id"))
    else:
        anchor = target_package(first.get("seller_target_id"))

    candidates: list[dict[str, Any]] = []
    for position, item in enumerate(selected_items, start=1):
        pair_key = _pair_key(item.get("seller_target_id"), item.get("buyer_intent_id"))
        candidate_snapshot = candidate_snapshots.get(pair_key, {})
        evidence = candidate_snapshot.get("evidence_json")
        if not isinstance(evidence, dict):
            evidence = item.get("evidence_snapshot_json")
        if not isinstance(evidence, dict):
            evidence = {}
        deep_eval = candidate_snapshot.get("deep_eval")
        if not isinstance(deep_eval, dict):
            deep_eval = {}

        package: dict[str, Any] = {
            "position": position,
            "selection_snapshot": {
                "match_summary": item.get("match_summary"),
                "gap_summary": item.get("gap_summary"),
                "risk_summary": item.get("risk_summary"),
                "reason_snapshot": item.get("reason_snapshot"),
            },
            "matching_context": {
                "rule_matches": evidence.get("matches") or [],
                "rule_gaps": evidence.get("gaps") or [],
                "missing_dimensions": candidate_snapshot.get("missing_dimensions")
                or (evidence.get("score") or {}).get("missing_dimensions")
                or [],
                "best_scenario_label": candidate_snapshot.get("best_scenario_label"),
                "matched_scenario_labels": candidate_snapshot.get("matched_scenario_labels") or [],
                "deep_evaluation": {
                    "reason": deep_eval.get("reason") or item.get("reason_snapshot"),
                    "risks": deep_eval.get("risks"),
                    "info_gaps": deep_eval.get("info_gaps"),
                },
            },
        }
        if mode == "buyer_to_target":
            package["candidate"] = target_package(item.get("seller_target_id"))
        else:
            package["candidate"] = buyer_package(
                item.get("buyer_intent_id"), item.get("buyer_party_id")
            )
        candidates.append(package)

    audience = "买家客户" if mode == "buyer_to_target" else "卖方客户"
    return {
        "schema_version": REPORT_CONTEXT_VERSION,
        "report": {
            "kind": "推荐标的报告" if mode == "buyer_to_target" else "推荐买家报告",
            "title": report.get("title"),
            "audience": audience,
            "candidate_kind": "标的" if mode == "buyer_to_target" else "买家",
            "candidate_count": len(candidates),
            "buyer_name_disclosure": "真实名称",
        },
        "recommendation_basis": {
            "direction": (
                "买家需求到候选标的"
                if mode == "buyer_to_target"
                else "当前标的到候选买家"
            ),
            "effective_conditions": _json_safe(
                session.get("latest_condition_snapshot_json")
                or session.get("initial_condition_snapshot_json")
                or {}
            ),
        },
        "anchor": anchor,
        "candidates": candidates,
        "writing_contract": {
            "purpose": "帮助外部客户在数分钟内判断候选是否值得继续了解和跟进",
            "analysis_style": "综合字段、长文本和深评内容，按业务大类归纳，不逐字段机械复述",
            "fact_boundary": "只能使用本上下文；事实、初步判断、待确认事项必须区分",
            "forbidden": [
                "内部数值评分、A/B/C等级、算法或调试信息",
                "虚构财务数字、主体身份、交易状态或风险",
                "尽调报告式长篇分析或确定性投资结论",
                "联系人、联系方式、负责人和系统元数据",
            ],
            "format": "中文Markdown；只用标题、段落、无序列表、粗体和简单四列表格",
            "table_columns": ["评估维度", "客户关注重点", "候选现有情况", "初步判断"],
            "table_rules": "最多四列，单元格不嵌套列表或表格，内容简洁",
        },
    }


def build_fallback_report_markdown(context: dict[str, Any], *, title: str) -> str:
    """Produce a readable report even when the report LLM is unavailable."""
    report = context.get("report") or {}
    mode = (context.get("session") or {}).get("mode")
    candidates = context.get("candidates") or []
    candidate_kind = report.get("candidate_kind")
    object_label = (
        f"候选{candidate_kind}"
        if candidate_kind
        else ("候选标的" if mode == "buyer_to_target" else "候选买家")
    )
    lines = [
        f"# {title}",
        "",
        (
            f"> 本报告面向{report.get('audience') or '外部客户'}，"
            "用于初步判断是否值得继续了解，不构成尽职调查、估值或投资意见。"
        ),
        "",
        "## 推荐概览",
        "",
        (
            f"本次共纳入 {len(candidates)} 个{object_label}。"
            "以下内容根据系统现有资料和推荐评估整理；未提供的信息均列为待确认。"
        ),
        "",
    ]
    for candidate in candidates:
        entity = candidate.get("candidate") or {}
        name = entity.get("name") or f"未命名{object_label}"
        position = candidate.get("position") or 1
        matching = candidate.get("matching_context") or {}
        selection = candidate.get("selection_snapshot") or {}
        lines.extend([f"## {position}. {name}", "", "### 候选概况", ""])
        summary_rows = _fallback_summary_rows(entity)
        if summary_rows:
            for label, value in summary_rows:
                lines.append(f"- **{label}**：{value}")
        else:
            lines.append("现有资料较少，建议在继续接触前补充候选基本情况。")
        lines.extend(
            [
                "",
                "### 匹配情况",
                "",
                "| 评估维度 | 客户关注重点 | 候选现有情况 | 初步判断 |",
                "|---|---|---|---|",
                (
                    "| 综合匹配 | 以当前推荐条件为准 | "
                    f"{_table_text(selection.get('match_summary') or '暂无明确摘要')} |"
                    " 初步可关注 |"
                ),
                (
                    "| 信息完整度 | 关键条件需有事实支撑 | "
                    f"{_table_text(selection.get('gap_summary') or '暂无显著缺口')} | "
                    f"{'待补充' if selection.get('gap_summary') else '现有资料可供初判'} |"
                ),
                "",
                "### 需要关注的信息",
                "",
            ]
        )
        gaps = [
            *[str(value) for value in (matching.get("rule_gaps") or []) if value],
            str((matching.get("deep_evaluation") or {}).get("risks") or "").strip(),
            str((matching.get("deep_evaluation") or {}).get("info_gaps") or "").strip(),
        ]
        gaps = [value for value in gaps if value]
        if gaps:
            lines.extend(f"- {value}" for value in gaps[:5])
        else:
            lines.append("- 暂无额外风险或信息缺口记录，仍建议由顾问复核关键事实。")
        conclusion = (
            (matching.get("deep_evaluation") or {}).get("reason")
            or selection.get("reason_snapshot")
            or selection.get("match_summary")
            or "现有信息显示具备初步接触价值，建议结合关键缺口进一步确认。"
        )
        lines.extend(["", "### 简要结论", "", str(conclusion), ""])
    return "\n".join(lines).strip()


def normalize_report_markdown(markdown: str, *, title: str) -> str:
    """Keep LLM output inside the Markdown subset shared by preview and DOCX."""
    value = (markdown or "").strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    value = re.sub(r"<[^>]+>", "", value)
    value = value[:REPORT_MAX_MARKDOWN_CHARS].strip()
    if not value:
        return ""
    if not re.match(r"^#\s+", value):
        value = f"# {title}\n\n{value}"
    return value


def _load_entity_rows(
    db: Session,
    entity_type: str,
    entity_ids: list[UUID],
) -> dict[str, dict[str, Any]]:
    if not entity_ids:
        return {}
    if entity_type == "seller_target":
        table = "seller_target"
        registry_columns = [indicator.column for indicator in indicators_for(entity_type)]
        extra_columns = [column for column, _, _ in _SELLER_EXTRA_COLUMNS]
    elif entity_type == "buyer_intent":
        table = "buyer_intent"
        registry_columns = [indicator.column for indicator in indicators_for(entity_type)]
        extra_columns = [column for column, _, _ in _BUYER_INTENT_EXTRA_COLUMNS]
    else:  # pragma: no cover - call sites are fixed
        raise ValueError(f"Unsupported report entity type: {entity_type}")
    columns = _dedupe(["id", *registry_columns, *extra_columns])
    select_columns = ", ".join(
        f"{column}::text as {column}" if column == "updated_at" else column
        for column in columns
    )
    statement = text(
        f"""
        select {select_columns}
        from {table}
        where id in :entity_ids
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    ).bindparams(bindparam("entity_ids", expanding=True))
    rows = db.execute(
        statement,
        {
            "entity_ids": tuple(entity_ids),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return {str(row["id"]): dict(row) for row in rows}


def _load_buyer_parties(db: Session, party_ids: list[UUID]) -> dict[str, dict[str, Any]]:
    if not party_ids:
        return {}
    select_columns = ", ".join(
        f"{column}::text as {column}" if column == "updated_at" else column
        for column in ("id", *_BUYER_PARTY_COLUMNS)
    )
    rows = db.execute(
        text(
            f"""
            select {select_columns}
            from buyer_party
            where id in :party_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("party_ids", expanding=True)),
        {
            "party_ids": tuple(party_ids),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    return {str(row["id"]): dict(row) for row in rows}


def _load_buyer_intent_scenarios(
    db: Session, intent_ids: list[UUID]
) -> dict[str, list[dict[str, Any]]]:
    if not intent_ids:
        return {}
    rows = db.execute(
        text(
            """
            select buyer_intent_id, id, label, sort_order, fields_json,
                   needs_confirmation_json
            from buyer_intent_scenario
            where buyer_intent_id in :intent_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and active = true
              and deleted_at is null
            order by buyer_intent_id, sort_order, created_at
            """
        ).bindparams(bindparam("intent_ids", expanding=True)),
        {
            "intent_ids": tuple(intent_ids),
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["buyer_intent_id"])].append(
            _json_safe(
                {
                    "label": row["label"],
                    "fields": row["fields_json"],
                    "needs_confirmation": row["needs_confirmation_json"],
                }
            )
        )
    return dict(grouped)


def _load_latest_candidate_snapshots(
    db: Session, session_id: UUID
) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select content
            from recommendation_message
            where session_id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and content_type = 'json'
              and metadata_json ->> 'message_type' in ('reranked_candidates', 'initial_candidates')
            order by created_at desc
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    snapshots: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            payload = json.loads(row["content"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            key = _pair_key(candidate.get("seller_target_id"), candidate.get("buyer_intent_id"))
            if key != ":" and key not in snapshots:
                snapshots[key] = candidate
    return snapshots


def _grouped_entity_fields(entity_type: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    group_labels = {group.key: group.label for group in groups_for(entity_type)}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for indicator in indicators_for(entity_type):
        if indicator.column in _REPORT_FIELD_EXCLUSIONS:
            continue
        value = row.get(indicator.column)
        if _empty(value):
            continue
        default_group_label = "需求原文与摘要" if entity_type == "buyer_intent" else "其他信息"
        group_label = group_labels.get(indicator.group or "", default_group_label)
        grouped[group_label].append(
            {
                "label": indicator.label,
                "value": _json_safe(value),
            }
        )
        seen.add(indicator.column)
    extras = (
        _SELLER_EXTRA_COLUMNS
        if entity_type == "seller_target"
        else _BUYER_INTENT_EXTRA_COLUMNS
    )
    for column, label, group_label in extras:
        value = row.get(column)
        if column in seen or _empty(value):
            continue
        grouped[group_label].append({"label": label, "value": _json_safe(value)})
    return [{"group": label, "fields": fields} for label, fields in grouped.items()]


def _profile_section_package(sections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for code, section in sections.items():
        result.append(
            {
                "section_label": PROFILE_SECTION_LABELS.get(code, code),
                "content_text": _trim_text(section.get("content_text")),
                "info_status": section.get("info_status"),
                "as_of_date": section.get("as_of_date"),
            }
        )
    return result


def _fallback_summary_rows(entity: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for group in entity.get("field_groups") or []:
        for field in group.get("fields") or []:
            value = field.get("value")
            if _empty(value):
                continue
            rows.append((str(field.get("label") or field.get("field")), _display_value(value)))
            if len(rows) >= 10:
                return rows
    return rows


def _display_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(_display_value(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{key}：{_display_value(item)}" for key, item in value.items())
    return str(value)


def _table_text(value: Any) -> str:
    return str(value or "").replace("|", "／").replace("\n", "；")[:300]


def _unique_ids(values: Any) -> list[UUID]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if not value:
            continue
        parsed = UUID(str(value))
        if parsed not in seen:
            result.append(parsed)
            seen.add(parsed)
    return result


def _pair_key(seller_target_id: Any, buyer_intent_id: Any) -> str:
    return f"{seller_target_id or ''}:{buyer_intent_id or ''}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _trim_text(value: Any) -> str | None:
    text_value = str(value or "").strip()
    if not text_value:
        return None
    return text_value[:REPORT_MAX_FIELD_TEXT_CHARS]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (UUID, Decimal, date, datetime)):
        return str(value)
    if isinstance(value, str):
        return value[:REPORT_MAX_FIELD_TEXT_CHARS]
    return value
