from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.handlers.buyer_intent_parse import (
    BUYER_INTENT_PARSE_JSON_FIELDS,
    BUYER_INTENT_PARSE_NUMERIC_FIELDS,
)
from backend.app.jobs.handlers.common import (
    ALLOWED_ACTION_TYPES,
    ALLOWED_TARGET_ENTITY_TYPES,
    BUYER_INTENT_CHANGE_FIELDS,
    BUYER_INTENT_ENUM_FIELDS,
    BUYER_INTENT_FIELD_ALIASES,
    BUYER_SELLER_RELATION_CHANGE_FIELDS,
    BUYER_SELLER_RELATION_ENUM_FIELDS,
    BUYER_SELLER_RELATION_FIELD_ALIASES,
    MONEY_UNIT_PATTERN,
    MONEY_YUAN_FIELDS,
    NESTED_FIELD_ALIASES,
    SELLER_TARGET_CHANGE_FIELDS,
    SELLER_TARGET_ENUM_FIELDS,
    SELLER_TARGET_FIELD_ALIASES,
    _attach_multimodal_images,
    _attachment_file_bytes,
    _decimal_ratio,
    _decimal_to_json_number,
    _fetch_buyer_intents,
    _fetch_buyer_parties,
    _fetch_seller_targets,
    _get_default_node_config,
    _json_safe_dict,
    _json_safe_value,
    _normalize_change_fields,
    _optional_decimal,
    _optional_uuid,
    _render_prompt_messages,
    _safe_prompt_messages_for_trace,
    _truncate_text,
    _uuid_list,
)
from backend.app.jobs.handlers.seller_target_parse import (
    _mark_bound_seller_targets_complete_after_business_update_parse,
    _mark_bound_seller_targets_parse_failed_if_final_attempt,
    _normalize_seller_target_industry_changes,
)
from backend.app.jobs.handlers.traces import (
    _insert_llm_trace,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.extracted_action_apply import (
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
)
from backend.app.services.image_inputs import (
    is_supported_multimodal_image,
    multimodal_image_constraints,
    prepare_image_for_multimodal,
)
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
)
from backend.app.services.profile_sections import (
    apply_profile_section,
    normalize_profile_section_items,
)


def _handle_business_update_extract_actions(db: Session, job: JobClaim) -> dict[str, object]:
    business_update_id = _resolve_business_update_id(job)
    if business_update_id is None:
        raise ValueError("business_update_extract_actions job requires a business_update_id.")

    business_update = _get_business_update(db, business_update_id)
    node_name = _business_update_parser_node_name(business_update)
    try:
        node_config = _get_default_node_config(db, node_name)
    except ValueError:
        node_config = _get_default_node_config(db, "business_update_extractor")
    attachment_context = (
        _build_business_update_attachment_context(
            db,
            business_update_id,
            trigger_attachment_id=_optional_uuid(job.payload_json.get("trigger_attachment_id")),
            trigger_evidence_id=_optional_uuid(job.payload_json.get("trigger_evidence_id")),
        )
        if job.payload_json.get("include_attachment_text", True)
        else {"attachments": [], "combined_text": "", "evidence_ids": []}
    )
    raw_text = _business_update_raw_text_with_attachments(business_update["raw_text"], attachment_context)
    business_update_for_normalization = {
        **business_update,
        "attachment_evidence_ids": attachment_context.get("evidence_ids", []),
    }
    context_json = _build_business_update_context(db, business_update)
    context_json["attachments"] = attachment_context.get("attachments", [])
    image_context = _build_business_update_image_context(
        db,
        business_update_id,
        trigger_attachment_id=_optional_uuid(job.payload_json.get("trigger_attachment_id")),
    )
    if image_context["images"]:
        context_json["image_attachments"] = image_context["summaries"]
        context_json["image_input_constraints"] = image_context["constraints"]
        business_update_for_normalization["image_evidence_attachment_ids"] = [
            item["attachment_id"] for item in image_context["summaries"]
        ]
    prompt_messages = _render_prompt_messages(
        node_config,
        {
            "context_json": context_json,
            "raw_text": raw_text,
        },
    )
    if image_context["images"]:
        prompt_messages = _attach_multimodal_images(prompt_messages, image_context["images"])
    input_json = {
        "business_update_id": str(business_update["id"]),
        "raw_text": raw_text,
        "original_raw_text": business_update["raw_text"],
        "input_type": business_update["input_type"],
        "attachment_count": len(attachment_context.get("attachments", [])),
        "image_attachment_count": len(image_context["summaries"]),
        "image_attachments": image_context["summaries"],
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
        _mark_business_update_failed_if_final_attempt(db, job, business_update_id, str(exc))
        _mark_bound_seller_targets_parse_failed_if_final_attempt(db, job, business_update, str(exc))
        db.commit()
        raise

    parsed_output_json = llm_result.parsed_output_json
    schema_validation_json = _validate_extractor_output(parsed_output_json)
    actions = _normalize_actions(parsed_output_json, business_update_for_normalization, db=db)
    actions = _attach_image_evidence_to_actions(db, job, actions, image_context["summaries"])
    schema_error = (
        schema_validation_json.get("error")
        or "Business update extractor output is invalid."
    )
    _insert_llm_trace(
        db,
        job=job,
        business_update_id=business_update_id,
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
        error_message=None if schema_validation_json["valid"] else schema_error,
    )
    if not schema_validation_json["valid"]:
        _mark_business_update_failed_if_final_attempt(db, job, business_update_id, schema_error)
        _mark_bound_seller_targets_parse_failed_if_final_attempt(
            db,
            job,
            business_update,
            schema_error,
        )
        db.commit()
        raise ValueError(schema_error)
    db.commit()

    try:
        created_actions = _insert_extracted_actions(db, business_update_id, actions, job.id)
        auto_apply_results = _auto_apply_safe_actions(db, created_actions)
        profile_sections_written = _persist_document_profile_sections(
            db,
            actions=actions,
            attachment_context=attachment_context,
            business_update_id=business_update_id,
        )
        # Actions that could not be auto-applied stay queryable on
        # extracted_action; they no longer park the target in a 待复核 state
        # that had no review UI behind it (施工单 0727).
        completed_target_count = _mark_bound_seller_targets_complete_after_business_update_parse(
            db,
            business_update,
            auto_apply_results,
            job.id,
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
                    "last_profile_sections_written": profile_sections_written,
                    "last_bound_seller_targets_completed": completed_target_count,
                    "last_schema_valid": schema_validation_json["valid"],
                },
            },
        )
    except Exception as exc:
        db.rollback()
        _mark_business_update_failed_if_final_attempt(db, job, business_update_id, str(exc))
        _mark_bound_seller_targets_parse_failed_if_final_attempt(db, job, business_update, str(exc))
        db.commit()
        raise

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
        "profile_sections_written": profile_sections_written,
        "bound_seller_targets_completed": completed_target_count,
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
              metadata_json, created_at::text as created_at
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

def _build_business_update_context(db: Session, business_update: dict[str, Any]) -> dict[str, Any]:
    seller_target_ids = _uuid_list(business_update["bound_seller_target_ids_json"])
    buyer_party_ids = _uuid_list(business_update["bound_buyer_party_ids_json"])
    buyer_intent_ids = _uuid_list(business_update["bound_buyer_intent_ids_json"])
    return {
        "bound_seller_targets": _fetch_seller_targets(db, seller_target_ids),
        "bound_buyer_parties": _fetch_buyer_parties(db, buyer_party_ids),
        "bound_buyer_intents": _fetch_buyer_intents(db, buyer_intent_ids),
        "industry_l1_list": industry_l1_prompt_list(db),
        # Reference date for resolving partial follow-up dates such as 0730.
        "update_date": str(business_update.get("created_at") or "")[:10],
        "instructions": {
            "target_id_policy": (
                "Use bound object IDs only when they clearly match; otherwise null."
            ),
            "review_policy": "Safe actions are auto-applied first, then remain visible for review and rollback.",
        },
    }

def _build_business_update_attachment_context(
    db: Session,
    business_update_id: UUID,
    *,
    trigger_attachment_id: UUID | None = None,
    trigger_evidence_id: UUID | None = None,
) -> dict[str, Any]:
    evidence_lateral_filter_sql = ""
    outer_filter_sql = ""
    if trigger_evidence_id:
        evidence_lateral_filter_sql = "and id = :trigger_evidence_id"
        outer_filter_sql = "and ev.id is not null"
    elif trigger_attachment_id:
        outer_filter_sql = "and al.attachment_id = :trigger_attachment_id"
    rows = db.execute(
        text(
            f"""
            select
              a.id as attachment_id, a.file_name, a.file_type, a.mime_type,
              a.parse_status, al.link_type,
              pd.id as parsed_document_id, pd.parse_status as parsed_document_status,
              ev.id as evidence_id, ev.text_excerpt, ev.page_no, ev.char_start, ev.char_end
            from attachment_link al
            join attachment a on a.id = al.attachment_id
            left join lateral (
              select id, parse_status
              from parsed_document
              where team_id = al.team_id
                and workspace_id = al.workspace_id
                and attachment_id = al.attachment_id
              order by created_at desc
              limit 1
            ) pd on true
            left join lateral (
              select id, text_excerpt, page_no, char_start, char_end
              from evidence_span
              where team_id = al.team_id
                and workspace_id = al.workspace_id
                and attachment_id = al.attachment_id
                {evidence_lateral_filter_sql}
              order by created_at desc
              limit 5
            ) ev on true
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.entity_id = :business_update_id
              and a.deleted_at is null
              {outer_filter_sql}
            order by al.created_at asc, ev.page_no nulls last
            limit 50
            """
        ),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "trigger_attachment_id": trigger_attachment_id,
            "trigger_evidence_id": trigger_evidence_id,
        },
    ).mappings().all()

    attachments_by_id: dict[str, dict[str, Any]] = {}
    evidence_ids: list[str] = []
    for row in rows:
        item = dict(row)
        attachment_id = str(item["attachment_id"])
        attachment = attachments_by_id.setdefault(
            attachment_id,
            {
                "attachment_id": attachment_id,
                "file_name": item.get("file_name"),
                "file_type": item.get("file_type"),
                "mime_type": item.get("mime_type"),
                "parse_status": item.get("parse_status"),
                "link_type": item.get("link_type"),
                "parsed_document_id": str(item["parsed_document_id"]) if item.get("parsed_document_id") else None,
                "parsed_document_status": item.get("parsed_document_status"),
                "evidence_spans": [],
            },
        )
        if item.get("evidence_id"):
            evidence_id = str(item["evidence_id"])
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
            attachment["evidence_spans"].append(
                {
                    "evidence_id": evidence_id,
                    "page_no": item.get("page_no"),
                    "text_excerpt": item.get("text_excerpt"),
                    "char_start": item.get("char_start"),
                    "char_end": item.get("char_end"),
                }
            )

    attachments = list(attachments_by_id.values())
    combined_parts: list[str] = []
    for attachment in attachments:
        for evidence in attachment.get("evidence_spans", []):
            text_excerpt = _truncate_text(evidence.get("text_excerpt"), 4000)
            if text_excerpt:
                combined_parts.append(
                    "[Attachment evidence "
                    f"{evidence['evidence_id']} from {attachment.get('file_name')}]\n{text_excerpt}"
                )
    return {
        "attachments": attachments,
        "combined_text": "\n\n".join(combined_parts),
        "evidence_ids": evidence_ids,
    }

def _build_business_update_image_context(
    db: Session,
    business_update_id: UUID,
    *,
    trigger_attachment_id: UUID | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    constraints = multimodal_image_constraints(
        max_count=settings.image_multimodal_max_count,
        max_upload_bytes=settings.image_multimodal_max_upload_bytes,
        max_side=settings.image_multimodal_max_side,
        target_bytes=settings.image_multimodal_target_bytes,
    )
    trigger_filter_sql = "and a.id = :trigger_attachment_id" if trigger_attachment_id else ""
    rows = db.execute(
        text(
            f"""
            select
              a.id, a.file_name, a.file_type, a.mime_type, a.file_size,
              a.storage_path, a.metadata_json, al.link_type
            from attachment_link al
            join attachment a on a.id = al.attachment_id
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.entity_id = :business_update_id
              {trigger_filter_sql}
              and a.deleted_at is null
            order by al.created_at asc
            limit 50
            """
        ),
        {
            "business_update_id": business_update_id,
            "trigger_attachment_id": trigger_attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()

    images: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        attachment = _json_safe_dict(row)
        if not is_supported_multimodal_image(attachment):
            continue
        attachment_id = str(attachment["id"])
        if len(images) >= settings.image_multimodal_max_count:
            skipped.append(
                {
                    "attachment_id": attachment_id,
                    "file_name": attachment.get("file_name"),
                    "reason": "image_count_limit_exceeded",
                }
            )
            continue
        file_size = int(attachment.get("file_size") or 0)
        if file_size > settings.image_multimodal_max_upload_bytes:
            skipped.append(
                {
                    "attachment_id": attachment_id,
                    "file_name": attachment.get("file_name"),
                    "reason": "image_too_large",
                    "file_size": file_size,
                    "max_upload_bytes": settings.image_multimodal_max_upload_bytes,
                }
            )
            continue
        image_bytes = _attachment_file_bytes(
            attachment,
            max_bytes=settings.image_multimodal_max_upload_bytes,
        )
        prepared = prepare_image_for_multimodal(
            image_bytes,
            attachment_id=attachment_id,
            file_name=str(attachment.get("file_name") or "image"),
            mime_type=str(attachment.get("mime_type") or ""),
            max_side=settings.image_multimodal_max_side,
            jpeg_quality=settings.image_multimodal_jpeg_quality,
            target_bytes=settings.image_multimodal_target_bytes,
        )
        images.append(
            {
                "attachment_id": prepared.attachment_id,
                "file_name": prepared.file_name,
                "data_url": prepared.data_url,
                "mime_type": prepared.mime_type,
            }
        )
        summary = prepared.trace_summary()
        summary["link_type"] = attachment.get("link_type")
        summaries.append(summary)

    return {
        "images": images,
        "summaries": summaries,
        "skipped": skipped,
        "constraints": constraints,
    }

def _business_update_raw_text_with_attachments(raw_text: Any, attachment_context: dict[str, Any]) -> str:
    base_text = str(raw_text or "").strip()
    attachment_text = str(attachment_context.get("combined_text") or "").strip()
    if not attachment_text:
        return base_text
    if not base_text:
        return f"Attachment OCR evidence:\n{attachment_text}"
    return f"{base_text}\n\nAttachment OCR evidence:\n{attachment_text}"

def _validate_extractor_output(parsed_output_json: dict[str, Any] | None) -> dict[str, Any]:
    if parsed_output_json is None:
        return {"valid": False, "error": "LLM output is not a JSON object."}
    actions = parsed_output_json.get("actions")
    if not isinstance(actions, list):
        return {"valid": False, "error": "LLM output must contain actions array."}
    if not actions:
        return {"valid": False, "error": "LLM output actions array must not be empty."}
    invalid_indexes: list[int] = []
    accepted_aliases: dict[str, list[str]] = {}
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            invalid_indexes.append(index)
            continue
        canonical_action, alias_notes = _canonicalize_extractor_action(action)
        if alias_notes:
            accepted_aliases[str(index)] = alias_notes
        if canonical_action.get("action_type") not in ALLOWED_ACTION_TYPES:
            invalid_indexes.append(index)
            continue
        if not isinstance(canonical_action.get("proposed_changes_json"), dict):
            invalid_indexes.append(index)
    return {
        "valid": len(invalid_indexes) == 0,
        "action_count": len(actions),
        "invalid_indexes": invalid_indexes,
        "accepted_aliases": accepted_aliases,
        "error": "Some actions are invalid." if invalid_indexes else None,
    }


EXTRACTOR_ACTION_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "action_type": ("action",),
    "target_entity_type": ("target",),
    "target_entity_id": ("target_id",),
    "proposed_changes_json": ("proposed_changes", "changes"),
}


def _canonicalize_extractor_action(action: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Accept unambiguous legacy/model aliases without weakening action validation."""

    canonical = dict(action)
    notes: list[str] = []
    for canonical_key, aliases in EXTRACTOR_ACTION_FIELD_ALIASES.items():
        if canonical_key in canonical:
            continue
        for alias in aliases:
            if alias not in action:
                continue
            canonical[canonical_key] = action[alias]
            notes.append(f"{canonical_key}<-{alias}")
            break
    return canonical, notes


def _normalize_actions(
    parsed_output_json: dict[str, Any] | None,
    business_update: dict[str, Any],
    *,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    if not parsed_output_json or not isinstance(parsed_output_json.get("actions"), list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw_action in parsed_output_json["actions"]:
        if not isinstance(raw_action, dict):
            continue
        action, shape_notes = _canonicalize_extractor_action(raw_action)
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
        normalization_notes = [*shape_notes, *normalization_notes]
        profile_sections: list[dict[str, Any]] = []
        if action_type == "seller_fact_update":
            profile_sections, profile_notes = normalize_profile_section_items(
                proposed_changes.get("profile_sections_json")
            )
            normalization_notes.extend(profile_notes)
        if action_type == "seller_fact_update" and db is not None:
            normalization_notes.extend(
                _normalize_seller_target_industry_changes(db, normalized_changes)
            )
        if action_type == "buyer_intent_update":
            update_notes = _normalize_buyer_intent_action_changes(
                normalized_changes,
                evidence_text="\n".join(
                    str(value or "")
                    for value in (action.get("raw_evidence_text"), business_update.get("raw_text"))
                ),
            )
            normalization_notes.extend(update_notes)
        money_notes = _normalize_money_fields_from_action_evidence(
            normalized_changes,
            action,
        )
        normalization_notes.extend(money_notes)
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
                "evidence_id": _business_update_action_evidence_id(action, business_update),
                "confidence": _optional_decimal(action.get("confidence")),
                "reason": action.get("reason"),
                "raw_action": raw_action,
                "normalization_notes": normalization_notes,
                "profile_sections": profile_sections,
            }
        )
    return normalized

def _normalize_proposed_changes(
    action_type: str,
    proposed_changes: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if action_type == "seller_fact_update":
        # Old prompt versions still name raw industry fields. Convert them to
        # normalization candidates before the registry-derived whitelist drops
        # retired seller_target columns; originals remain in action evidence.
        candidate = dict(proposed_changes)
        if "industry_pairs_json" not in candidate:
            legacy_pair = {
                "l1": candidate.get("industry_l1") or candidate.get("industry_primary"),
                "l2": candidate.get("industry_l2") or candidate.get("industry_secondary"),
            }
            if legacy_pair["l1"] or legacy_pair["l2"]:
                candidate["industry_pairs_json"] = [legacy_pair]
        candidate.pop("industry_l1", None)
        candidate.pop("industry_l2", None)
        if "location_province" not in candidate:
            legacy_province = candidate.get("headquarter_province") or candidate.get("registered_province")
            if legacy_province:
                candidate["location_province"] = legacy_province
        if "location_city" not in candidate:
            legacy_city = candidate.get("headquarter_city") or candidate.get("registered_city")
            if legacy_city:
                candidate["location_city"] = legacy_city
        return _normalize_change_fields(
            candidate,
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

def _normalize_buyer_intent_action_changes(changes: dict[str, Any], *, evidence_text: str) -> list[str]:
    notes: list[str] = []
    for field in BUYER_INTENT_PARSE_NUMERIC_FIELDS:
        if field in changes:
            normalized = _optional_decimal(changes[field])
            if normalized is None:
                changes.pop(field, None)
                notes.append(f"{field}:dropped_invalid_number")
            else:
                changes[field] = normalized

    for field in BUYER_INTENT_PARSE_JSON_FIELDS:
        if field in changes and not isinstance(changes[field], (list, dict)):
            changes.pop(field, None)
            notes.append(f"{field}:dropped_invalid_json")

    tags = changes.get("industry_focus_tags_json")
    if isinstance(tags, list):
        cleaned_tags: list[str] = []
        for value in tags:
            tag = str(value or "").strip()[:80]
            if tag and tag not in cleaned_tags:
                cleaned_tags.append(tag)
        if cleaned_tags:
            changes["industry_focus_tags_json"] = cleaned_tags
        else:
            changes.pop("industry_focus_tags_json", None)

    source = evidence_text.lower()
    if ("估值" in evidence_text or "valuation" in source) and not (
        "市值" in evidence_text or "market cap" in source
    ):
        for field in ("min_market_cap_yuan", "max_market_cap_yuan", "market_cap_range_summary"):
            if field in changes:
                changes.pop(field, None)
                notes.append(f"dropped_{field}:source_mentions_valuation_not_market_cap")
    return notes

def _business_update_parser_node_name(business_update: dict[str, Any]) -> str:
    seller_ids = _uuid_list(business_update.get("bound_seller_target_ids_json"))
    intent_ids = _uuid_list(business_update.get("bound_buyer_intent_ids_json"))
    if len(intent_ids) == 1 and not seller_ids:
        return "buyer_intent_update_parser"
    if len(seller_ids) == 1 and not intent_ids:
        return "seller_target_update_parser"
    return "business_update_extractor"

def _normalize_money_fields_from_action_evidence(
    changes: dict[str, Any],
    action: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    evidence_text = _action_money_evidence_text(action)
    if not evidence_text:
        return notes
    evidence_amounts = _money_amounts_from_chinese_units(evidence_text)
    if not evidence_amounts:
        return notes

    for field in MONEY_YUAN_FIELDS.intersection(changes):
        current = _optional_decimal(changes.get(field))
        if current is None:
            continue
        replacement = _closest_evidence_money_amount(current, evidence_amounts)
        if replacement is None or replacement == current:
            continue
        changes[field] = _decimal_to_json_number(replacement)
        notes.append(f"{field}:evidence_money_unit:{current}->{replacement}")
    return notes

def _action_money_evidence_text(action: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("raw_evidence_text", "reason"):
        value = action.get(key)
        if value:
            pieces.append(str(value))
    proposed_changes = action.get("proposed_changes_json")
    if isinstance(proposed_changes, dict):
        for key in ("raw_requirement_text", "intent_summary", "business_summary", "transaction_summary"):
            value = proposed_changes.get(key)
            if value:
                pieces.append(str(value))
    return "\n".join(pieces)

def _money_amounts_from_chinese_units(text_value: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    seen: set[Decimal] = set()
    for match in MONEY_UNIT_PATTERN.finditer(text_value):
        unit = match.group(3)
        for number_text in (match.group(1), match.group(2)):
            if not number_text:
                continue
            try:
                number = Decimal(number_text.replace(",", ""))
            except Exception:
                continue
            multiplier = Decimal("100000000") if unit in {"亿元", "亿"} else Decimal("10000") if unit in {"万元", "万"} else Decimal("1")
            amount = number * multiplier
            if amount > 0 and amount not in seen:
                amounts.append(amount)
                seen.add(amount)
    return amounts

def _closest_evidence_money_amount(current: Decimal, evidence_amounts: list[Decimal]) -> Decimal | None:
    if current <= 0:
        return None
    exact_or_close = [amount for amount in evidence_amounts if _decimal_ratio(current, amount) <= Decimal("1.02")]
    if exact_or_close:
        return None
    candidates = [
        amount
        for amount in evidence_amounts
        if _decimal_ratio(current, amount) in {Decimal("10"), Decimal("100")}
    ]
    if len(candidates) != 1:
        return None
    return candidates[0]

def _business_update_action_evidence_id(
    action: dict[str, Any],
    business_update: dict[str, Any],
) -> UUID | None:
    explicit = _optional_uuid(action.get("evidence_id"))
    if explicit:
        return explicit
    raw_evidence_text = str(action.get("raw_evidence_text") or "").strip()
    evidence_ids = business_update.get("attachment_evidence_ids")
    if raw_evidence_text and isinstance(evidence_ids, list) and len(evidence_ids) == 1:
        return _optional_uuid(evidence_ids[0])
    return None

def _attach_image_evidence_to_actions(
    db: Session,
    job: JobClaim,
    actions: list[dict[str, Any]],
    image_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not image_summaries:
        return actions
    image_by_id = {str(item.get("attachment_id")): item for item in image_summaries if item.get("attachment_id")}
    if not image_by_id:
        return actions

    updated_actions: list[dict[str, Any]] = []
    for action in actions:
        if action.get("evidence_id"):
            updated_actions.append(action)
            continue
        raw_evidence_text = str(action.get("raw_evidence_text") or "").strip()
        if not raw_evidence_text:
            updated_actions.append(action)
            continue
        attachment_id = _match_image_evidence_attachment(action, raw_evidence_text, image_by_id)
        if attachment_id is None and len(image_by_id) == 1:
            attachment_id = UUID(next(iter(image_by_id)))
        if attachment_id is None:
            updated_actions.append(action)
            continue
        evidence_id = _insert_image_llm_evidence_span(
            db,
            attachment_id=attachment_id,
            job_id=job.id,
            text_excerpt=raw_evidence_text,
        )
        updated_actions.append(
            {
                **action,
                "evidence_id": evidence_id,
                "normalization_notes": [
                    *action.get("normalization_notes", []),
                    "evidence_id<-image_llm_excerpt",
                ],
            }
        )
    return updated_actions

def _match_image_evidence_attachment(
    action: dict[str, Any],
    raw_evidence_text: str,
    image_by_id: dict[str, dict[str, Any]],
) -> UUID | None:
    candidates = [
        action.get("attachment_id"),
        action.get("evidence_attachment_id"),
        action.get("source_attachment_id"),
    ]
    raw_action = action.get("raw_action") if isinstance(action.get("raw_action"), dict) else {}
    candidates.extend(
        [
            raw_action.get("attachment_id"),
            raw_action.get("evidence_attachment_id"),
            raw_action.get("source_attachment_id"),
        ]
    )
    for candidate in candidates:
        attachment_id = _optional_uuid(candidate)
        if attachment_id and str(attachment_id) in image_by_id:
            return attachment_id
    for attachment_id_text, summary in image_by_id.items():
        file_name = str(summary.get("file_name") or "")
        if attachment_id_text in raw_evidence_text or (file_name and file_name in raw_evidence_text):
            return UUID(attachment_id_text)
    return None

def _insert_image_llm_evidence_span(
    db: Session,
    *,
    attachment_id: UUID,
    job_id: UUID,
    text_excerpt: str,
) -> UUID:
    excerpt = _truncate_text(text_excerpt, 2000) or ""
    row = db.execute(
        text(
            """
            insert into evidence_span (
              team_id, workspace_id, source_type, source_id, attachment_id,
              parsed_document_id, page_no, text_excerpt, char_start, char_end
            )
            values (
              :team_id, :workspace_id, 'image_llm_excerpt', :job_id, :attachment_id,
              null, null, :text_excerpt, null, null
            )
            returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_id": job_id,
            "attachment_id": attachment_id,
            "text_excerpt": excerpt,
        },
    ).mappings().one()
    return row["id"]

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
        "evidence_id": None,
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
                  proposed_changes_json, raw_evidence_text, evidence_id, confidence,
                  review_status, metadata_json
                )
                values (
                  :team_id, :workspace_id, :business_update_id,
                  :action_type, :target_entity_type, :target_entity_id,
                  :proposed_changes_json, :raw_evidence_text, :evidence_id, :confidence,
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
                "proposed_changes_json": _json_safe_value(action["proposed_changes_json"]),
                "raw_evidence_text": action["raw_evidence_text"],
                "evidence_id": action.get("evidence_id"),
                "confidence": action["confidence"],
                "metadata_json": _json_safe_value(
                    {
                        "source": "business_update_extractor",
                        "job_id": str(job_id),
                        "reason": action.get("reason"),
                        "raw_action": action.get("raw_action"),
                        "normalization_notes": action.get("normalization_notes", []),
                        "profile_sections": action.get("profile_sections", []),
                    }
                ),
            },
        ).mappings().one()
        action_ids.append(row["id"])
    return action_ids


def _persist_document_profile_sections(
    db: Session,
    *,
    actions: list[dict[str, Any]],
    attachment_context: dict[str, Any],
    business_update_id: UUID | None = None,
) -> int:
    """Write qualitative claims extracted from user-supplied target material.

    The uploaded attachment is first-party evidence, so supported non-empty
    sections can be auto-accepted. Missing sections are not marked not_found:
    an attachment is rarely intended to be an exhaustive company profile.
    """
    attachment_names = [
        str(item.get("file_name") or "").strip()
        for item in attachment_context.get("attachments", [])
        if str(item.get("file_name") or "").strip()
    ]
    source_title = "、".join(dict.fromkeys(attachment_names[:3])) or "业务更新材料"
    attachment_evidence = str(attachment_context.get("combined_text") or "")
    written = 0
    for action in actions:
        if action.get("action_type") != "seller_fact_update":
            continue
        target_id = _optional_uuid(action.get("target_entity_id"))
        if target_id is None:
            continue
        fallback_excerpt = str(action.get("raw_evidence_text") or "").strip()[:2000] or None
        for section in _document_profile_sections_for_action(action):
            proposed_excerpt = str(section.get("source_excerpt") or "").strip()
            source_excerpt = _verified_document_excerpt(
                proposed_excerpt,
                attachment_evidence=attachment_evidence,
                fallback_excerpt=fallback_excerpt,
            )
            apply_profile_section(
                db,
                entity_type="seller_target",
                entity_id=target_id,
                section_code=section["section_code"],
                info_status="filled",
                content_text=section["content_text"],
                source_type="user_attachment",
                source_title=source_title,
                source_excerpt=source_excerpt,
                as_of_date=section.get("as_of_date"),
                review_status="auto_accepted",
                user_id=SYSTEM_USER_ID,
                log_source_type="user_attachment",
                business_update_id=business_update_id,
            )
            written += 1
    return written


