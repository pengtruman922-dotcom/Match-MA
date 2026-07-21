from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.queue import JobClaim
from backend.app.services.search_docs import (
    create_search_doc_rebuild_job,
)
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    industry_l2_prompt_list,
    normalize_excluded_terms,
    normalize_l2_values,
    normalize_l1_values,
    resolve_l1,
)

from backend.app.jobs.handlers.common import (
    CLOSED_LIST_FIELD_VALUES,
    REQUIREMENT_STRENGTH_FIELDS,
    YES_NO_LIKE_FIELDS,
    _diff_json_safe,
    _get_default_node_config,
    _json_safe_dict,
    _json_safe_value,
    _normalize_closed_list_values,
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_listing_market_region,
    _normalize_requirement_strength,
    _normalize_yes_no_like,
    _optional_decimal,
    _parse_source_context,
    _render_prompt_messages,
    _resolve_entity_id,
    _safe_prompt_messages_for_trace,
    _write_field_value_sources,
)
from backend.app.jobs.handlers.traces import (
    _insert_buyer_intent_parse_trace,
)

def _handle_buyer_intent_parse(db: Session, job: JobClaim) -> dict[str, object]:
    buyer_intent_id = _resolve_entity_id(job, expected_entity_type="buyer_intent")
    if buyer_intent_id is None:
        raise ValueError("buyer_intent_parse job requires a buyer_intent entity_id.")

    buyer_intent = _get_buyer_intent_for_parse(db, buyer_intent_id)
    buyer_profile_json = _build_buyer_profile_context(db, buyer_intent)
    raw_requirement_text = str(job.payload_json.get("raw_requirement_text") or buyer_intent.get("raw_requirement_text") or "")
    if not raw_requirement_text.strip():
        raise ValueError("buyer_intent_parse job requires raw_requirement_text.")

    node_config = _get_default_node_config(db, "buyer_intent_parser")
    prompt_messages = _render_prompt_messages(
        node_config,
        {
            "raw_requirement_text": raw_requirement_text,
            "buyer_profile_json": buyer_profile_json,
            "industry_l1_list": industry_l1_prompt_list(db),
            "industry_l2_list": industry_l2_prompt_list(db),
        },
    )
    input_json = {
        "buyer_intent_id": str(buyer_intent_id),
        "raw_requirement_text": raw_requirement_text,
        "buyer_profile_json": buyer_profile_json,
    }

    started = time.perf_counter()
    try:
        llm_result = call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            api_key_encrypted=node_config.get("api_key_encrypted"),
            model_name=node_config["model_name"],
            messages=prompt_messages,
            temperature=node_config["temperature"],
            top_p=node_config["top_p"],
            max_tokens=node_config["max_tokens"],
            timeout_seconds=node_config["timeout_seconds"] or 90,
            response_format=node_config["response_format"],
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_buyer_intent_parse_trace(
            db,
            job=job,
            buyer_intent_id=buyer_intent_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
            raw_output_text=None,
            parsed_output_json=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=latency_ms,
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        db.commit()
        raise

    parsed_output_json = llm_result.parsed_output_json
    schema_validation_json = _validate_buyer_intent_parse_output(parsed_output_json)
    changes, normalization_notes = _normalize_buyer_intent_parse_changes(parsed_output_json, raw_requirement_text)
    normalization_notes.extend(_normalize_buyer_intent_industry_changes(db, changes))
    _insert_buyer_intent_parse_trace(
        db,
        job=job,
        buyer_intent_id=buyer_intent_id,
        node_config=node_config,
        status="succeeded" if schema_validation_json["valid"] else "failed",
        input_json=input_json,
        prompt_messages_json=prompt_messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=parsed_output_json,
        schema_validation_json=schema_validation_json,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
        error_code=None if schema_validation_json["valid"] else "schema_validation_failed",
        error_message=schema_validation_json.get("error"),
    )
    db.commit()
    if not schema_validation_json["valid"]:
        raise ValueError(schema_validation_json.get("error") or "Buyer intent parser output is invalid.")

    source_context = _parse_source_context(
        job,
        default_source_type="buyer_intent_parse",
        default_source_label="Buyer intent parser",
    )

    applied_fields: list[str] = []
    if changes:
        applied_fields = _apply_buyer_intent_parse_changes(
            db,
            buyer_intent,
            changes,
            job.id,
            normalization_notes,
            source_context,
        )

    return {
        "handled": True,
        "job_type": job.job_type,
        "buyer_intent_id": str(buyer_intent_id),
        "applied_fields": applied_fields,
        "field_count": len(applied_fields),
        "applied_buyer_party_fields": [],
        "buyer_party_field_count": 0,
        "trace_created": True,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "schema_valid": schema_validation_json["valid"],
    }

def _get_buyer_intent_for_parse(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, pause_reason, contact_name,
              contact_info_json, raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, industries_json,
              excluded_industries_json, industry_l2_json, industry_focus_tags_json,
              region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_ps, min_net_margin, min_gross_margin,
              min_valuation_yuan, max_valuation_yuan, market_cap_range_summary,
              min_market_cap_yuan, max_market_cap_yuan, budget_min_yuan, budget_max_yuan,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, listing_board_requirement_summary, listing_market_region,
              acceptable_cash_flow_status_json, acceptable_profitability_status_json,
              requires_relocation, relocation_target_regions_json,
              requires_return_investment, return_investment_multiple,
              requires_team_retention, earnout_requirement,
              financing_stage_requirement_summary, transaction_type, transaction_types_json,
              premium_tolerance_summary, max_premium_rate, max_debt_ratio,
              debt_ratio_requirement_summary, major_risk_tolerance_summary,
              buyer_industry_advantage_summary, negative_summary,
              priority_summary, preference_summary, unknown_summary
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Buyer intent not found: {buyer_intent_id}")
    return _json_safe_dict(row)

def _get_buyer_party(db: Session, buyer_party_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, buyer_name, legal_name, aliases_json, buyer_type, group_name,
              listed_status, region_province, region_city, main_business,
              capital_strength_summary, profile_summary, status
            from buyer_party
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return _json_safe_dict(row) if row else None

def _build_buyer_profile_context(db: Session, buyer_intent: dict[str, Any]) -> dict[str, Any]:
    buyer_party = None
    if buyer_intent.get("buyer_party_id"):
        buyer_party = _get_buyer_party(db, UUID(str(buyer_intent["buyer_party_id"])))
    return {
        "buyer_party": buyer_party,
        "current_intent": buyer_intent,
        "instructions": {
            "apply_policy": "Parser output is automatically applied to the bound buyer_intent and remains reviewable in update logs.",
            "money_unit": "Use CNY yuan numbers.",
            "percentage_unit": "Use numeric percentage values, e.g. 51 means 51 percent.",
        },
    }

BUYER_INTENT_PARSE_FIELDS = {
    "intent_name",
    "raw_requirement_text",
    "intent_summary",
    "parsed_requirement_json",
    "industry_primary",
    "industry_secondary",
    "industries_json",
    "industry_l2_json",
    "excluded_industries_json",
    "industry_focus_tags_json",
    "region_scope_summary",
    "region_constraints_json",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_pe",
    "max_ps",
    "min_net_margin",
    "min_gross_margin",
    "min_valuation_yuan",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "market_cap_range_summary",
    "budget_min_yuan",
    "budget_max_yuan",
    "acceptable_cash_flow_status_json",
    "acceptable_profitability_status_json",
    "requires_relocation",
    "relocation_target_regions_json",
    "requires_return_investment",
    "return_investment_multiple",
    "requires_team_retention",
    "earnout_requirement",
    "listing_market_region",
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
    "equity_ratio_summary",
    "equity_requirement_type",
    "acceptable_control_paths_json",
    "preferred_listed_status",
    "listing_board_requirement_summary",
    "financing_stage_requirement_summary",
    "transaction_type",
    "transaction_types_json",
    "premium_tolerance_summary",
    "max_premium_rate",
    "max_debt_ratio",
    "debt_ratio_requirement_summary",
    "major_risk_tolerance_summary",
    "buyer_industry_advantage_summary",
    "negative_summary",
    "priority_summary",
    "preference_summary",
    "unknown_summary",
}

BUYER_INTENT_PARSE_JSON_FIELDS = {
    "parsed_requirement_json",
    "region_constraints_json",
    "acceptable_control_paths_json",
    "transaction_types_json",
    "industries_json",
    "industry_l2_json",
    "excluded_industries_json",
    "industry_focus_tags_json",
    "acceptable_cash_flow_status_json",
    "acceptable_profitability_status_json",
    "relocation_target_regions_json",
}

BUYER_INTENT_PARSE_NUMERIC_FIELDS = {
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_pe",
    "max_ps",
    "min_net_margin",
    "min_gross_margin",
    "min_valuation_yuan",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "max_premium_rate",
    "max_debt_ratio",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
    "budget_min_yuan",
    "budget_max_yuan",
    "return_investment_multiple",
}

BUYER_INTENT_TEXT_LIMITS = {
    "intent_name": 300,
}

BUYER_PARTY_PARSE_FIELDS = {
    "buyer_type",
    "group_name",
    "listed_status",
    "region_province",
    "region_city",
    "main_business",
    "capital_strength_summary",
    "profile_summary",
}

BUYER_PARTY_PARSE_TEXT_LIMITS = {
    "buyer_type": 80,
    "group_name": 200,
    "region_province": 80,
    "region_city": 80,
    "main_business": 2000,
    "capital_strength_summary": 2000,
    "profile_summary": 2000,
}

BUYER_PARTY_TYPE_VALUES = {
    "industrial_buyer",
    "listed_company",
    "state_owned_platform",
    "pe_fund",
    "financial_investor",
    "government_platform",
    "other",
}

BUYER_PARTY_TYPE_ALIASES = {
    "strategic": "industrial_buyer",
    "strategic_buyer": "industrial_buyer",
    "strategic_investor": "industrial_buyer",
    "industrial": "industrial_buyer",
    "industry": "industrial_buyer",
    "corporate": "industrial_buyer",
    "corporate_buyer": "industrial_buyer",
    "private": "industrial_buyer",
    "private_company": "industrial_buyer",
    "listed": "listed_company",
    "public_company": "listed_company",
    "上市公司": "listed_company",
    "state_owned": "state_owned_platform",
    "state_owned_enterprise": "state_owned_platform",
    "soe": "state_owned_platform",
    "国资": "state_owned_platform",
    "国资平台": "state_owned_platform",
    "pe": "pe_fund",
    "private_equity": "pe_fund",
    "pe基金": "pe_fund",
    "fund": "financial_investor",
    "financial": "financial_investor",
    "financial_investor": "financial_investor",
    "government": "government_platform",
    "government_platform": "government_platform",
    "政府平台": "government_platform",
    "other": "other",
}

def _validate_buyer_intent_parse_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if parsed_output_json is None:
        return {"valid": False, "error": "LLM output is not a JSON object."}
    if "fields" in parsed_output_json and not isinstance(parsed_output_json["fields"], dict):
        return {"valid": False, "error": "Buyer intent parser output field 'fields' must be an object."}
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {"valid": False, "error": "Buyer intent parser output must be an object."}
    allowed_count = len([key for key in candidate if key in BUYER_INTENT_PARSE_FIELDS])
    party = parsed_output_json.get("buyer_party")
    if isinstance(party, dict):
        allowed_count += len([key for key in party if key in BUYER_PARTY_PARSE_FIELDS])
    return {
        "valid": allowed_count > 0,
        "field_count": allowed_count,
        "error": None if allowed_count > 0 else "Buyer intent parser output has no supported fields.",
    }

def _normalize_buyer_intent_parse_changes(
    parsed_output_json: dict[str, Any] | None,
    raw_requirement_text: str,
) -> tuple[dict[str, Any], list[str]]:
    if not parsed_output_json:
        return {}, []
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {}, []

    notes: list[str] = []
    changes: dict[str, Any] = {}
    for key, value in candidate.items():
        if key not in BUYER_INTENT_PARSE_FIELDS:
            notes.append(f"ignored_unsupported_field:{key}")
            continue
        if key in BUYER_INTENT_PARSE_NUMERIC_FIELDS:
            changes[key] = _optional_decimal(value)
            continue
        if key in YES_NO_LIKE_FIELDS:
            changes[key] = _normalize_yes_no_like(value)
            continue
        if key == "preferred_listed_status":
            changes[key] = _normalize_listed_status(value)
            continue
        if key == "equity_requirement_type":
            changes[key] = _normalize_equity_requirement_type(value)
            continue
        if key in REQUIREMENT_STRENGTH_FIELDS:
            changes[key] = _normalize_requirement_strength(value)
            continue
        if key == "listing_market_region":
            changes[key] = _normalize_listing_market_region(value)
            continue
        if key in CLOSED_LIST_FIELD_VALUES:
            normalized_values = _normalize_closed_list_values(key, value)
            if normalized_values:
                changes[key] = normalized_values
            else:
                notes.append(f"dropped_{key}:no_recognised_values")
            continue
        if key in BUYER_INTENT_PARSE_JSON_FIELDS:
            changes[key] = value if isinstance(value, (list, dict)) else []
            continue
        text_value = str(value).strip() if value is not None else None
        if text_value and key in BUYER_INTENT_TEXT_LIMITS:
            text_value = text_value[: BUYER_INTENT_TEXT_LIMITS[key]]
        changes[key] = text_value

    source_text = raw_requirement_text.lower()
    mentions_valuation = "估值" in raw_requirement_text or "valuation" in source_text
    mentions_market_cap = "市值" in raw_requirement_text or "market cap" in source_text
    if mentions_valuation and not mentions_market_cap:
        for field in ("min_market_cap_yuan", "max_market_cap_yuan", "market_cap_range_summary"):
            if field in changes:
                changes.pop(field, None)
                notes.append(f"dropped_{field}:source_mentions_valuation_not_market_cap")

    changes["raw_requirement_text"] = raw_requirement_text
    if "parsed_requirement_json" not in changes:
        changes["parsed_requirement_json"] = {
            "source": "buyer_intent_parser",
            "raw_requirement_text": raw_requirement_text,
            "llm_fields": parsed_output_json,
        }
    return {key: value for key, value in changes.items() if value is not None}, notes

def _normalize_buyer_intent_industry_changes(db: Session, changes: dict[str, Any]) -> list[str]:
    """Map parser industry output onto the closed L1 dictionary in place."""
    notes: list[str] = []
    if "industries_json" in changes:
        normalized, industry_notes = normalize_l1_values(db, changes["industries_json"])
        notes.extend(industry_notes)
        if normalized:
            changes["industries_json"] = normalized
        else:
            changes.pop("industries_json", None)
    if "industry_l2_json" in changes:
        # L2 是筛选字段，只保留字典里真实存在的赛道；写不进字典的细分方向
        # （醋酸下游、偏光膜这类产品级说法）留给深评，不污染 SQL。
        normalized_l2, l2_notes = normalize_l2_values(db, changes["industry_l2_json"])
        notes.extend(l2_notes)
        if normalized_l2:
            changes["industry_l2_json"] = normalized_l2
        else:
            changes.pop("industry_l2_json", None)
    if "excluded_industries_json" in changes:
        cleaned = normalize_excluded_terms(changes["excluded_industries_json"])
        if cleaned:
            changes["excluded_industries_json"] = cleaned
        else:
            changes.pop("excluded_industries_json", None)
    if "industry_focus_tags_json" in changes:
        raw_tags = changes["industry_focus_tags_json"]
        tags: list[str] = []
        if isinstance(raw_tags, list):
            for value in raw_tags:
                tag = str(value or "").strip()[:80]
                if tag and tag not in tags:
                    tags.append(tag)
        if tags:
            changes["industry_focus_tags_json"] = tags
        else:
            changes.pop("industry_focus_tags_json", None)
    if "industries_json" not in changes and changes.get("industry_primary"):
        l1_name = resolve_l1(db, changes["industry_primary"])
        if l1_name:
            changes["industries_json"] = [l1_name]
    return notes

def _apply_buyer_intent_parse_changes(
    db: Session,
    buyer_intent: dict[str, Any],
    changes: dict[str, Any],
    job_id: UUID,
    normalization_notes: list[str],
    source_context: dict[str, Any],
) -> list[str]:
    diff = _diff_json_safe(buyer_intent, changes)
    if not diff:
        return []

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    statement = text(
        f"""
        update buyer_intent
        set {', '.join(set_clauses)}
        where id = :buyer_intent_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    bind_params = [bindparam(field, type_=JSONB) for field in diff if field in BUYER_INTENT_PARSE_JSON_FIELDS]
    if bind_params:
        statement = statement.bindparams(*bind_params)
    db.execute(
        statement,
        {
            **{field: changes[field] for field in diff},
            "updated_by": SYSTEM_USER_ID,
            "buyer_intent_id": buyer_intent["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _write_buyer_intent_parse_logs(db, buyer_intent, changes, diff, job_id, normalization_notes, source_context)
    _write_field_value_sources(
        db,
        entity_type="buyer_intent",
        entity_id=UUID(str(buyer_intent["id"])),
        changes=changes,
        diff=diff,
        source_context=source_context,
        review_status="auto_accepted",
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=UUID(str(buyer_intent["id"])),
        source="buyer_intent_parse",
    )
    return list(diff.keys())

def _write_buyer_intent_parse_logs(
    db: Session,
    buyer_intent: dict[str, Any],
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    job_id: UUID,
    normalization_notes: list[str],
    source_context: dict[str, Any],
) -> None:
    for field_path, (old_value, new_value) in diff.items():
        db.execute(
            text(
                """
                insert into action_application_log (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  old_value_json, new_value_json, source_type, source_id,
                  evidence_id, applied_by, edited_before_apply, metadata_json
                )
                values (
                  :team_id, :workspace_id, 'buyer_intent', :buyer_intent_id, :field_path,
                  :old_value_json, :new_value_json, 'buyer_intent_parse', :job_id,
                  :evidence_id, :applied_by, false, :metadata_json
                )
                """
            ).bindparams(
                bindparam("old_value_json", type_=JSONB),
                bindparam("new_value_json", type_=JSONB),
                bindparam("metadata_json", type_=JSONB),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "buyer_intent_id": buyer_intent["id"],
                "field_path": field_path,
                "old_value_json": _json_safe_value(old_value),
                "new_value_json": _json_safe_value(new_value),
                "job_id": job_id,
                "evidence_id": source_context.get("evidence_id"),
                "applied_by": SYSTEM_USER_ID,
                "metadata_json": {
                    "source": "buyer_intent_parser",
                    "normalization_notes": normalization_notes,
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )

def _normalize_buyer_party_parse_changes(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if not parsed_output_json:
        return {}
    candidate = parsed_output_json.get("buyer_party")
    if not isinstance(candidate, dict):
        return {}

    changes: dict[str, Any] = {}
    for key, value in candidate.items():
        if key not in BUYER_PARTY_PARSE_FIELDS:
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if key == "listed_status":
            listed_status = _normalize_listed_status(value)
            changes[key] = "unknown" if listed_status == "any" else listed_status
            continue
        if key == "buyer_type":
            changes[key] = _normalize_buyer_party_type(value)
            continue
        text_value = str(value).strip()
        limit = BUYER_PARTY_PARSE_TEXT_LIMITS.get(key)
        if limit:
            text_value = text_value[:limit]
        changes[key] = text_value
    return {key: value for key, value in changes.items() if value is not None}

def _normalize_buyer_party_type(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    if normalized in BUYER_PARTY_TYPE_VALUES:
        return normalized
    if normalized in BUYER_PARTY_TYPE_ALIASES:
        return BUYER_PARTY_TYPE_ALIASES[normalized]
    if raw in BUYER_PARTY_TYPE_ALIASES:
        return BUYER_PARTY_TYPE_ALIASES[raw]
    return "other"

def _apply_buyer_party_parse_changes(
    db: Session,
    buyer_party: dict[str, Any],
    changes: dict[str, Any],
    job_id: UUID,
    source_context: dict[str, Any],
) -> list[str]:
    # Enrich-only: fill empty buyer_party fields, never overwrite existing data.
    diff: dict[str, tuple[Any, Any]] = {}
    for field, new_value in changes.items():
        current = buyer_party.get(field)
        if current is not None and not (isinstance(current, str) and not current.strip()):
            continue
        if _json_safe_value(current) == _json_safe_value(new_value):
            continue
        diff[field] = (current, new_value)
    if not diff:
        return []

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    db.execute(
        text(
            f"""
            update buyer_party
            set {', '.join(set_clauses)}
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            **{field: changes[field] for field in diff},
            "updated_by": SYSTEM_USER_ID,
            "buyer_party_id": buyer_party["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _write_buyer_party_parse_logs(db, buyer_party, changes, diff, job_id, source_context)
    _write_field_value_sources(
        db,
        entity_type="buyer_party",
        entity_id=UUID(str(buyer_party["id"])),
        changes=changes,
        diff=diff,
        source_context=source_context,
        review_status="auto_accepted",
    )
    return list(diff.keys())

def _write_buyer_party_parse_logs(
    db: Session,
    buyer_party: dict[str, Any],
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    job_id: UUID,
    source_context: dict[str, Any],
) -> None:
    for field_path, (old_value, new_value) in diff.items():
        db.execute(
            text(
                """
                insert into action_application_log (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  old_value_json, new_value_json, source_type, source_id,
                  evidence_id, applied_by, edited_before_apply, metadata_json
                )
                values (
                  :team_id, :workspace_id, 'buyer_party', :buyer_party_id, :field_path,
                  :old_value_json, :new_value_json, 'buyer_intent_parse', :job_id,
                  :evidence_id, :applied_by, false, :metadata_json
                )
                """
            ).bindparams(
                bindparam("old_value_json", type_=JSONB),
                bindparam("new_value_json", type_=JSONB),
                bindparam("metadata_json", type_=JSONB),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "buyer_party_id": buyer_party["id"],
                "field_path": field_path,
                "old_value_json": _json_safe_value(old_value),
                "new_value_json": _json_safe_value(new_value),
                "job_id": job_id,
                "evidence_id": source_context.get("evidence_id"),
                "applied_by": SYSTEM_USER_ID,
                "metadata_json": {
                    "source": "buyer_intent_parser",
                    "enrichment": "buyer_party",
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )
