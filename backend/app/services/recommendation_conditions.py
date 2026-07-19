"""Parse recommendation-chat messages into condition overrides and route them.

The LLM node (`recommendation_query_parser`) only extracts; routing between
full refilter / re-evaluate / display filter / question is derived from the
extraction result in code so it stays deterministic and testable.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.prompting import render_template
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.industry_taxonomy import industry_l1_prompt_list

QUERY_PARSER_NODE_NAME = "recommendation_query_parser"

# Override fields the chat may touch, with their value kind for coercion.
# Every field here maps 1:1 onto the anchor keys read by the rule scorer.
OVERRIDE_FIELD_KINDS: dict[str, str] = {
    "industries_json": "industry_list",
    "excluded_industries_json": "industry_list",
    "region_scope_summary": "text",
    "min_net_profit_yuan": "number",
    "min_revenue_yuan": "number",
    "min_valuation_yuan": "number",
    "max_valuation_yuan": "number",
    "max_pe": "number",
    "min_market_cap_yuan": "number",
    "max_market_cap_yuan": "number",
    "requires_control": "yes_no",
    "requires_consolidation": "yes_no",
    "desired_equity_ratio_min": "number",
    "preferred_listed_status": "listed_status",
    "max_debt_ratio": "number",
}

FIELD_LABELS: dict[str, str] = {
    "industries_json": "行业",
    "excluded_industries_json": "排除行业",
    "region_scope_summary": "地区",
    "min_net_profit_yuan": "净利润下限",
    "min_revenue_yuan": "营收下限",
    "min_valuation_yuan": "估值下限",
    "max_valuation_yuan": "估值上限",
    "max_pe": "PE上限",
    "min_market_cap_yuan": "市值下限",
    "max_market_cap_yuan": "市值上限",
    "requires_control": "控股要求",
    "requires_consolidation": "并表要求",
    "desired_equity_ratio_min": "最低股比",
    "preferred_listed_status": "上市偏好",
    "max_debt_ratio": "负债率上限",
}

_LISTED_STATUS_VALUES = {"listed", "unlisted", "preparing_listing", "pre_ipo", "any", "unknown"}
_YES_NO_VALUES = {"yes", "no", "unknown"}


def _coerce_value(kind: str, value: Any) -> Any | None:
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number
    if kind == "text":
        text_value = str(value or "").strip()
        return text_value or None
    if kind == "yes_no":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _YES_NO_VALUES else None
    if kind == "listed_status":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _LISTED_STATUS_VALUES else None
    if kind == "industry_list":
        if isinstance(value, str):
            item = value.strip()
            return [item] if item else None
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item or "").strip()]
            return items or None
        return None
    return None


def normalize_parse_result(raw: Any) -> dict[str, Any]:
    """Whitelist-filter the LLM extraction into a safe, typed structure."""
    data = raw if isinstance(raw, dict) else {}
    ops: list[dict[str, Any]] = []
    for item in data.get("condition_ops") or []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").strip().lower()
        field = str(item.get("field") or "").strip()
        if op not in {"set", "remove", "exclude"} or field not in OVERRIDE_FIELD_KINDS:
            continue
        if op == "exclude" and field != "excluded_industries_json":
            continue
        if op == "remove":
            ops.append({"op": "remove", "field": field, "value": None})
            continue
        value = _coerce_value(OVERRIDE_FIELD_KINDS[field], item.get("value"))
        if value is None:
            continue
        if op == "exclude":
            for term in value if isinstance(value, list) else [value]:
                ops.append({"op": "exclude", "field": field, "value": term})
        else:
            ops.append({"op": "set", "field": field, "value": value})

    preferences = [
        str(item).strip()
        for item in (data.get("semantic_preferences") or [])
        if str(item or "").strip()
    ]

    display_ops: list[dict[str, Any]] = []
    for item in data.get("display_ops") or []:
        if not isinstance(item, dict):
            continue
        op_type = str(item.get("type") or "").strip()
        if op_type == "only_grade" and str(item.get("value") or "").upper() in {"A", "B", "C"}:
            display_ops.append({"type": "only_grade", "value": str(item["value"]).upper()})
        elif op_type == "top_n":
            try:
                count = int(item.get("value"))
            except (TypeError, ValueError):
                continue
            if 1 <= count <= 50:
                display_ops.append({"type": "top_n", "value": count})

    question = str(data.get("question") or "").strip() or None
    reply = str(data.get("reply_summary") or "").strip() or None
    return {
        "condition_ops": ops,
        "semantic_preferences": preferences,
        "display_ops": display_ops,
        "question": question,
        "reply_summary": reply,
        "parser_status": "ok",
    }


def fallback_parse_result(user_message: str) -> dict[str, Any]:
    return {
        "condition_ops": [],
        "semantic_preferences": [user_message.strip()] if user_message.strip() else [],
        "display_ops": [],
        "question": None,
        "reply_summary": "条件解析暂不可用，已把这句话作为语义偏好记录",
        "parser_status": "fallback",
    }


def _get_query_parser_node_config(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.model_name, node.temperature, node.top_p, node.max_tokens,
              node.timeout_seconds, node.response_format,
              provider.base_url, provider.api_key_secret_ref, provider.api_key_encrypted,
              prompt.system_prompt, prompt.user_prompt_template
            from model_node_config node
            join model_provider_config provider on provider.id = node.provider_config_id
            left join prompt_template prompt
              on prompt.team_id = node.team_id
             and prompt.workspace_id = node.workspace_id
             and prompt.node_name = node.node_name
             and prompt.is_default = true
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": QUERY_PARSER_NODE_NAME,
        },
    ).mappings().one_or_none()
    if row is None or not row.get("base_url") or not row.get("user_prompt_template"):
        raise ValueError(f"Query parser node is not configured: {QUERY_PARSER_NODE_NAME}")
    return dict(row)


def parse_recommendation_message(
    db: Session,
    *,
    mode: str,
    user_message: str,
    current_conditions: dict[str, Any],
) -> dict[str, Any]:
    """Run the query parser LLM; degrade to a semantic-preference fallback on failure."""
    try:
        node = _get_query_parser_node_config(db)
        variables = {
            "mode": mode,
            "current_conditions_json": json.dumps(current_conditions, ensure_ascii=False, default=str),
            "industry_l1_list": industry_l1_prompt_list(db),
            "user_message": user_message,
        }
        messages = []
        system_prompt = render_template(node.get("system_prompt"), variables)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": render_template(node["user_prompt_template"], variables)})
        llm_result = call_openai_compatible_chat(
            base_url=node["base_url"],
            api_key_secret_ref=node["api_key_secret_ref"],
            api_key_encrypted=node.get("api_key_encrypted"),
            model_name=node["model_name"],
            messages=messages,
            temperature=node["temperature"],
            top_p=node["top_p"],
            max_tokens=node["max_tokens"],
            timeout_seconds=node["timeout_seconds"] or 30,
            response_format=node["response_format"],
        )
        return normalize_parse_result(llm_result.parsed_output_json)
    except (LlmCallError, ValueError, KeyError):
        return fallback_parse_result(user_message)


EMPTY_OVERRIDES: dict[str, Any] = {
    "fields": {},
    "removed_fields": [],
    "extra_excluded_industries": [],
    "semantic_preferences": [],
}


def _normalized_overrides(overrides: Any) -> dict[str, Any]:
    data = overrides if isinstance(overrides, dict) else {}
    return {
        "fields": dict(data.get("fields") or {}),
        "removed_fields": list(data.get("removed_fields") or []),
        "extra_excluded_industries": list(data.get("extra_excluded_industries") or []),
        "semantic_preferences": list(data.get("semantic_preferences") or []),
    }


def merge_condition_overrides(existing: Any, parse_result: dict[str, Any]) -> dict[str, Any]:
    merged = _normalized_overrides(existing)
    for op in parse_result.get("condition_ops") or []:
        field = op["field"]
        if op["op"] == "set":
            merged["fields"][field] = op["value"]
            if field in merged["removed_fields"]:
                merged["removed_fields"].remove(field)
        elif op["op"] == "remove":
            merged["fields"].pop(field, None)
            if field not in merged["removed_fields"]:
                merged["removed_fields"].append(field)
            if field == "excluded_industries_json":
                merged["extra_excluded_industries"] = []
        elif op["op"] == "exclude":
            if op["value"] not in merged["extra_excluded_industries"]:
                merged["extra_excluded_industries"].append(op["value"])
            if "excluded_industries_json" in merged["removed_fields"]:
                merged["removed_fields"].remove("excluded_industries_json")
    for preference in parse_result.get("semantic_preferences") or []:
        if preference not in merged["semantic_preferences"]:
            merged["semantic_preferences"].append(preference)
    return merged


def apply_overrides_to_anchor(anchor: dict[str, Any], overrides: Any) -> dict[str, Any]:
    """Return a copy of the intent anchor with session overrides applied."""
    data = _normalized_overrides(overrides)
    effective = dict(anchor)
    for field in data["removed_fields"]:
        if field in {"industries_json", "excluded_industries_json"}:
            effective[field] = []
        else:
            effective[field] = None
        if field == "industries_json":
            effective["industry_primary"] = None
    for field, value in data["fields"].items():
        effective[field] = value
    if data["extra_excluded_industries"]:
        existing = effective.get("excluded_industries_json")
        base = [str(item) for item in existing] if isinstance(existing, list) else []
        for term in data["extra_excluded_industries"]:
            if term not in base:
                base.append(term)
        effective["excluded_industries_json"] = base
    return effective


def conditions_snapshot(anchor: dict[str, Any], overrides: Any) -> dict[str, Any]:
    """Active condition values (base + overrides) for display and parser context."""
    effective = apply_overrides_to_anchor(anchor, overrides)
    data = _normalized_overrides(overrides)
    snapshot: dict[str, Any] = {}
    for field in OVERRIDE_FIELD_KINDS:
        value = effective.get(field)
        if value in (None, "", []):
            continue
        snapshot[field] = value
    snapshot["semantic_preferences"] = data["semantic_preferences"]
    return snapshot


def derive_route(parse_result: dict[str, Any] | None) -> str:
    """Deterministic routing from the extraction result (never LLM-decided)."""
    if parse_result is None:
        return "refilter"
    if parse_result.get("condition_ops"):
        return "refilter"
    if parse_result.get("semantic_preferences"):
        return "re_evaluate"
    if parse_result.get("display_ops"):
        return "display"
    if parse_result.get("question"):
        return "question"
    return "noop"


def describe_condition_ops(ops: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for op in ops:
        label = FIELD_LABELS.get(op["field"], op["field"])
        if op["op"] == "remove":
            parts.append(f"取消{label}")
        elif op["op"] == "exclude":
            parts.append(f"排除{op['value']}")
        else:
            value = op["value"]
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            elif isinstance(value, float) and value >= 10000:
                value = _compact_money(value)
            parts.append(f"{label}={value}")
    return "、".join(parts)


def _compact_money(value: float) -> str:
    if value >= 100000000:
        rounded = value / 100000000
        return f"{rounded:.1f}亿".replace(".0亿", "亿")
    if value >= 10000:
        return f"{value / 10000:.0f}万"
    return str(int(value))


def apply_condition_actions(overrides: Any, actions: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Apply deterministic UI actions (chip removal / clear-all) to overrides.

    Returns the new overrides plus a Chinese description for the system reply.
    """
    merged = _normalized_overrides(overrides)
    parts: list[str] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        op = str(action.get("op") or "").strip()
        if op == "clear_all":
            merged = _normalized_overrides(None)
            parts = ["恢复默认条件"]
            break
        if op == "remove_field":
            field = str(action.get("field") or "").strip()
            if field not in OVERRIDE_FIELD_KINDS:
                continue
            merged["fields"].pop(field, None)
            if field in merged["removed_fields"]:
                merged["removed_fields"].remove(field)
            if field == "excluded_industries_json":
                merged["extra_excluded_industries"] = []
            parts.append(f"移除{FIELD_LABELS.get(field, field)}")
        elif op == "remove_preference":
            value = str(action.get("value") or "").strip()
            if value in merged["semantic_preferences"]:
                merged["semantic_preferences"].remove(value)
                parts.append("移除偏好")
    return merged, "、".join(parts)


def persist_session_overrides(db: Session, session_id: Any, overrides: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set condition_overrides_json = :overrides,
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("overrides", type_=JSONB)),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "overrides": overrides,
        },
    )
