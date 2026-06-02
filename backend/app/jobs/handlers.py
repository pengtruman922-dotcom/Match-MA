from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.prompting import render_template
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.extracted_actions import (
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
)
from backend.app.jobs.queue import JobClaim

ALLOWED_ACTION_TYPES = {
    "seller_fact_update",
    "seller_event",
    "buyer_seller_relation_update",
    "buyer_intent_target_exclusion",
    "buyer_intent_update",
    "buyer_level_blacklist_suggestion",
    "internal_note",
    "unresolved_item",
}

ALLOWED_TARGET_ENTITY_TYPES = {
    "seller_target",
    "buyer_party",
    "buyer_intent",
    "buyer_seller_relation",
}

SELLER_TARGET_CHANGE_FIELDS = {
    "target_name",
    "industry_primary",
    "industry_secondary",
    "headquarter_province",
    "headquarter_city",
    "listed_status",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "valuation_yuan",
    "asking_price_yuan",
    "pe_ratio",
    "is_for_sale",
    "can_control",
    "can_consolidate",
    "accepts_minority_investment",
    "transfer_ratio_min",
    "transfer_ratio_max",
    "transfer_ratio_text",
    "transfer_flexibility_type",
    "business_summary",
    "transaction_summary",
    "risk_summary",
    "gap_summary",
    "information_status",
    "recommendation_status",
}

SELLER_TARGET_FIELD_ALIASES = {
    "summary": "business_summary",
    "target_summary": "business_summary",
    "business": "business_summary",
    "industry": "industry_secondary",
    "location": "raw_region_text",
    "province": "headquarter_province",
    "city": "headquarter_city",
    "revenue": "current_revenue_yuan",
    "profit": "current_net_profit_yuan",
    "net_profit": "current_net_profit_yuan",
    "valuation": "valuation_yuan",
    "asking_price": "asking_price_yuan",
    "pe": "pe_ratio",
    "pe_multiple": "pe_ratio",
}

BUYER_INTENT_CHANGE_FIELDS = {
    "raw_requirement_text",
    "intent_summary",
    "industry_primary",
    "industry_secondary",
    "region_scope_summary",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "max_pe",
    "max_valuation_yuan",
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
    "equity_ratio_summary",
    "equity_requirement_type",
    "preferred_listed_status",
    "transaction_type",
    "negative_summary",
    "priority_summary",
    "preference_summary",
    "unknown_summary",
    "status",
    "pause_reason",
}

BUYER_INTENT_FIELD_ALIASES = {
    "requirement": "intent_summary",
    "summary": "intent_summary",
    "region": "region_scope_summary",
    "min_profit": "min_net_profit_yuan",
    "profit_min": "min_net_profit_yuan",
    "max_valuation": "max_valuation_yuan",
    "control": "requires_control",
    "consolidation": "requires_consolidation",
}

BUYER_SELLER_RELATION_CHANGE_FIELDS = {
    "buyer_intent_id",
    "buyer_party_id",
    "seller_target_id",
    "status",
    "status_reason",
    "first_recommended_at",
    "last_contact_at",
    "last_event_at",
    "last_event_summary",
    "event_type",
    "event_title",
    "event_content",
    "next_step",
    "buyer_name",
    "seller_target_name",
    "feedback",
    "recommendation_date",
}

BUYER_SELLER_RELATION_FIELD_ALIASES = {
    "feedback": "last_event_summary",
    "recommendation_date": "first_recommended_at",
    "recommended_at": "first_recommended_at",
    "event_summary": "last_event_summary",
    "title": "event_title",
    "content": "event_content",
}

SELLER_TARGET_ENUM_FIELDS = {
    "listed_status": {"listed", "unlisted", "pre_ipo", "unknown"},
    "is_for_sale": {"yes", "no", "unknown", "likely"},
    "can_control": {"yes", "no", "unknown", "likely"},
    "can_consolidate": {"yes", "no", "unknown", "likely"},
    "accepts_minority_investment": {"yes", "no", "unknown", "likely"},
    "transfer_flexibility_type": {
        "control_available",
        "consolidation_available",
        "minority_available",
        "full_sale_available",
        "flexible",
        "specific_range",
        "unknown",
    },
    "information_status": {
        "normal",
        "insufficient",
        "pending_review",
        "parsing",
        "researching",
        "parse_failed",
    },
    "recommendation_status": {"recommendable", "not_recommendable"},
}