def _document_profile_sections_for_action(action: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep per-group ``其他`` genuinely supplementary.

    ``business_summary`` is a structured target field. It must never be copied
    into the business/product supplement just to make that block non-empty.
    Old prompts can still emit the same text twice, so remove an exact
    whitespace-insensitive duplicate before the profile writer persists it.
    """
    sections = [dict(item) for item in (action.get("profile_sections") or [])]
    business_summary = str(
        (action.get("proposed_changes_json") or {}).get("business_summary") or ""
    ).strip()
    current = next(
        (item for item in sections if item.get("section_code") == "business_product"),
        None,
    )
    if current is not None and _same_profile_text(current.get("content_text"), business_summary):
        sections.remove(current)
    return sections


def _same_profile_text(left: Any, right: Any) -> bool:
    return re.sub(r"\s+", "", str(left or "")) == re.sub(r"\s+", "", str(right or ""))


def _business_summary_profile_worthy(summary: str) -> bool:
    """Reject generic placeholders before they become semantic evidence."""
    text_value = str(summary or "").strip()
    if len(text_value) < 16:
        return False
    if any(
        phrase in text_value
        for phrase in ("未详", "不详", "未知", "未提供", "无法判断", "无法确认", "信息不足")
    ):
        return False
    return any(
        term in text_value
        for term in ("产品", "服务", "设备", "材料", "软件", "解决方案", "生产", "研发", "销售", "运营", "提供")
    )


def _verified_document_excerpt(
    proposed_excerpt: str,
    *,
    attachment_evidence: str,
    fallback_excerpt: str | None,
) -> str | None:
    """Accept an attachment quote when it differs only in OCR whitespace."""
    if not proposed_excerpt:
        return fallback_excerpt
    if proposed_excerpt in attachment_evidence:
        return proposed_excerpt[:2000]
    compact_proposed = re.sub(r"\s+", "", proposed_excerpt)
    compact_evidence = re.sub(r"\s+", "", attachment_evidence)
    if compact_proposed and compact_proposed in compact_evidence:
        return proposed_excerpt[:2000]
    return fallback_excerpt

AUTO_APPLY_ACTION_TYPE_ORDER = {
    "seller_fact_update": 0,
    "buyer_intent_update": 1,
    "buyer_seller_relation_update": 2,
    "buyer_intent_target_exclusion": 3,
}

def _auto_apply_safe_actions(db: Session, action_ids: list[UUID]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for action_id in action_ids:
        action = _get_extracted_action_for_auto_apply(db, action_id)
        if action and _is_safe_auto_apply_action(action):
            actions.append(action)
    actions.sort(key=lambda action: AUTO_APPLY_ACTION_TYPE_ORDER.get(action["action_type"], 99))

    results: list[dict[str, Any]] = []
    for action in actions:
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
              proposed_changes_json, raw_evidence_text, evidence_id, confidence, review_status,
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

def _mark_business_update_failed_if_final_attempt(
    db: Session,
    job: JobClaim,
    business_update_id: UUID,
    error_message: str,
) -> None:
    if job.attempt_count < job.max_attempts:
        return
    _mark_business_update_failed(db, business_update_id, job.id, error_message)

def _latest_active_business_update_process_job(db: Session, business_update_id: UUID) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_type, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = 'business_update_extract_actions'
              and entity_type = 'business_update'
              and entity_id = :business_update_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None

def _latest_active_child_parse_job(
    db: Session,
    *,
    job_type: str,
    entity_type: str,
    entity_id: UUID,
) -> dict[str, Any] | None:
    row = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_type, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = :job_type
              and entity_type = :entity_type
              and entity_id = :entity_id
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": job_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
        },
    ).mappings().one_or_none()
    return dict(row) if row else None
