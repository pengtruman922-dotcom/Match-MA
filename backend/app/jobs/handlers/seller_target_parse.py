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
    normalize_l2_values,
    resolve_l1,
)

from backend.app.jobs.handlers.common import (
    SELLER_TARGET_POST_PARSE_STATUSES,
    _diff_json_safe,
    _get_default_node_config,
    _join_lines,
    _json_safe_dict,
    _json_safe_value,
    _normalize_allowed_enum,
    _normalize_seller_listed_status,
    _normalize_yes_no_like,
    _optional_decimal,
    _optional_uuid,
    _parse_source_context,
    _render_prompt_messages,
    _resolve_entity_id,
    _safe_prompt_messages_for_trace,
    _truncate_text,
    _uuid_list,
    _write_field_value_sources,
)
from backend.app.jobs.handlers.traces import (
    _insert_seller_target_parse_trace,
)

SELLER_TARGET_PARSE_FAILURE_STATUSES = {"parsing"}

def _handle_seller_target_parse(db: Session, job: JobClaim) -> dict[str, object]:
    seller_target_id = _resolve_entity_id(job, expected_entity_type="seller_target")
    if seller_target_id is None:
        raise ValueError("seller_target_parse job requires a seller_target entity_id.")

    seller_target = _get_seller_target_for_parse(db, seller_target_id)
    raw_target_text = str(job.payload_json.get("raw_target_text") or _seller_target_parse_fallback_text(seller_target))
    if not raw_target_text.strip():
        raise ValueError("seller_target_parse job requires raw_target_text.")

    node_config = _get_default_node_config(db, "seller_target_parser")
    target_context_json = _build_seller_target_parse_context(seller_target)
    prompt_messages = _render_prompt_messages(
        node_config,
        {
            "raw_target_text": raw_target_text,
            "target_context_json": target_context_json,
            "industry_l1_list": industry_l1_prompt_list(db),
            "industry_l2_list": industry_l2_prompt_list(db),
        },
    )
    input_json = {
        "seller_target_id": str(seller_target_id),
        "raw_target_text": raw_target_text,
        "target_context_json": target_context_json,
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
        _insert_seller_target_parse_trace(
            db,
            job=job,
            seller_target_id=seller_target_id,
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
        _mark_seller_target_parse_failed_if_final_attempt(db, job, seller_target_id, str(exc))
        db.commit()
        raise

    parsed_output_json = llm_result.parsed_output_json
    schema_validation_json = _validate_seller_target_parse_output(parsed_output_json)
    changes, normalization_notes = _normalize_seller_target_parse_changes(parsed_output_json)
    normalization_notes.extend(_normalize_seller_target_industry_changes(db, changes))
    _insert_seller_target_parse_trace(
        db,
        job=job,
        seller_target_id=seller_target_id,
        node_config=node_config,
        status="succeeded" if schema_validation_json["valid"] else "failed",
        input_json=input_json,
        prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
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
        _mark_seller_target_parse_failed_if_final_attempt(
            db,
            job,
            seller_target_id,
            schema_validation_json.get("error") or "Seller target parser output is invalid.",
        )
        db.commit()
        raise ValueError(schema_validation_json.get("error") or "Seller target parser output is invalid.")

    applied_fields: list[str] = []
    if changes:
        applied_fields = _apply_seller_target_parse_changes(
            db,
            seller_target,
            changes,
            job.id,
            normalization_notes,
            _parse_source_context(
                job,
                default_source_type="seller_target_parse",
                default_source_label="Seller target parser",
            ),
        )

    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(seller_target_id),
        "applied_fields": applied_fields,
        "field_count": len(applied_fields),
        "trace_created": True,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "schema_valid": schema_validation_json["valid"],
    }

def _get_seller_target_for_parse(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, target_type, target_subject_name, recommendation_status, information_status,
              industry_primary, industry_secondary, industry_l2, registered_country,
              registered_province, registered_city, headquarter_province,
              headquarter_city, raw_region_text, region_granularity, listed_status,
              market_cap_yuan, current_revenue_yuan, current_net_profit_yuan,
              current_total_profit_yuan, current_assets_yuan, current_debt_ratio,
              current_operating_cash_flow_yuan, financial_period_label,
              profitability_status, cash_flow_status, operation_stability_status,
              valuation_yuan, valuation_date, asking_price_yuan, asking_price_date,
              pe_ratio, pe_source_type,
              premium_rate, is_for_sale, can_control, can_consolidate,
              accepts_minority_investment, transfer_ratio_min, transfer_ratio_max,
              transfer_ratio_text, transfer_flexibility_type, consolidation_path_summary,
              accepts_relocation, accepts_return_investment, management_team_summary,
              management_retention_possible, earnout_dependency_status,
              business_summary, transaction_summary, risk_summary, gap_summary
            from seller_target
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Seller target not found: {seller_target_id}")
    return _json_safe_dict(row)

def _build_seller_target_parse_context(seller_target: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_target": seller_target,
        "instructions": {
            "apply_policy": "Parser output is automatically applied to the bound seller_target and remains reviewable in update logs.",
            "money_unit": "Use CNY yuan numbers.",
            "percentage_unit": "Use numeric percentage values, e.g. 51 means 51 percent.",
            "region_policy": "Store actual target location fields; do not store whether it matches any buyer preference.",
        },
    }

def _seller_target_parse_fallback_text(seller_target: dict[str, Any]) -> str:
    return _join_lines(
        [
            seller_target.get("target_name"),
            seller_target.get("target_subject_name"),
            seller_target.get("business_summary"),
            seller_target.get("transaction_summary"),
            seller_target.get("risk_summary"),
            seller_target.get("gap_summary"),
        ]
    )

SELLER_TARGET_PARSE_FIELDS = {
    "target_name",
    "target_type",
    "target_subject_name",
    "industry_l1",
    "industry_l2",
    "industry_primary",
    "industry_secondary",
    "registered_province",
    "registered_city",
    "headquarter_province",
    "headquarter_city",
    "raw_region_text",
    "region_granularity",
    "listed_status",
    "market_cap_yuan",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_assets_yuan",
    "current_debt_ratio",
    "current_operating_cash_flow_yuan",
    "financial_period_label",
    "profitability_status",
    "cash_flow_status",
    "operation_stability_status",
    "valuation_yuan",
    "valuation_date",
    "asking_price_yuan",
    "asking_price_date",
    "pe_ratio",
    "pe_source_type",
    "premium_rate",
    "is_for_sale",
    "can_control",
    "can_consolidate",
    "accepts_minority_investment",
    "transfer_ratio_min",
    "transfer_ratio_max",
    "transfer_ratio_text",
    "transfer_flexibility_type",
    "consolidation_path_summary",
    "accepts_relocation",
    "accepts_return_investment",
    "management_team_summary",
    "management_retention_possible",
    "earnout_dependency_status",
    "business_summary",
    "transaction_summary",
    "risk_summary",
    "gap_summary",
    "information_status",
    "recommendation_status",
}

SELLER_TARGET_PARSE_NUMERIC_FIELDS = {
    "market_cap_yuan",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_assets_yuan",
    "current_debt_ratio",
    "current_operating_cash_flow_yuan",
    "valuation_yuan",
    "asking_price_yuan",
    "pe_ratio",
    "premium_rate",
    "transfer_ratio_min",
    "transfer_ratio_max",
}

SELLER_TARGET_YES_NO_LIKE_FIELDS = {
    "is_for_sale",
    "can_control",
    "can_consolidate",
    "accepts_minority_investment",
    "accepts_relocation",
    "accepts_return_investment",
    "management_retention_possible",
}

SELLER_TARGET_PARSE_ENUM_FIELDS = {
    "target_type": {"company", "equity_package", "business_unit", "asset_package", "project", "other"},
    "region_granularity": {"country", "province", "city", "district", "region_group", "unknown"},
    "listed_status": {"listed", "unlisted", "pre_ipo", "unknown"},
    "pe_source_type": {"user_input", "document", "calculated", "research", "unknown"},
    "profitability_status": {"profitable", "loss_making", "break_even", "unknown"},
    "cash_flow_status": {"stable_positive", "positive", "negative", "unstable", "unknown"},
    "operation_stability_status": {"stable", "unstable", "unknown", "needs_review"},
    "transfer_flexibility_type": {
        "control_available",
        "consolidation_available",
        "minority_available",
        "full_sale_available",
        "flexible",
        "specific_range",
        "unknown",
    },
    "earnout_dependency_status": {"none", "low", "medium", "high", "unknown"},
    "information_status": {"normal", "insufficient", "pending_review", "parsing", "researching", "parse_failed"},
    "recommendation_status": {"recommendable", "not_recommendable"},
}

SELLER_TARGET_TEXT_LIMITS = {
    "target_name": 300,
    "target_subject_name": 300,
    "valuation_date": 80,
    "asking_price_date": 80,
    # business_summary is a short AI-written profile shown in list rows; cap it
    # so a model that echoes raw source material cannot flood the UI.
    "business_summary": 300,
}

def _validate_seller_target_parse_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if parsed_output_json is None:
        return {"valid": False, "error": "LLM output is not a JSON object."}
    if "fields" in parsed_output_json and not isinstance(parsed_output_json["fields"], dict):
        return {"valid": False, "error": "Seller target parser output field 'fields' must be an object."}
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {"valid": False, "error": "Seller target parser output must be an object."}
    allowed_count = len([key for key in candidate if key in SELLER_TARGET_PARSE_FIELDS])
    return {
        "valid": allowed_count > 0,
        "field_count": allowed_count,
        "error": None if allowed_count > 0 else "Seller target parser output has no supported fields.",
    }

def _normalize_seller_target_parse_changes(
    parsed_output_json: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    if not parsed_output_json:
        return {}, []
    candidate = parsed_output_json.get("fields", parsed_output_json)
    if not isinstance(candidate, dict):
        return {}, []

    notes: list[str] = []
    changes: dict[str, Any] = {}
    for key, value in candidate.items():
        if key not in SELLER_TARGET_PARSE_FIELDS:
            notes.append(f"ignored_unsupported_field:{key}")
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if key in SELLER_TARGET_PARSE_NUMERIC_FIELDS:
            changes[key] = _optional_decimal(value)
            continue
        if key in SELLER_TARGET_YES_NO_LIKE_FIELDS:
            changes[key] = _normalize_yes_no_like(value)
            continue
        if key == "listed_status":
            changes[key] = _normalize_seller_listed_status(value)
            continue
        if key in SELLER_TARGET_PARSE_ENUM_FIELDS:
            changes[key] = _normalize_allowed_enum(value, SELLER_TARGET_PARSE_ENUM_FIELDS[key])
            continue
        text_value = str(value).strip() if value is not None else None
        if text_value and key in SELLER_TARGET_TEXT_LIMITS:
            text_value = text_value[: SELLER_TARGET_TEXT_LIMITS[key]]
        changes[key] = text_value

    return {key: value for key, value in changes.items() if value is not None}, notes

def _apply_seller_target_parse_changes(
    db: Session,
    seller_target: dict[str, Any],
    changes: dict[str, Any],
    job_id: UUID,
    normalization_notes: list[str],
    source_context: dict[str, Any],
) -> list[str]:
    changes = _seller_target_changes_with_post_parse_status(seller_target, changes)
    diff = _diff_json_safe(seller_target, changes)
    if not diff:
        return []

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    db.execute(
        text(
            f"""
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            **{field: changes[field] for field in diff},
            "updated_by": SYSTEM_USER_ID,
            "seller_target_id": seller_target["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    _write_seller_target_parse_logs(db, seller_target, changes, diff, job_id, normalization_notes, source_context)
    _write_field_value_sources(
        db,
        entity_type="seller_target",
        entity_id=UUID(str(seller_target["id"])),
        changes=changes,
        diff=diff,
        source_context=source_context,
        review_status="auto_accepted",
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=UUID(str(seller_target["id"])),
        source="seller_target_parse",
    )
    return list(diff.keys())

def _seller_target_changes_with_post_parse_status(
    seller_target: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    next_changes = dict(changes)
    original_information_status = seller_target.get("information_status")
    if (
        "information_status" not in next_changes
        and original_information_status in SELLER_TARGET_POST_PARSE_STATUSES
    ):
        next_changes["information_status"] = "normal"
    if (
        "recommendation_status" not in next_changes
        and seller_target.get("recommendation_status") == "not_recommendable"
        and original_information_status in SELLER_TARGET_POST_PARSE_STATUSES
    ):
        next_changes["recommendation_status"] = "recommendable"
    return next_changes

def _write_seller_target_parse_logs(
    db: Session,
    seller_target: dict[str, Any],
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
                  :team_id, :workspace_id, 'seller_target', :seller_target_id, :field_path,
                  :old_value_json, :new_value_json, 'seller_target_parse', :job_id,
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
                "seller_target_id": seller_target["id"],
                "field_path": field_path,
                "old_value_json": _json_safe_value(old_value),
                "new_value_json": _json_safe_value(new_value),
                "job_id": job_id,
                "evidence_id": source_context.get("evidence_id"),
                "applied_by": SYSTEM_USER_ID,
                "metadata_json": {
                    "source": "seller_target_parser",
                    "normalization_notes": normalization_notes,
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )

def _normalize_seller_target_industry_changes(db: Session, changes: dict[str, Any]) -> list[str]:
    """Validate industry_l1/l2 against the dictionary.

    L1 falls back to whatever industry_primary resolves to. L2 is the screening
    layer, so it is derived from the descriptive industry fields when the parser
    did not name a dictionary segment outright, and dropped when nothing maps —
    an invented segment would filter the target out of buyers who want it.
    """
    notes: list[str] = []
    value = changes.get("industry_l1")
    l1_name = resolve_l1(db, value) if value else None
    if value and l1_name is None:
        notes.append(f"industry_l1_unmapped:{str(value)[:50]}")
    if l1_name is None and changes.get("industry_primary"):
        l1_name = resolve_l1(db, changes["industry_primary"])
    if l1_name:
        changes["industry_l1"] = l1_name
    else:
        changes.pop("industry_l1", None)

    l2_candidates = [
        changes.get("industry_l2"),
        changes.get("industry_secondary"),
        changes.get("industry_primary"),
    ]
    l2_name = None
    for candidate in l2_candidates:
        if not candidate:
            continue
        resolved, _ = normalize_l2_values(db, [candidate])
        if resolved:
            l2_name = resolved[0]
            break
    if l2_name:
        changes["industry_l2"] = l2_name
    else:
        if changes.get("industry_l2"):
            notes.append(f"industry_l2_unmapped:{str(changes['industry_l2'])[:50]}")
        changes.pop("industry_l2", None)
    return notes

def _mark_seller_target_parse_failed_if_final_attempt(
    db: Session,
    job: JobClaim,
    seller_target_id: UUID,
    error_message: str,
) -> int:
    if job.attempt_count < job.max_attempts:
        return 0
    return _mark_seller_targets_parse_failed(
        db,
        seller_target_ids=[seller_target_id],
        job_id=job.id,
        error_message=error_message,
    )

def _mark_bound_seller_targets_parse_failed_if_final_attempt(
    db: Session,
    job: JobClaim,
    business_update: dict[str, Any],
    error_message: str,
) -> int:
    if job.attempt_count < job.max_attempts:
        return 0
    return _mark_seller_targets_parse_failed(
        db,
        seller_target_ids=_uuid_list(business_update.get("bound_seller_target_ids_json")),
        job_id=job.id,
        error_message=error_message,
    )

def _mark_bound_seller_targets_complete_after_business_update_parse(
    db: Session,
    business_update: dict[str, Any],
    auto_apply_results: list[dict[str, Any]],
    job_id: UUID,
) -> int:
    seller_target_ids = set(_uuid_list(business_update.get("bound_seller_target_ids_json")))
    if not seller_target_ids:
        return 0
    auto_applied_target_ids = {
        _optional_uuid(result.get("entity_id"))
        for result in auto_apply_results
        if result.get("entity_type") == "seller_target"
    }
    remaining_ids = [item for item in seller_target_ids if item not in auto_applied_target_ids]
    if not remaining_ids:
        return 0
    result = db.execute(
        text(
            """
            update seller_target
            set information_status = 'normal',
                updated_at = now(),
                updated_by = :updated_by,
                metadata_json = metadata_json || :metadata_patch
            where team_id = :team_id
              and workspace_id = :workspace_id
              and id = any(:seller_target_ids)
              and deleted_at is null
              and information_status = 'parsing'
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_ids": remaining_ids,
            "updated_by": SYSTEM_USER_ID,
            "metadata_patch": {
                "last_parse_completed_job_id": str(job_id),
                "last_parse_completed_reason": "business_update_parsed_without_field_changes",
            },
        },
    )
    return int(result.rowcount or 0)

def _mark_seller_targets_parse_failed(
    db: Session,
    *,
    seller_target_ids: list[UUID],
    job_id: UUID,
    error_message: str | None,
) -> int:
    unique_ids = list(dict.fromkeys(seller_target_ids))
    if not unique_ids:
        return 0
    result = db.execute(
        text(
            """
            update seller_target
            set information_status = 'parse_failed',
                updated_at = now(),
                updated_by = :updated_by,
                metadata_json = metadata_json || :metadata_patch
            where team_id = :team_id
              and workspace_id = :workspace_id
              and id = any(:seller_target_ids)
              and deleted_at is null
              and information_status = any(:failure_statuses)
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_ids": unique_ids,
            "failure_statuses": list(SELLER_TARGET_PARSE_FAILURE_STATUSES),
            "updated_by": SYSTEM_USER_ID,
            "metadata_patch": {
                "last_parse_failed_job_id": str(job_id),
                "last_parse_error_message": _truncate_text(error_message, 500),
            },
        },
    )
    return int(result.rowcount or 0)