BUYER_INTENT_ENUM_FIELDS = {
    "status": {"active", "paused"},
    "requires_control": {"yes", "no", "unknown", "likely"},
    "requires_consolidation": {"yes", "no", "unknown", "likely"},
    "accepts_minority_investment": {"yes", "no", "unknown", "likely"},
    "equity_requirement_type": {
        "control_required",
        "consolidation_required",
        "minority_acceptable",
        "minority_only",
        "flexible",
        "specific_range",
        "unknown",
    },
    "preferred_listed_status": {"listed", "unlisted", "pre_ipo", "any", "unknown"},
}

BUYER_SELLER_RELATION_ENUM_FIELDS = {
    "status": {
        "recommended",
        "interested",
        "in_discussion",
        "due_diligence",
        "agreement",
        "deal_closed",
        "not_interested",
        "paused",
        "lost",
    },
    "event_type": {
        "recommended",
        "buyer_interested",
        "buyer_not_interested",
        "meeting",
        "call",
        "material_sent",
        "due_diligence_started",
        "agreement_discussion",
        "deal_closed",
        "paused",
        "internal_note",
        "other",
    },
}

ENUM_VALUE_ALIASES = {
    "是": "yes",
    "否": "no",
    "可": "yes",
    "不可": "no",
    "可以": "yes",
    "不可以": "no",
    "可能": "likely",
    "不确定": "unknown",
    "未知": "unknown",
    "非上市": "unlisted",
    "未上市": "unlisted",
    "上市": "listed",
    "推荐": "recommended",
    "已推荐": "recommended",
    "recommendation": "recommended",
    "interested": "interested",
    "初步感兴趣": "interested",
    "感兴趣": "interested",
    "in_talk": "in_discussion",
    "沟通中": "in_discussion",
    "初步沟通": "in_discussion",
    "推进中": "in_discussion",
    "尽调": "due_diligence",
    "due_diligence_started": "due_diligence_started",
    "不感兴趣": "not_interested",
    "暂停": "paused",
    "暂不推进": "paused",
    "失败": "lost",
    "已成交": "deal_closed",
    "推荐反馈": "other",
    "recommendation_feedback": "other",
    "recommendation_negotiation": "other",
}

NESTED_FIELD_ALIASES = {
    ("finance", "profit"): "current_net_profit_yuan",
    ("finance", "net_profit"): "current_net_profit_yuan",
    ("finance", "revenue"): "current_revenue_yuan",
    ("finance", "valuation"): "valuation_yuan",
    ("finance", "asking_price"): "asking_price_yuan",
    ("finance", "pe"): "pe_ratio",
    ("deal", "can_control"): "can_control",
    ("deal", "can_consolidate"): "can_consolidate",
    ("deal", "is_for_sale"): "is_for_sale",
    ("deal", "transfer_ratio_min"): "transfer_ratio_min",
    ("deal", "transfer_ratio_max"): "transfer_ratio_max",
    ("deal", "transfer_ratio_text"): "transfer_ratio_text",
    ("risk", "summary"): "risk_summary",
    ("risk", "risk_summary"): "risk_summary",
}


def execute_job(db: Session, job: JobClaim) -> dict[str, object]:
    if job.job_type == "business_update_extract_actions":
        return _handle_business_update_extract_actions(db, job)

    return {
        "handled": False,
        "job_type": job.job_type,
        "message": "No real job handler is implemented for this job type yet.",
    }


