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
from backend.app.registry.indicators import (
    multi_value_enum_values,
    seller_target_fact_columns,
    writable_columns,
    writable_enum_values,
)
from backend.app.services.field_writer import WriteProvenance, write_seller_target_fields
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    industry_l2_prompt_list,
    normalize_industry_pairs,
    normalize_l2_values,
    resolve_l1,
)
from backend.app.services.seller_target_status import mark_parse_completed

from backend.app.jobs.handlers.common import (
    SELLER_TARGET_POST_PARSE_STATUSES,
    _get_default_node_config,
    _join_lines,
    _json_safe_dict,
    _normalize_allowed_enum,
    _normalize_closed_list_values,
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
    normalization_notes.extend(_normalize_seller_target_industry_changes(db, changes, parsed_output_json))
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
    mark_parse_completed(
        db,
        seller_target_id=seller_target_id,
        actor_user_id=SYSTEM_USER_ID,
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
    # 事实列来自注册表，不是外部输入，可以安全拼接（同 common._fetch_seller_targets）。
    row = db.execute(
        text(
            f"""
            select
              id, {", ".join(seller_target_fact_columns())}
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

SELLER_TARGET_PARSE_FIELDS = writable_columns("parse")

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

SELLER_TARGET_PARSE_ENUM_FIELDS = writable_enum_values()

SELLER_TARGET_CLOSED_LIST_FIELDS = set(multi_value_enum_values())

SELLER_TARGET_TEXT_LIMITS = {
    "target_name": 300,
    "target_subject_name": 300,
    "valuation_date": 80,
    "asking_price_date": 80,
    # business_summary is a short AI-written profile shown in list rows; cap it
    # so a model that echoes raw source material cannot flood the UI.
    "business_summary": 300,
    # 主要产品是产品线枚举而不是又一段业务描述——给足空间列全，但不能变成
    # business_summary 的副本。
    "main_products_text": 400,
    "stock_code": 40,
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
    # Prompt versions are edited at runtime. Accept legacy HQ/registration
    # keys while production prompts are moved to the single location model;
    # only the new canonical columns proceed to the writer.
    candidate = dict(candidate)
    if "location_province" not in candidate:
        legacy_province = candidate.get("headquarter_province") or candidate.get("registered_province")
        if legacy_province:
            candidate["location_province"] = legacy_province
    if "location_city" not in candidate:
        legacy_city = candidate.get("headquarter_city") or candidate.get("registered_city")
        if legacy_city:
            candidate["location_city"] = legacy_city
    if "industry_pairs_json" not in candidate:
        legacy_pair = {
            "l1": candidate.get("industry_l1") or candidate.get("industry_primary"),
            "l2": candidate.get("industry_l2") or candidate.get("industry_secondary"),
        }
        if legacy_pair["l1"] or legacy_pair["l2"]:
            candidate["industry_pairs_json"] = [legacy_pair]
    # They are normalization inputs only. The canonical writer receives the
    # paired representation so L2 parentage can never be lost.
    candidate.pop("industry_l1", None)
    candidate.pop("industry_l2", None)

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
        # 闭集多值列先于标量枚举判断：它们也在 ENUM_FIELDS 里（同样声明了
        # enum_options），但值是数组，走标量分支会被整条丢掉。
        if key in SELLER_TARGET_CLOSED_LIST_FIELDS:
            normalized_values = _normalize_closed_list_values(key, value)
            if normalized_values:
                changes[key] = normalized_values
            else:
                notes.append(f"dropped_{key}:no_recognised_values")
            continue
        if key in SELLER_TARGET_PARSE_ENUM_FIELDS:
            changes[key] = _normalize_allowed_enum(value, SELLER_TARGET_PARSE_ENUM_FIELDS[key])
            continue
        if key == "industry_pairs_json":
            changes[key] = value
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
    changes = _seller_target_changes_with_parse_completion(seller_target, changes)
    return write_seller_target_fields(
        db,
        UUID(str(seller_target["id"])),
        changes,
        provenance=WriteProvenance(
            source_type="seller_target_parse",
            actor_user_id=SYSTEM_USER_ID,
            writer="parse",
            source_id=job_id,
            evidence_id=source_context.get("evidence_id"),
            field_source_label=source_context.get("source_label"),
            review_status="auto_accepted",
            source_context=source_context,
            log_metadata={
                "source": "seller_target_parser",
                "normalization_notes": normalization_notes,
                "field_value_source": source_context,
            },
        ),
        search_doc_source="seller_target_parse",
    )

def _seller_target_changes_with_parse_completion(
    seller_target: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Keep the field-write diff free of transient parse state.

    The handler calls ``mark_parse_completed`` after writing facts. If
    ``information_status`` were included here, withdrawing the fact batch
    would also roll the target back into ``parsing`` with no job behind it.
    """
    return dict(changes)

def _normalize_seller_target_industry_changes(
    db: Session,
    changes: dict[str, Any],
    parsed_output_json: dict[str, Any] | None = None,
) -> list[str]:
    """Normalize current and legacy parser outputs into canonical pairs."""
    raw_fields = (parsed_output_json or {}).get("fields", parsed_output_json or {})
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    values = changes.get("industry_pairs_json")
    if not values:
        values = [{
            "l1": raw_fields.get("industry_l1") or raw_fields.get("industry_primary"),
            "l2": raw_fields.get("industry_l2") or raw_fields.get("industry_secondary"),
        }]
    pairs, notes = normalize_industry_pairs(db, values)
    if pairs:
        changes["industry_pairs_json"] = pairs
    else:
        changes.pop("industry_pairs_json", None)
    changes.pop("industry_l1", None)
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
    information_status = "normal"
    completion_reason = "business_update_parsed_without_field_changes"
    result = db.execute(
        text(
            """
            update seller_target
            set information_status = :information_status,
                last_parse_at = now(),
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
            "information_status": information_status,
            "updated_by": SYSTEM_USER_ID,
            "metadata_patch": {
                "last_parse_completed_job_id": str(job_id),
                "last_parse_completed_reason": completion_reason,
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
                last_parse_at = now(),
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