def _handle_business_update_extract_actions(db: Session, job: JobClaim) -> dict[str, object]:
    business_update_id = _resolve_business_update_id(job)
    if business_update_id is None:
        raise ValueError("business_update_extract_actions job requires a business_update_id.")

    business_update = _get_business_update(db, business_update_id)
    node_config = _get_default_node_config(db, "business_update_extractor")
    context_json = _build_business_update_context(db, business_update)
    prompt_messages = _render_prompt_messages(
        node_config,
        {
            "context_json": context_json,
            "raw_text": business_update["raw_text"] or "",
        },
    )
    input_json = {
        "business_update_id": str(business_update["id"]),
        "raw_text": business_update["raw_text"],
        "input_type": business_update["input_type"],
        "bound_seller_target_ids": business_update["bound_seller_target_ids_json"],
        "bound_buyer_party_ids": business_update["bound_buyer_party_ids_json"],
        "bound_buyer_intent_ids": business_update["bound_buyer_intent_ids_json"],
        "bound_recommendation_session_id": (
            str(business_update["bound_recommendation_session_id"])
            if business_update["bound_recommendation_session_id"]
            else None
        ),
        "context_json": context_json,
    }

    started = time.perf_counter()
    try:
        llm_result = call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
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
        _insert_llm_trace(
            db,
            job=job,
            business_update_id=business_update_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            prompt_messages_json=prompt_messages,
            raw_output_text=None,
            parsed_output_json=None,
            schema_validation_json={"valid": False, "error": str(exc)},
            latency_ms=latency_ms,
            error_code="llm_call_failed",
            error_message=str(exc),
        )
        _mark_business_update_failed(db, business_update_id, job.id, str(exc))
        raise

    parsed_output_json = llm_result.parsed_output_json
    schema_validation_json = _validate_extractor_output(parsed_output_json)
    actions = _normalize_actions(parsed_output_json, business_update)
    if not actions:
        actions = [_build_unresolved_action(parsed_output_json, llm_result.raw_output_text)]
    created_actions = _insert_extracted_actions(db, business_update_id, actions, job.id)
    auto_apply_results = _auto_apply_safe_actions(db, created_actions)

    _insert_llm_trace(
        db,
        job=job,
        business_update_id=business_update_id,
        node_config=node_config,
        status="succeeded",
        input_json=input_json,
        prompt_messages_json=prompt_messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=parsed_output_json,
        schema_validation_json=schema_validation_json,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
    )

    db.execute(
        text(
            """
            update business_update
            set processing_status = case
                  when :auto_applied_count > 0 and exists (
                    select 1
                    from extracted_action
                    where business_update_id = :business_update_id
                      and applied_at is null
                      and review_status in ('pending_review', 'accepted', 'auto_accepted')
                  ) then 'partially_applied'
                  when :auto_applied_count > 0 then 'applied'
                  else 'parsed'
                end,
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "auto_applied_count": len(auto_apply_results),
            "metadata_patch": {
                "last_processed_job_id": str(job.id),
                "last_processing_result": "llm_parsed",
                "last_actions_created": len(created_actions),
                "last_auto_applied_actions": len(auto_apply_results),
                "last_schema_valid": schema_validation_json["valid"],
            },
        },
    )

    return {
        "handled": True,
        "job_type": job.job_type,
        "business_update_id": str(business_update_id),
        "actions_created": len(created_actions),
        "extracted_action_ids": [str(action_id) for action_id in created_actions],
        "trace_created": True,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "schema_valid": schema_validation_json["valid"],
        "auto_applied_actions": len(auto_apply_results),
    }


def _resolve_business_update_id(job: JobClaim) -> UUID | None:
    if job.entity_type == "business_update" and job.entity_id is not None:
        return job.entity_id

    payload_value = job.payload_json.get("business_update_id")
    if not payload_value:
        return None
    return UUID(str(payload_value))


def _get_business_update(db: Session, business_update_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, raw_text, input_type, processing_status,
              bound_seller_target_ids_json, bound_buyer_party_ids_json,
              bound_buyer_intent_ids_json, bound_recommendation_session_id,
              metadata_json
            from business_update
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Business update not found: {business_update_id}")
    return dict(row)


def _get_default_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.model_name,
              node.temperature,
              node.top_p,
              node.max_tokens,
              node.timeout_seconds,
              node.response_format,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref,
              prompt.id as prompt_template_id,
              prompt.version as prompt_version,
              prompt.system_prompt,
              prompt.user_prompt_template,
              prompt.output_schema_json
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
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
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Default model node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    if not config.get("prompt_template_id"):
        raise ValueError(f"Default prompt template is not configured for node: {node_name}")
    return config


def _render_prompt_messages(
    node_config: dict[str, Any],
    variables: dict[str, Any],
) -> list[dict[str, str]]:
    system_prompt = render_template(node_config.get("system_prompt"), variables)
    user_prompt = render_template(node_config.get("user_prompt_template"), variables)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_business_update_context(db: Session, business_update: dict[str, Any]) -> dict[str, Any]:
    seller_target_ids = _uuid_list(business_update["bound_seller_target_ids_json"])
    buyer_party_ids = _uuid_list(business_update["bound_buyer_party_ids_json"])
    buyer_intent_ids = _uuid_list(business_update["bound_buyer_intent_ids_json"])
    return {
        "bound_seller_targets": _fetch_seller_targets(db, seller_target_ids),
        "bound_buyer_parties": _fetch_buyer_parties(db, buyer_party_ids),
        "bound_buyer_intents": _fetch_buyer_intents(db, buyer_intent_ids),
        "instructions": {
            "target_id_policy": (
                "Use bound object IDs only when they clearly match; otherwise null."
            ),
            "review_policy": "Safe actions are auto-applied first, then remain visible for review and rollback.",
        },
    }


def _fetch_seller_targets(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, target_name, target_type, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, listed_status,
              current_revenue_yuan, current_net_profit_yuan, valuation_yuan,
              asking_price_yuan, pe_ratio, is_for_sale, can_control,
              can_consolidate, business_summary, transaction_summary, risk_summary
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]


def _fetch_buyer_parties(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, buyer_name, legal_name, buyer_type, listed_status,
              region_province, region_city, main_business, profile_summary
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]


def _fetch_buyer_intents(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, contact_name,
              raw_requirement_text, intent_summary, industry_primary,
              industry_secondary, region_scope_summary, min_revenue_yuan,
              min_net_profit_yuan, max_pe, max_valuation_yuan,
              requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status,
              transaction_type, negative_summary, preference_summary,
              unknown_summary
            from buyer_intent
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]


def _uuid_list(values: Any) -> list[UUID]:
    if not isinstance(values, list):
        return []
    uuids: list[UUID] = []
    for value in values:
        try:
            uuids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return uuids


def _json_safe_dict(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, Decimal):
            result[key] = float(value)
        else:
            result[key] = value
    return result


def _validate_extractor_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if parsed_output_json is None:
        return {"valid": False, "error": "LLM output is not a JSON object."}
    actions = parsed_output_json.get("actions")
    if not isinstance(actions, list):
        return {"valid": False, "error": "LLM output must contain actions array."}
    invalid_indexes: list[int] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            invalid_indexes.append(index)
            continue
        if action.get("action_type") not in ALLOWED_ACTION_TYPES:
            invalid_indexes.append(index)
            continue
        if not isinstance(action.get("proposed_changes_json"), dict):
            invalid_indexes.append(index)
    return {
        "valid": len(invalid_indexes) == 0,
        "action_count": len(actions),
        "invalid_indexes": invalid_indexes,
        "error": "Some actions are invalid." if invalid_indexes else None,
    }


def _normalize_actions(
    parsed_output_json: dict[str, Any] | None,
    business_update: dict[str, Any],
) -> list[dict[str, Any]]:
    if not parsed_output_json or not isinstance(parsed_output_json.get("actions"), list):
        return []

    normalized: list[dict[str, Any]] = []
    for action in parsed_output_json["actions"]:
        if not isinstance(action, dict):
            continue
        action_type = action.get("action_type")
        if action_type not in ALLOWED_ACTION_TYPES:
            continue
        proposed_changes = action.get("proposed_changes_json")
        if not isinstance(proposed_changes, dict):
            continue
        target_entity_type = action.get("target_entity_type")
        if target_entity_type not in ALLOWED_TARGET_ENTITY_TYPES:
            target_entity_type = None
        target_entity_id = _optional_uuid(action.get("target_entity_id"))
        normalized_changes, normalization_notes = _normalize_proposed_changes(
            action_type,
            proposed_changes,
        )
        if action_type in {"buyer_seller_relation_update", "buyer_intent_target_exclusion"}:
            relation_context_changes, relation_context_notes = _relation_context_changes(
                business_update,
            )
            normalized_changes = {**relation_context_changes, **normalized_changes}
            normalization_notes.extend(relation_context_notes)
        target_entity_type, target_entity_id, binding_notes = _normalize_action_target(
            action_type,
            target_entity_type,
            target_entity_id,
            business_update,
        )
        normalization_notes.extend(binding_notes)
        normalized.append(
            {
                "action_type": action_type,
                "target_entity_type": target_entity_type,
                "target_entity_id": target_entity_id,
                "proposed_changes_json": normalized_changes,
                "raw_evidence_text": action.get("raw_evidence_text"),
                "confidence": _optional_decimal(action.get("confidence")),
                "reason": action.get("reason"),
                "raw_action": action,
                "normalization_notes": normalization_notes,
            }
        )
    return normalized


def _normalize_proposed_changes(
    action_type: str,
    proposed_changes: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if action_type == "seller_fact_update":
        return _normalize_change_fields(
            proposed_changes,
            allowed_fields=SELLER_TARGET_CHANGE_FIELDS,
            aliases=SELLER_TARGET_FIELD_ALIASES,
            nested_aliases=NESTED_FIELD_ALIASES,
            enum_fields=SELLER_TARGET_ENUM_FIELDS,
        )
    if action_type == "buyer_intent_update":
        return _normalize_change_fields(
            proposed_changes,
            allowed_fields=BUYER_INTENT_CHANGE_FIELDS,
            aliases=BUYER_INTENT_FIELD_ALIASES,
            enum_fields=BUYER_INTENT_ENUM_FIELDS,
        )
    if action_type == "buyer_seller_relation_update":
        return _normalize_change_fields(
            proposed_changes,
            allowed_fields=BUYER_SELLER_RELATION_CHANGE_FIELDS,
            aliases=BUYER_SELLER_RELATION_FIELD_ALIASES,
            enum_fields=BUYER_SELLER_RELATION_ENUM_FIELDS,
        )
    return proposed_changes, []


def _normalize_change_fields(
    proposed_changes: dict[str, Any],
    *,
    allowed_fields: set[str],
    aliases: dict[str, str],
    nested_aliases: dict[tuple[str, str], str] | None = None,
    enum_fields: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    notes: list[str] = []

    for key, value in proposed_changes.items():
        if key in allowed_fields:
            normalized[key] = _normalize_field_value(key, value, enum_fields, notes)
            continue

        alias = aliases.get(key)
        if alias and alias in allowed_fields:
            normalized[alias] = _normalize_field_value(alias, value, enum_fields, notes)
            notes.append(f"{key}->{alias}")
            continue

        if isinstance(value, dict) and nested_aliases:
            for child_key, child_value in value.items():
                nested_alias = nested_aliases.get((key, child_key))
                if nested_alias and nested_alias in allowed_fields:
                    normalized[nested_alias] = _normalize_field_value(
                        nested_alias,
                        child_value,
                        enum_fields,
                        notes,
                    )
                    notes.append(f"{key}.{child_key}->{nested_alias}")

    return normalized, notes


def _normalize_field_value(
    field: str,
    value: Any,
    enum_fields: dict[str, set[str]] | None,
    notes: list[str],
) -> Any:
    if not enum_fields or field not in enum_fields:
        return value

    normalized = _normalize_enum_value(value)
    allowed_values = enum_fields[field]
    if normalized in allowed_values:
        if normalized != value:
            notes.append(f"{field}:{value}->{normalized}")
        return normalized

    notes.append(f"{field}:{value}->dropped_invalid_enum")
    return value


def _normalize_enum_value(value: Any) -> str:
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return ENUM_VALUE_ALIASES.get(normalized, ENUM_VALUE_ALIASES.get(str(value).strip(), normalized))


def _normalize_action_target(
    action_type: str,
    target_entity_type: str | None,
    target_entity_id: UUID | None,
    business_update: dict[str, Any],
) -> tuple[str | None, UUID | None, list[str]]:
    if target_entity_id is not None:
        return target_entity_type, target_entity_id, []

    if action_type == "seller_fact_update":
        bound_ids = _uuid_list(business_update["bound_seller_target_ids_json"])
        if len(bound_ids) == 1:
            return "seller_target", bound_ids[0], ["target_entity_id<-single_bound_seller_target"]

    if action_type == "buyer_intent_update":
        bound_ids = _uuid_list(business_update["bound_buyer_intent_ids_json"])
        if len(bound_ids) == 1:
            return "buyer_intent", bound_ids[0], ["target_entity_id<-single_bound_buyer_intent"]

    if action_type == "buyer_seller_relation_update":
        return "buyer_seller_relation", target_entity_id, []

    return target_entity_type, target_entity_id, []


def _relation_context_changes(business_update: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    changes: dict[str, Any] = {}
    notes: list[str] = []

    seller_target_ids = _uuid_list(business_update["bound_seller_target_ids_json"])
    if len(seller_target_ids) == 1:
        changes["seller_target_id"] = str(seller_target_ids[0])
        notes.append("seller_target_id<-single_bound_seller_target")

    buyer_intent_ids = _uuid_list(business_update["bound_buyer_intent_ids_json"])
    if len(buyer_intent_ids) == 1:
        changes["buyer_intent_id"] = str(buyer_intent_ids[0])
        notes.append("buyer_intent_id<-single_bound_buyer_intent")

    buyer_party_ids = _uuid_list(business_update["bound_buyer_party_ids_json"])
    if len(buyer_party_ids) == 1:
        changes["buyer_party_id"] = str(buyer_party_ids[0])
        notes.append("buyer_party_id<-single_bound_buyer_party")

    return changes, notes


def _build_unresolved_action(
    parsed_output_json: dict[str, Any] | None,
    raw_output_text: str,
) -> dict[str, Any]:
    return {
        "action_type": "unresolved_item",
        "target_entity_type": None,
        "target_entity_id": None,
        "proposed_changes_json": {
            "issue": "LLM output did not contain any valid extracted_action.",
            "parsed_output_json": parsed_output_json,
        },
        "raw_evidence_text": raw_output_text[:2000],
        "confidence": Decimal("0"),
        "reason": "Fallback action for debugging invalid or unusable LLM output.",
        "raw_action": parsed_output_json,
    }


def _insert_extracted_actions(
    db: Session,
    business_update_id: UUID,
    actions: list[dict[str, Any]],
    job_id: UUID,
) -> list[UUID]:
    action_ids: list[UUID] = []
    for action in actions:
        row = db.execute(
            text(
                """
                insert into extracted_action (
                  team_id, workspace_id, business_update_id,
                  action_type, target_entity_type, target_entity_id,
                  proposed_changes_json, raw_evidence_text, confidence,
                  review_status, metadata_json
                )
                values (
                  :team_id, :workspace_id, :business_update_id,
                  :action_type, :target_entity_type, :target_entity_id,
                  :proposed_changes_json, :raw_evidence_text, :confidence,
                  'pending_review', :metadata_json
                )
                returning id
                """
            ).bindparams(
                bindparam("proposed_changes_json", type_=JSONB),
                bindparam("metadata_json", type_=JSONB),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "business_update_id": business_update_id,
                "action_type": action["action_type"],
                "target_entity_type": action["target_entity_type"],
                "target_entity_id": action["target_entity_id"],
                "proposed_changes_json": action["proposed_changes_json"],
                "raw_evidence_text": action["raw_evidence_text"],
                "confidence": action["confidence"],
                "metadata_json": {
                    "source": "business_update_extractor",
                    "job_id": str(job_id),
                    "reason": action.get("reason"),
                    "raw_action": action.get("raw_action"),
                    "normalization_notes": action.get("normalization_notes", []),
                },
            },
        ).mappings().one()
        action_ids.append(row["id"])
    return action_ids


def _auto_apply_safe_actions(db: Session, action_ids: list[UUID]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for action_id in action_ids:
        action = _get_extracted_action_for_auto_apply(db, action_id)
        if not action or not _is_safe_auto_apply_action(action):
            continue
        result = _apply_auto_action(db, action)
        if result:
            results.append(result)
    return results


def _get_extracted_action_for_auto_apply(db: Session, action_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select
              id, business_update_id, action_type, target_entity_type, target_entity_id,
              proposed_changes_json, raw_evidence_text, confidence, review_status,
              reviewed_by, reviewed_at::text as reviewed_at, applied_at::text as applied_at,
              metadata_json, created_at::text as created_at
            from extracted_action
            where id = :action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "action_id": action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None


def _apply_auto_action(db: Session, action: dict[str, Any]) -> dict[str, Any] | None:
    if action["action_type"] == "seller_fact_update":
        return apply_seller_fact_update_action(db, action, require_accepted=False)
    if action["action_type"] == "buyer_intent_update":
        return apply_buyer_intent_update_action(db, action, require_accepted=False)
    if action["action_type"] == "buyer_seller_relation_update":
        return apply_buyer_seller_relation_update_action(db, action, require_accepted=False)
    if action["action_type"] == "buyer_intent_target_exclusion":
        return apply_buyer_intent_target_exclusion_action(db, action, require_accepted=False)
    return None


def _is_safe_auto_apply_action(action: dict[str, Any]) -> bool:
    if action["applied_at"] is not None:
        return False
    if action["review_status"] != "pending_review":
        return False
    if not action["proposed_changes_json"]:
        return False

    if action["action_type"] == "seller_fact_update":
        return action["target_entity_type"] == "seller_target" and action["target_entity_id"] is not None

    if action["action_type"] == "buyer_intent_update":
        return action["target_entity_type"] == "buyer_intent" and action["target_entity_id"] is not None

    if action["action_type"] == "buyer_seller_relation_update":
        changes = action["proposed_changes_json"]
        return bool(changes.get("buyer_intent_id") and changes.get("seller_target_id"))

    if action["action_type"] == "buyer_intent_target_exclusion":
        changes = action["proposed_changes_json"]
        return bool((changes.get("buyer_intent_id") or action["target_entity_id"]) and changes.get("seller_target_id"))

    return False


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _mark_business_update_failed(
    db: Session,
    business_update_id: UUID,
    job_id: UUID,
    error_message: str,
) -> None:
    db.execute(
        text(
            """
            update business_update
            set processing_status = 'failed',
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_processed_job_id": str(job_id),
                "last_processing_result": "failed",
                "last_error_message": error_message,
            },
        },
    )


def _insert_llm_trace(
    db: Session,
    *,
    job: JobClaim,
    business_update_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    schema_validation_json: dict[str, Any],
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id, prompt_template_id,
              provider_name, model_name, prompt_version, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, output_schema_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at,
              metadata_json
            )
            values (
              :team_id, :workspace_id, 'llm', 'business_update_extractor',
              :job_id, :correlation_id, 'business_update', :business_update_id,
              :provider_config_id, :node_config_id, :prompt_template_id,
              :provider_name, :model_name, :prompt_version, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :output_schema_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(),
              :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("output_schema_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "business_update_id": business_update_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "prompt_template_id": node_config["prompt_template_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
            "status": status,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json,
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "output_schema_json": node_config["output_schema_json"] or {},
            "schema_validation_json": schema_validation_json,
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "business_update_extractor"},
        },
    )
