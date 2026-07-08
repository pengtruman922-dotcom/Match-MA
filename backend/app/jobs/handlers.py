from __future__ import annotations

import re
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.doc2x_client import Doc2xCallError, poll_doc2x_status, submit_doc2x_pdf
from backend.app.ai.embedding_client import (
    EmbeddingCallError,
    call_openai_compatible_embedding,
    embedding_to_pgvector_literal,
)
from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.ocr_client import OcrInput, build_attachment_ocr_input_json, call_attachment_ocr
from backend.app.ai.prompting import render_template
from backend.app.ai.rerank_client import RerankCallError, call_dashscope_compatible_rerank
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.extracted_actions import (
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
    apply_target_follow_up_action,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.search_docs import (
    create_embedding_job_for_search_doc,
    create_search_doc_rebuild_job,
    rebuild_buyer_intent_search_doc,
    rebuild_seller_target_search_doc,
)
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    read_attachment_bytes,
    read_local_text_content,
    save_generated_text,
)
from backend.app.services.image_inputs import (
    is_supported_multimodal_image,
    multimodal_image_constraints,
    prepare_image_for_multimodal,
)
from backend.app.services.office_inspection import inspect_office_text, office_document_kind
from backend.app.services.pdf_inspection import inspect_pdf_text_layer

ALLOWED_ACTION_TYPES = {
    "seller_fact_update",
    "seller_event",
    "target_follow_up",
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

_SKIP_FIELD = object()

MONEY_YUAN_FIELDS = {
    "market_cap_yuan",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "valuation_yuan",
    "asking_price_yuan",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
}

_MONEY_UNIT_YI = chr(0x4EBF)
_MONEY_UNIT_WAN = chr(0x4E07)
_MONEY_UNIT_YUAN = chr(0x5143)
_MONEY_RANGE_SEPARATORS = "-~" + chr(0x2013) + chr(0x2014) + chr(0x81F3) + chr(0x5230)

MONEY_UNIT_PATTERN = re.compile(
    "(?<![\\d.])(\\d+(?:,\\d{3})*(?:\\.\\d+)?)"
    f"(?:\\s*(?:[{re.escape(_MONEY_RANGE_SEPARATORS)}])\\s*(\\d+(?:,\\d{{3}})*(?:\\.\\d+)?))?"
    f"\\s*({_MONEY_UNIT_YI}{_MONEY_UNIT_YUAN}|{_MONEY_UNIT_YI}|"
    f"{_MONEY_UNIT_WAN}{_MONEY_UNIT_YUAN}|{_MONEY_UNIT_WAN}|{_MONEY_UNIT_YUAN})"
)

SELLER_TARGET_CHANGE_FIELDS = {
    "target_name",
    "target_subject_name",
    "industry_primary",
    "industry_secondary",
    "headquarter_province",
    "headquarter_city",
    "listed_status",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "financial_period_label",
    "valuation_yuan",
    "valuation_date",
    "asking_price_yuan",
    "asking_price_date",
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
    "subject": "target_subject_name",
    "subject_name": "target_subject_name",
    "target_subject": "target_subject_name",
    "target_subject_name": "target_subject_name",
    "owner_company": "target_subject_name",
    "company_name": "target_subject_name",
    "industry": "industry_secondary",
    "location": "raw_region_text",
    "province": "headquarter_province",
    "city": "headquarter_city",
    "revenue": "current_revenue_yuan",
    "profit": "current_net_profit_yuan",
    "net_profit": "current_net_profit_yuan",
    "valuation": "valuation_yuan",
    "valuation_time": "valuation_date",
    "valuation_date": "valuation_date",
    "asking_price": "asking_price_yuan",
    "asking_price_time": "asking_price_date",
    "asking_price_date": "asking_price_date",
    "price_date": "asking_price_date",
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
    "min_total_profit_yuan",
    "max_pe",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "market_cap_range_summary",
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
    "equity_ratio_summary",
    "equity_requirement_type",
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
    "min_market_cap": "min_market_cap_yuan",
    "max_market_cap": "max_market_cap_yuan",
    "market_cap": "market_cap_range_summary",
    "control": "requires_control",
    "consolidation": "requires_consolidation",
    "listing_status_requirement": "preferred_listed_status",
    "listed_status_requirement": "preferred_listed_status",
    "listing_board": "listing_board_requirement_summary",
    "listing_board_requirement": "listing_board_requirement_summary",
    "financing_stage": "financing_stage_requirement_summary",
    "listing_stage": "financing_stage_requirement_summary",
    "transaction_types": "transaction_types_json",
    "deal_types": "transaction_types_json",
    "premium": "premium_tolerance_summary",
    "premium_tolerance": "premium_tolerance_summary",
    "debt_ratio": "debt_ratio_requirement_summary",
    "max_debt": "max_debt_ratio",
    "major_risk_tolerance": "major_risk_tolerance_summary",
    "risk_tolerance": "major_risk_tolerance_summary",
    "buyer_advantage": "buyer_industry_advantage_summary",
    "regional_industry_advantage": "buyer_industry_advantage_summary",
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

SELLER_TARGET_POST_PARSE_STATUSES = {"parsing", "pending_review", "insufficient", "parse_failed"}
SELLER_TARGET_PARSE_FAILURE_STATUSES = {"parsing"}

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
    "preferred_listed_status": {"listed", "preparing_listing", "pre_ipo", "unlisted", "any", "unknown"},
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
    if job.job_type == "seller_target_parse":
        return _handle_seller_target_parse(db, job)
    if job.job_type == "buyer_intent_parse":
        return _handle_buyer_intent_parse(db, job)
    if job.job_type == "attachment_ocr_parse":
        return _handle_attachment_ocr_parse(db, job)
    if job.job_type == "attachment_ocr_poll":
        return _handle_attachment_ocr_poll(db, job)
    if job.job_type == "seller_search_doc_rebuild":
        return _handle_seller_search_doc_rebuild(db, job)
    if job.job_type == "buyer_intent_search_doc_rebuild":
        return _handle_buyer_intent_search_doc_rebuild(db, job)
    if job.job_type == "embedding_generate":
        return _handle_embedding_generate(db, job)
    if job.job_type == "recommendation_report_generate":
        return _handle_recommendation_report_generate(db, job)
    if job.job_type == "recommendation_rerank":
        return _handle_recommendation_rerank(db, job)
    if job.job_type == "model_node_test":
        return _handle_model_node_test(db, job)

    return {
        "handled": False,
        "job_type": job.job_type,
        "message": "No real job handler is implemented for this job type yet.",
    }


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

    # Enrich the linked buyer party (acquirer) from the same requirement material.
    applied_buyer_party_fields: list[str] = []
    party_changes = _normalize_buyer_party_parse_changes(parsed_output_json)
    if party_changes and buyer_intent.get("buyer_party_id"):
        buyer_party = _get_buyer_party(db, UUID(str(buyer_intent["buyer_party_id"])))
        if buyer_party:
            applied_buyer_party_fields = _apply_buyer_party_parse_changes(
                db,
                buyer_party,
                party_changes,
                job.id,
                source_context,
            )

    return {
        "handled": True,
        "job_type": job.job_type,
        "buyer_intent_id": str(buyer_intent_id),
        "applied_fields": applied_fields,
        "field_count": len(applied_fields),
        "applied_buyer_party_fields": applied_buyer_party_fields,
        "buyer_party_field_count": len(applied_buyer_party_fields),
        "trace_created": True,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "schema_valid": schema_validation_json["valid"],
    }


def _handle_attachment_ocr_parse(db: Session, job: JobClaim) -> dict[str, object]:
    attachment_id = _resolve_entity_id(job, expected_entity_type="attachment")
    if attachment_id is None:
        attachment_id = _optional_uuid(job.payload_json.get("attachment_id"))
    if attachment_id is None:
        raise ValueError("attachment_ocr_parse job requires an attachment entity_id.")

    attachment = _get_attachment_for_ocr(db, attachment_id)
    node_config = _get_default_ocr_node_config(db, "ocr_attachment_parser")
    ocr_input = _attachment_ocr_input(job, attachment_id=attachment_id, attachment=attachment)
    input_json = build_attachment_ocr_input_json(node_config=node_config, ocr_input=ocr_input)
    pdf_result = _handle_pdf_attachment_ocr(db, job, attachment_id=attachment_id, attachment=attachment, node_config=node_config)
    if pdf_result is not None:
        return pdf_result
    office_result = _handle_office_attachment_ocr(
        db,
        job,
        attachment_id=attachment_id,
        attachment=attachment,
        node_config=node_config,
    )
    if office_result is not None:
        return office_result

    ocr_result = call_attachment_ocr(node_config=node_config, ocr_input=ocr_input)
    extracted_text = ocr_result.extracted_text

    parsed_document_id = None
    if extracted_text:
        parsed_document_id = _insert_parsed_document_for_ocr(
            db,
            attachment_id=attachment_id,
            parse_status=ocr_result.terminal_parse_status,
            extracted_text=extracted_text,
            error_message=ocr_result.error_message,
        )
    elif ocr_result.terminal_parse_status == "parsed":
        parsed_document_id = _insert_parsed_document_for_ocr(
            db,
            attachment_id=attachment_id,
            parse_status="parsed",
            extracted_text="",
            error_message=ocr_result.error_message,
        )
    evidence_id = None
    if extracted_text and parsed_document_id:
        evidence_id = _insert_ocr_evidence_span(
            db,
            attachment_id=attachment_id,
            parsed_document_id=parsed_document_id,
            job_id=job.id,
            text_excerpt=extracted_text,
        )

    if parsed_document_id:
        _update_attachment_parse_terminal(
            db,
            attachment_id=attachment_id,
            parse_status=ocr_result.terminal_parse_status,
            job_id=job.id,
            parsed_document_id=parsed_document_id,
            evidence_id=evidence_id,
            text_length=len(extracted_text) if extracted_text else 0,
        )
    else:
        _update_attachment_parse_terminal_without_document(
            db,
            attachment_id=attachment_id,
            parse_status=ocr_result.terminal_parse_status,
            job_id=job.id,
            metadata_patch={
                "last_text_length": 0,
                "last_ocr_error": ocr_result.error_message,
            },
        )
        _mark_business_updates_blocked_by_attachment_ocr(
            db,
            attachment_id=attachment_id,
            job_id=job.id,
            error_message=ocr_result.error_message,
        )
    touched_seller_target_count = _touch_seller_targets_linked_to_attachment(db, attachment_id)
    child_parse_jobs = _enqueue_linked_parse_jobs_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        parsed_document_id=parsed_document_id,
        evidence_id=evidence_id,
        extracted_text=extracted_text,
    )
    business_update_process_job = _enqueue_business_update_process_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        evidence_id=evidence_id,
        extracted_text=extracted_text,
    )
    _insert_ocr_trace(
        db,
        job=job,
        attachment_id=attachment_id,
        node_config=node_config,
        status=ocr_result.trace_status,
        input_json=input_json,
        raw_output_text=ocr_result.raw_output_text,
        parsed_output_json={
            **ocr_result.parsed_output_json,
            "parsed_document_id": str(parsed_document_id) if parsed_document_id else None,
            "evidence_id": str(evidence_id) if evidence_id else None,
            "terminal_parse_status": ocr_result.terminal_parse_status,
            "child_parse_jobs": child_parse_jobs,
            "business_update_process_job": business_update_process_job,
        },
        latency_ms=ocr_result.latency_ms,
        error_message=ocr_result.error_message,
    )

    return {
        "handled": True,
        "job_type": job.job_type,
        "attachment_id": str(attachment_id),
        "parse_status": ocr_result.terminal_parse_status,
        "trace_status": ocr_result.trace_status,
        "parsed_document_id": str(parsed_document_id) if parsed_document_id else None,
        "evidence_id": str(evidence_id) if evidence_id else None,
        "text_length": len(extracted_text) if extracted_text else 0,
        "touched_seller_target_count": touched_seller_target_count,
        "child_parse_jobs": child_parse_jobs,
        "child_parse_job_count": len(child_parse_jobs),
        "business_update_process_job": business_update_process_job,
        "trace_created": True,
        "node_name": node_config["node_name"],
        "model_name": node_config["model_name"],
        "execution_mode": ocr_result.execution_mode,
    }


def _handle_attachment_ocr_poll(db: Session, job: JobClaim) -> dict[str, object]:
    attachment_id = _resolve_entity_id(job, expected_entity_type="attachment")
    if attachment_id is None:
        attachment_id = _optional_uuid(job.payload_json.get("attachment_id"))
    if attachment_id is None:
        raise ValueError("attachment_ocr_poll job requires an attachment entity_id.")

    attachment = _get_attachment_for_ocr(db, attachment_id)
    settings = get_settings()
    uid = str(job.payload_json.get("doc2x_uid") or "").strip()
    if not uid:
        raise ValueError("attachment_ocr_poll job requires doc2x_uid.")
    doc2x_api_key = settings.effective_doc2x_api_key
    if not doc2x_api_key:
        raise ValueError("DOC2X_API_KEY is required for Doc2X OCR polling.")

    started_at = float(job.payload_json.get("doc2x_started_epoch") or time.time())
    elapsed_seconds = int(time.time() - started_at)
    if elapsed_seconds > settings.doc2x_max_wait_seconds:
        _update_attachment_parse_terminal_without_document(
            db,
            attachment_id=attachment_id,
            parse_status="failed",
            job_id=job.id,
            metadata_patch={
                "last_ocr_status": "failed",
                "last_ocr_provider": "doc2x",
                "last_doc2x_uid": uid,
                "last_doc2x_error": "Doc2X polling exceeded max wait seconds.",
            },
        )
        _mark_business_updates_blocked_by_attachment_ocr(
            db,
            attachment_id=attachment_id,
            job_id=job.id,
            error_message="Doc2X polling exceeded max wait seconds.",
        )
        raise ValueError("Doc2X polling exceeded max wait seconds.")

    try:
        status_result = poll_doc2x_status(
            base_url=settings.doc2x_base_url,
            api_key=doc2x_api_key,
            uid=uid,
            timeout_seconds=30,
        )
    except Doc2xCallError as exc:
        raise ValueError(str(exc)) from exc

    _patch_attachment_metadata(
        db,
        attachment_id,
        {
            "last_ocr_status": "provider_processing"
            if status_result.status == "processing"
            else status_result.status,
            "last_ocr_provider": "doc2x",
            "last_doc2x_uid": uid,
            "last_doc2x_progress": status_result.progress,
        },
    )

    if status_result.status == "processing":
        next_job = _enqueue_doc2x_poll_job(
            db,
            parent_job_id=job.payload_json.get("submitted_by_job_id") or job.id,
            attachment_id=attachment_id,
            business_update_id=_optional_uuid(job.payload_json.get("business_update_id")),
            doc2x_uid=uid,
            started_epoch=started_at,
            source_payload=job.payload_json,
            run_after_seconds=settings.doc2x_poll_interval_seconds,
        )
        _insert_ocr_trace(
            db,
            job=job,
            attachment_id=attachment_id,
            node_config={
                "provider_config_id": None,
                "node_config_id": None,
                "provider_name": "doc2x",
                "model_name": settings.doc2x_model,
                "node_name": "ocr_attachment_parser",
            },
            status="succeeded",
            input_json={
                "attachment_id": str(attachment_id),
                "provider": "doc2x",
                "doc2x_uid": uid,
                "poll_status": "processing",
            },
            raw_output_text=None,
            parsed_output_json={
                "provider": "doc2x",
                "status": status_result.status,
                "progress": status_result.progress,
                "next_poll_job": _json_safe_dict(next_job),
            },
            latency_ms=status_result.latency_ms,
            error_message=None,
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "attachment_id": str(attachment_id),
            "provider": "doc2x",
            "provider_status": "processing",
            "progress": status_result.progress,
            "next_poll_job": _json_safe_dict(next_job),
        }

    if status_result.status == "failed":
        detail = status_result.detail or "Doc2X parsing failed."
        _update_attachment_parse_terminal_without_document(
            db,
            attachment_id=attachment_id,
            parse_status="failed",
            job_id=job.id,
            metadata_patch={
                "last_ocr_status": "failed",
                "last_ocr_provider": "doc2x",
                "last_doc2x_uid": uid,
                "last_doc2x_error": str(detail),
            },
        )
        _insert_ocr_trace(
            db,
            job=job,
            attachment_id=attachment_id,
            node_config={
                "provider_config_id": None,
                "node_config_id": None,
                "provider_name": "doc2x",
                "model_name": settings.doc2x_model,
                "node_name": "ocr_attachment_parser",
            },
            status="failed",
            input_json={"attachment_id": str(attachment_id), "provider": "doc2x", "doc2x_uid": uid},
            raw_output_text=None,
            parsed_output_json={"provider": "doc2x", "status": "failed", "detail": detail},
            latency_ms=status_result.latency_ms,
            error_message=str(detail),
        )
        _mark_business_updates_blocked_by_attachment_ocr(
            db,
            attachment_id=attachment_id,
            job_id=job.id,
            error_message=f"Doc2X parse failed: {detail}",
        )
        raise ValueError(f"Doc2X parse failed: {detail}")

    if status_result.status != "success":
        raise ValueError(f"Unsupported Doc2X status: {status_result.status}")

    extracted_text = status_result.markdown_text.strip()
    if not extracted_text:
        extracted_text = _doc2x_status_text_fallback(status_result.raw_response)
    text_path = _save_ocr_text_artifact(
        attachment_id=attachment_id,
        parsed_document_id=None,
        content=extracted_text,
        suffix="doc2x.md",
        content_type="text/markdown; charset=utf-8",
    )
    parsed_document_id = _insert_parsed_document_for_ocr(
        db,
        attachment_id=attachment_id,
        parse_status="parsed" if extracted_text else "skipped",
        extracted_text=extracted_text,
        error_message=None if extracted_text else "Doc2X returned no markdown text.",
        parser_name="doc2x",
        parser_version=settings.doc2x_model,
        text_path=text_path,
        markdown_path=text_path,
        page_count=status_result.page_count,
    )
    evidence_id = None
    if extracted_text:
        evidence_id = _insert_ocr_evidence_span(
            db,
            attachment_id=attachment_id,
            parsed_document_id=parsed_document_id,
            job_id=job.id,
            text_excerpt=extracted_text,
        )
    _update_attachment_parse_terminal(
        db,
        attachment_id=attachment_id,
        parse_status="parsed" if extracted_text else "skipped",
        job_id=job.id,
        parsed_document_id=parsed_document_id,
        evidence_id=evidence_id,
        text_length=len(extracted_text),
        metadata_patch={
            "last_ocr_provider": "doc2x",
            "last_doc2x_uid": uid,
            "last_doc2x_progress": status_result.progress,
            "last_pdf_kind": "scanned_pdf",
        },
    )
    touched_seller_target_count = _touch_seller_targets_linked_to_attachment(db, attachment_id)
    child_parse_jobs = _enqueue_linked_parse_jobs_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        parsed_document_id=parsed_document_id,
        evidence_id=evidence_id,
        extracted_text=extracted_text,
    )
    business_update_process_job = _enqueue_business_update_process_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        evidence_id=evidence_id,
        extracted_text=extracted_text,
    )
    _insert_ocr_trace(
        db,
        job=job,
        attachment_id=attachment_id,
        node_config={
            "provider_config_id": None,
            "node_config_id": None,
            "provider_name": "doc2x",
            "model_name": settings.doc2x_model,
            "node_name": "ocr_attachment_parser",
        },
        status="succeeded" if extracted_text else "skipped",
        input_json={"attachment_id": str(attachment_id), "provider": "doc2x", "doc2x_uid": uid},
        raw_output_text=extracted_text,
        parsed_output_json={
            "provider": "doc2x",
            "status": status_result.status,
            "progress": status_result.progress,
            "page_count": status_result.page_count,
            "parsed_document_id": str(parsed_document_id),
            "evidence_id": str(evidence_id) if evidence_id else None,
            "child_parse_jobs": child_parse_jobs,
            "business_update_process_job": business_update_process_job,
        },
        latency_ms=status_result.latency_ms,
        error_message=None if extracted_text else "Doc2X returned no markdown text.",
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "attachment_id": str(attachment_id),
        "provider": "doc2x",
        "provider_status": status_result.status,
        "parse_status": "parsed" if extracted_text else "skipped",
        "parsed_document_id": str(parsed_document_id),
        "evidence_id": str(evidence_id) if evidence_id else None,
        "text_length": len(extracted_text),
        "touched_seller_target_count": touched_seller_target_count,
        "child_parse_jobs": child_parse_jobs,
        "child_parse_job_count": len(child_parse_jobs),
        "business_update_process_job": business_update_process_job,
    }


def _handle_business_update_extract_actions(db: Session, job: JobClaim) -> dict[str, object]:
    business_update_id = _resolve_business_update_id(job)
    if business_update_id is None:
        raise ValueError("business_update_extract_actions job requires a business_update_id.")

    business_update = _get_business_update(db, business_update_id)
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
    actions = _normalize_actions(parsed_output_json, business_update_for_normalization)
    if not actions:
        actions = [_build_unresolved_action(parsed_output_json, llm_result.raw_output_text)]
    actions = _attach_image_evidence_to_actions(db, job, actions, image_context["summaries"])
    _insert_llm_trace(
        db,
        job=job,
        business_update_id=business_update_id,
        node_config=node_config,
        status="succeeded",
        input_json=input_json,
        prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=parsed_output_json,
        schema_validation_json=schema_validation_json,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
    )
    db.commit()

    try:
        created_actions = _insert_extracted_actions(db, business_update_id, actions, job.id)
        auto_apply_results = _auto_apply_safe_actions(db, created_actions)
        pending_review_target_count = _mark_bound_seller_targets_pending_review_after_business_update_parse(
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
                    "last_bound_seller_targets_pending_review": pending_review_target_count,
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
        "bound_seller_targets_pending_review": pending_review_target_count,
    }


def _handle_seller_search_doc_rebuild(db: Session, job: JobClaim) -> dict[str, object]:
    seller_target_id = _resolve_entity_id(job, expected_entity_type="seller_target")
    if seller_target_id is None:
        raise ValueError("seller_search_doc_rebuild job requires a seller_target entity_id.")

    result = rebuild_seller_target_search_doc(db, seller_target_id)
    embedding_job_id = create_embedding_job_for_search_doc(
        db,
        owner_job_id=job.id,
        entity_type="seller_target",
        entity_id=seller_target_id,
        search_doc_id=result["search_doc_id"],
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(seller_target_id),
        "search_doc_id": str(result["search_doc_id"]),
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": str(embedding_job_id),
    }


def _handle_buyer_intent_search_doc_rebuild(db: Session, job: JobClaim) -> dict[str, object]:
    buyer_intent_id = _resolve_entity_id(job, expected_entity_type="buyer_intent")
    if buyer_intent_id is None:
        raise ValueError("buyer_intent_search_doc_rebuild job requires a buyer_intent entity_id.")

    result = rebuild_buyer_intent_search_doc(db, buyer_intent_id)
    embedding_job_id = create_embedding_job_for_search_doc(
        db,
        owner_job_id=job.id,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        search_doc_id=result["search_doc_id"],
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "buyer_intent_id": str(buyer_intent_id),
        "search_doc_id": str(result["search_doc_id"]),
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": str(embedding_job_id),
    }


def _handle_embedding_generate(db: Session, job: JobClaim) -> dict[str, object]:
    entity_type = str(job.payload_json.get("entity_type") or job.entity_type or "")
    if entity_type not in {"seller_target", "buyer_intent"}:
        raise ValueError("embedding_generate supports seller_target or buyer_intent only.")

    entity_id = _resolve_entity_id(job, expected_entity_type=entity_type)
    if entity_id is None:
        raise ValueError("embedding_generate job requires entity_id.")

    search_doc_id = _optional_uuid(job.payload_json.get("search_doc_id"))
    search_doc = _get_search_doc_for_embedding(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        search_doc_id=search_doc_id,
    )
    full_text = search_doc.get("full_text") or ""
    node_name = "embedding_seller_doc" if entity_type == "seller_target" else "embedding_buyer_intent"
    node_config = _get_default_embedding_node_config(db, node_name)
    input_json = {
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "search_doc_id": str(search_doc["id"]),
        "text": full_text,
    }

    if not full_text.strip():
        _insert_embedding_trace(
            db,
            job=job,
            entity_type=entity_type,
            entity_id=entity_id,
            node_config=node_config,
            status="skipped",
            input_json=input_json,
            parsed_output_json={"reason": "empty_search_doc"},
            latency_ms=0,
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "status": "skipped",
            "reason": "empty_search_doc",
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "search_doc_id": str(search_doc["id"]),
        }

    try:
        embedding_result = call_openai_compatible_embedding(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            model_name=node_config["model_name"],
            input_text=full_text,
            dimensions=node_config["embedding_dimension"],
            timeout_seconds=node_config["timeout_seconds"] or 60,
        )
    except EmbeddingCallError as exc:
        _insert_embedding_trace(
            db,
            job=job,
            entity_type=entity_type,
            entity_id=entity_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=0,
            error_code="embedding_call_failed",
            error_message=str(exc),
        )
        raise

    _update_search_doc_embedding(
        db,
        entity_type=entity_type,
        search_doc_id=search_doc["id"],
        embedding=embedding_result.embedding,
        model_name=node_config["model_name"],
    )
    _insert_embedding_trace(
        db,
        job=job,
        entity_type=entity_type,
        entity_id=entity_id,
        node_config=node_config,
        status="succeeded",
        input_json=input_json,
        parsed_output_json={
            "search_doc_id": str(search_doc["id"]),
            "embedding_dimension": len(embedding_result.embedding),
            "embedding_model": node_config["model_name"],
        },
        latency_ms=embedding_result.latency_ms,
        prompt_tokens=embedding_result.prompt_tokens,
        total_tokens=embedding_result.total_tokens,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "search_doc_id": str(search_doc["id"]),
        "embedding_model": node_config["model_name"],
        "embedding_dimension": len(embedding_result.embedding),
    }


def _handle_recommendation_report_generate(db: Session, job: JobClaim) -> dict[str, object]:
    report_id = _resolve_entity_id(job, expected_entity_type="recommendation_report")
    if report_id is None:
        raise ValueError("recommendation_report_generate job requires a recommendation_report entity_id.")

    report = _get_recommendation_report_for_job(db, report_id)
    session = _get_recommendation_session_for_report(db, report["session_id"])
    selected_items = _get_selected_items_for_recommendation_report(
        db,
        session_id=report["session_id"],
        selected_item_ids=report["selected_item_ids_json"],
    )
    context_json = _build_recommendation_report_context(
        report=report,
        session=session,
        selected_items=selected_items,
    )
    fallback_markdown = report.get("markdown_content") or _build_fallback_recommendation_report_markdown(
        session=session,
        selected_items=selected_items,
        title=report.get("title") or "推荐报告",
        report_type=report["report_type"],
    )

    try:
        node_config = _get_default_node_config(db, "recommendation_report_writer")
    except Exception as exc:
        _update_recommendation_report_generated(
            db,
            report_id=report_id,
            markdown_content=fallback_markdown,
            generated_by_model="rule_template_v0",
            prompt_version=None,
            metadata_patch={
                "generation_mode": "fallback",
                "fallback_reason": "model_node_config_error",
                "fallback_error": str(exc),
                "job_id": str(job.id),
            },
        )
        _insert_recommendation_report_message(
            db,
            report_id=report_id,
            session_id=report["session_id"],
            markdown_content=fallback_markdown,
            job_id=job.id,
            generation_mode="fallback",
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "report_id": str(report_id),
            "generation_mode": "fallback",
            "fallback_reason": "model_node_config_error",
        }

    prompt_messages = _render_prompt_messages(node_config, {"context_json": context_json})
    input_json = {
        "report_id": str(report_id),
        "session_id": str(report["session_id"]),
        "report_type": report["report_type"],
        "selected_item_count": len(selected_items),
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
            timeout_seconds=node_config["timeout_seconds"] or 180,
            response_format=node_config["response_format"],
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_recommendation_report_llm_trace(
            db,
            job=job,
            report_id=report_id,
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
        _update_recommendation_report_generated(
            db,
            report_id=report_id,
            markdown_content=fallback_markdown,
            generated_by_model="rule_template_v0",
            prompt_version=node_config["prompt_version"],
            metadata_patch={
                "generation_mode": "fallback",
                "fallback_reason": "llm_call_failed",
                "fallback_error": str(exc),
                "job_id": str(job.id),
            },
        )
        _insert_recommendation_report_message(
            db,
            report_id=report_id,
            session_id=report["session_id"],
            markdown_content=fallback_markdown,
            job_id=job.id,
            generation_mode="fallback",
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "report_id": str(report_id),
            "generation_mode": "fallback",
            "fallback_reason": "llm_call_failed",
            "trace_created": True,
        }

    markdown_content = (llm_result.raw_output_text or "").strip()
    if not markdown_content:
        markdown_content = fallback_markdown
        generation_mode = "fallback"
        schema_validation_json = {"valid": False, "error": "LLM output is empty."}
    else:
        generation_mode = "llm"
        schema_validation_json = {"valid": True, "output_mode": "markdown"}

    _insert_recommendation_report_llm_trace(
        db,
        job=job,
        report_id=report_id,
        node_config=node_config,
        status="succeeded" if generation_mode == "llm" else "failed",
        input_json=input_json,
        prompt_messages_json=prompt_messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=llm_result.parsed_output_json,
        schema_validation_json=schema_validation_json,
        latency_ms=llm_result.latency_ms,
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
    )
    _update_recommendation_report_generated(
        db,
        report_id=report_id,
        markdown_content=markdown_content,
        generated_by_model=node_config["model_name"] if generation_mode == "llm" else "rule_template_v0",
        prompt_version=node_config["prompt_version"],
        metadata_patch={
            "generation_mode": generation_mode,
            "job_id": str(job.id),
            "trace_created": True,
            "llm_model_name": node_config["model_name"],
        },
    )
    _insert_recommendation_report_message(
        db,
        report_id=report_id,
        session_id=report["session_id"],
        markdown_content=markdown_content,
        job_id=job.id,
        generation_mode=generation_mode,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "report_id": str(report_id),
        "generation_mode": generation_mode,
        "model_name": node_config["model_name"],
        "prompt_version": node_config["prompt_version"],
        "trace_created": True,
    }


def _handle_recommendation_rerank(db: Session, job: JobClaim) -> dict[str, object]:
    session_id = _resolve_entity_id(job, expected_entity_type="recommendation_session")
    if session_id is None:
        raise ValueError("recommendation_rerank job requires a recommendation_session entity_id.")

    mode = str(job.payload_json.get("mode") or "")
    query = str(job.payload_json.get("query") or "").strip()
    candidates = job.payload_json.get("candidates") or []
    if mode not in {"buyer_to_target", "target_to_buyer"}:
        raise ValueError("recommendation_rerank job requires mode buyer_to_target or target_to_buyer.")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("recommendation_rerank job requires at least two candidates.")

    node_config = _get_default_rerank_node_config(db, "recommendation_reranker")
    documents = _build_rerank_documents(db, mode=mode, candidates=candidates)
    input_json = {
        "session_id": str(session_id),
        "mode": mode,
        "query": query,
        "candidate_count": len(candidates),
        "documents": [
            {
                "index": index,
                "candidate_key": document["candidate_key"],
                "text_preview": document["text"][:1000],
            }
            for index, document in enumerate(documents)
        ],
    }
    started = time.perf_counter()
    try:
        rerank_result = call_dashscope_compatible_rerank(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            model_name=node_config["model_name"],
            query=query,
            documents=[document["text"] for document in documents],
            top_n=len(documents),
            instruct="Rerank M&A recommendation candidates by fit with the buyer intent or target profile.",
            timeout_seconds=node_config["timeout_seconds"] or 90,
        )
    except RerankCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_rerank_trace(
            db,
            job=job,
            session_id=session_id,
            node_config=node_config,
            status="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=latency_ms,
            total_tokens=None,
            error_code="rerank_call_failed",
            error_message=str(exc),
        )
        raise

    reranked_candidates = _apply_rerank_results_to_candidates(
        candidates=candidates,
        rerank_results=rerank_result.results,
        model_name=rerank_result.model_name,
    )
    _insert_rerank_trace(
        db,
        job=job,
        session_id=session_id,
        node_config=node_config,
        status="succeeded",
        input_json=input_json,
        parsed_output_json={
            "model": rerank_result.model_name,
            "results": [
                {"index": item.index, "relevance_score": item.relevance_score}
                for item in rerank_result.results
            ],
            "reranked_candidates": reranked_candidates,
        },
        latency_ms=rerank_result.latency_ms,
        total_tokens=rerank_result.total_tokens,
    )
    _insert_recommendation_rerank_message(
        db,
        session_id=session_id,
        job_id=job.id,
        reranked_candidates=reranked_candidates,
        model_name=rerank_result.model_name,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "session_id": str(session_id),
        "model_name": rerank_result.model_name,
        "candidate_count": len(candidates),
        "reranked_count": len(reranked_candidates),
        "trace_created": True,
    }


def _handle_model_node_test(db: Session, job: JobClaim) -> dict[str, object]:
    node_id = _resolve_entity_id(job, expected_entity_type="model_node_config")
    if node_id is None:
        node_id = _optional_uuid(job.payload_json.get("node_id"))
    if node_id is None:
        raise ValueError("model_node_test job requires a model_node_config entity_id.")

    node_config = _get_model_node_config_by_id(db, node_id)
    node_type = str(node_config["node_type"])
    if node_type in {"llm", "parser", "research"}:
        return _handle_model_chat_node_test(db, job=job, node_config=node_config)
    if node_type == "embedding":
        return _handle_model_embedding_node_test(db, job=job, node_config=node_config)
    if node_type == "rerank":
        return _handle_model_rerank_node_test(db, job=job, node_config=node_config)
    if node_type == "ocr":
        return _handle_model_ocr_node_test(db, job=job, node_config=node_config)
    raise ValueError(f"Unsupported model_node_test node_type: {node_type}")


def _handle_model_chat_node_test(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
) -> dict[str, object]:
    messages = _model_node_test_messages(job, node_config)
    trace_type = "llm" if node_config["node_type"] == "llm" else str(node_config["node_type"])
    input_json = _model_node_test_input_json(
        job,
        node_config,
        extra={"messages": _redact_test_messages(messages)},
    )
    started = time.perf_counter()
    try:
        result = call_openai_compatible_chat(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            model_name=node_config["model_name"],
            messages=messages,
            temperature=node_config.get("temperature"),
            top_p=node_config.get("top_p"),
            max_tokens=node_config.get("max_tokens") or 64,
            timeout_seconds=int(job.payload_json.get("timeout_seconds") or node_config["timeout_seconds"]),
            response_format=node_config.get("response_format"),
        )
    except LlmCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_model_node_test_trace(
            db,
            job=job,
            node_config=node_config,
            trace_type=trace_type,
            status="failed",
            input_json=input_json,
            prompt_messages_json=messages,
            parsed_output_json=None,
            raw_output_text=None,
            latency_ms=latency_ms,
            error_code="llm_test_failed",
            error_message=str(exc),
        )
        raise

    output_json = {
        "parsed_output_json": result.parsed_output_json,
        "raw_output_preview": result.raw_output_text[:1000],
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
    }
    _insert_model_node_test_trace(
        db,
        job=job,
        node_config=node_config,
        trace_type=trace_type,
        status="succeeded",
        input_json=input_json,
        prompt_messages_json=messages,
        parsed_output_json=output_json,
        raw_output_text=result.raw_output_text,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
    )
    return _model_node_test_result(job, node_config, "succeeded", output_json, result.latency_ms)


def _handle_model_embedding_node_test(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
) -> dict[str, object]:
    input_text = str(job.payload_json.get("input_text") or "Match-MA embedding connectivity test.")
    input_json = _model_node_test_input_json(
        job,
        node_config,
        extra={"input_preview": input_text[:500]},
    )
    started = time.perf_counter()
    try:
        result = call_openai_compatible_embedding(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            model_name=node_config["model_name"],
            input_text=input_text,
            dimensions=node_config.get("embedding_dimension"),
            timeout_seconds=int(job.payload_json.get("timeout_seconds") or node_config["timeout_seconds"]),
        )
    except EmbeddingCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_model_node_test_trace(
            db,
            job=job,
            node_config=node_config,
            trace_type="embedding",
            status="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=latency_ms,
            error_code="embedding_test_failed",
            error_message=str(exc),
        )
        raise

    output_json = {
        "embedding_dimension": len(result.embedding),
        "embedding_preview": result.embedding[:8],
        "prompt_tokens": result.prompt_tokens,
        "total_tokens": result.total_tokens,
    }
    _insert_model_node_test_trace(
        db,
        job=job,
        node_config=node_config,
        trace_type="embedding",
        status="succeeded",
        input_json=input_json,
        parsed_output_json=output_json,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        total_tokens=result.total_tokens,
    )
    return _model_node_test_result(job, node_config, "succeeded", output_json, result.latency_ms)


def _handle_model_rerank_node_test(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
) -> dict[str, object]:
    query = str(
        job.payload_json.get("query")
        or job.payload_json.get("input_text")
        or "Which target best matches healthcare growth capital?"
    )
    documents = job.payload_json.get("documents")
    if not isinstance(documents, list) or not documents:
        documents = [
            "Healthcare target with stable net profit and consolidation potential.",
            "Consumer retail business with limited strategic fit.",
        ]
    documents = [str(document) for document in documents]
    input_json = _model_node_test_input_json(
        job,
        node_config,
        extra={
            "query_preview": query[:500],
            "document_count": len(documents),
            "document_previews": [document[:300] for document in documents[:5]],
        },
    )
    started = time.perf_counter()
    try:
        result = call_dashscope_compatible_rerank(
            base_url=node_config["base_url"],
            api_key_secret_ref=node_config["api_key_secret_ref"],
            model_name=node_config["model_name"],
            query=query,
            documents=documents,
            top_n=int(job.payload_json.get("top_n") or min(len(documents), 5)),
            instruct="Connectivity test for Match-MA rerank node.",
            timeout_seconds=int(job.payload_json.get("timeout_seconds") or node_config["timeout_seconds"]),
        )
    except RerankCallError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        _insert_model_node_test_trace(
            db,
            job=job,
            node_config=node_config,
            trace_type="rerank",
            status="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=latency_ms,
            error_code="rerank_test_failed",
            error_message=str(exc),
        )
        raise

    output_json = {
        "model": result.model_name,
        "results": [
            {"index": item.index, "relevance_score": item.relevance_score}
            for item in result.results
        ],
        "total_tokens": result.total_tokens,
    }
    _insert_model_node_test_trace(
        db,
        job=job,
        node_config=node_config,
        trace_type="rerank",
        status="succeeded",
        input_json=input_json,
        parsed_output_json=output_json,
        latency_ms=result.latency_ms,
        total_tokens=result.total_tokens,
    )
    return _model_node_test_result(job, node_config, "succeeded", output_json, result.latency_ms)


def _handle_model_ocr_node_test(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
) -> dict[str, object]:
    text_hint = str(job.payload_json.get("mock_extracted_text") or job.payload_json.get("input_text") or "")
    ocr_input = OcrInput(
        attachment_id="model-node-test",
        file_name=str(job.payload_json.get("file_name") or "model-node-test.txt"),
        file_type=str(job.payload_json.get("file_type") or "txt"),
        mime_type=str(job.payload_json.get("mime_type") or "text/plain"),
        file_size=len(text_hint.encode("utf-8")) if text_hint else None,
        storage_path=str(job.payload_json.get("storage_path") or "mock://model-node-test"),
        metadata_json={
            "storage_backend": "mock",
            "storage_uri": "mock://model-node-test",
            "text_capture_source": "model_node_test_payload" if text_hint else None,
        },
        extracted_text_hint=text_hint,
    )
    input_json = _model_node_test_input_json(
        job,
        node_config,
        extra=build_attachment_ocr_input_json(node_config=node_config, ocr_input=ocr_input),
    )
    result = call_attachment_ocr(node_config=node_config, ocr_input=ocr_input)
    output_json = {
        **result.parsed_output_json,
        "terminal_parse_status": result.terminal_parse_status,
        "text_length": len(result.extracted_text),
    }
    _insert_model_node_test_trace(
        db,
        job=job,
        node_config=node_config,
        trace_type="ocr",
        status=result.trace_status,
        input_json=input_json,
        raw_output_text=result.raw_output_text,
        parsed_output_json=output_json,
        latency_ms=result.latency_ms,
        error_message=result.error_message,
    )
    return _model_node_test_result(job, node_config, result.trace_status, output_json, result.latency_ms)


def _resolve_business_update_id(job: JobClaim) -> UUID | None:
    if job.entity_type == "business_update" and job.entity_id is not None:
        return job.entity_id

    payload_value = job.payload_json.get("business_update_id")
    if not payload_value:
        return None
    return UUID(str(payload_value))


def _resolve_entity_id(job: JobClaim, *, expected_entity_type: str) -> UUID | None:
    if job.entity_type == expected_entity_type and job.entity_id is not None:
        return job.entity_id
    payload_value = job.payload_json.get(f"{expected_entity_type}_id") or job.payload_json.get("entity_id")
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


def _get_seller_target_for_parse(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, target_type, target_subject_name, recommendation_status, information_status,
              industry_primary, industry_secondary, registered_country,
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


def _get_buyer_intent_for_parse(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, status, pause_reason, contact_name,
              contact_info_json, raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_valuation_yuan, market_cap_range_summary,
              min_market_cap_yuan, max_market_cap_yuan,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, listing_board_requirement_summary,
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


def _get_attachment_for_ocr(db: Session, attachment_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, file_name, file_type, mime_type, file_size, storage_path,
              parse_status, metadata_json, uploaded_at::text as uploaded_at
            from attachment
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Attachment not found: {attachment_id}")
    return _json_safe_dict(row)


def _attachment_mock_extracted_text(job: JobClaim, attachment: dict[str, Any]) -> str:
    payload_text = job.payload_json.get("mock_extracted_text")
    metadata_json = attachment.get("metadata_json") if isinstance(attachment.get("metadata_json"), dict) else {}
    metadata_text = metadata_json.get("mock_extracted_text")
    uploaded_text = metadata_json.get("uploaded_text_content")
    local_file_text = _attachment_local_text_content(attachment)
    text_value = payload_text if payload_text is not None else metadata_text or uploaded_text or local_file_text
    if text_value is None:
        return ""
    return str(text_value).strip()


def _attachment_ocr_input(
    job: JobClaim,
    *,
    attachment_id: UUID,
    attachment: dict[str, Any],
) -> OcrInput:
    metadata_json = attachment.get("metadata_json") if isinstance(attachment.get("metadata_json"), dict) else {}
    return OcrInput(
        attachment_id=str(attachment_id),
        file_name=str(attachment.get("file_name") or ""),
        file_type=str(attachment["file_type"]) if attachment.get("file_type") is not None else None,
        mime_type=str(attachment["mime_type"]) if attachment.get("mime_type") is not None else None,
        file_size=int(attachment["file_size"]) if attachment.get("file_size") is not None else None,
        storage_path=str(attachment["storage_path"]) if attachment.get("storage_path") is not None else None,
        metadata_json=metadata_json,
        extracted_text_hint=_attachment_mock_extracted_text(job, attachment),
    )


def _handle_pdf_attachment_ocr(
    db: Session,
    job: JobClaim,
    *,
    attachment_id: UUID,
    attachment: dict[str, Any],
    node_config: dict[str, Any],
) -> dict[str, object] | None:
    if not _is_pdf_attachment(attachment):
        return None

    settings = get_settings()
    file_bytes = _attachment_file_bytes(attachment, max_bytes=settings.attachment_max_upload_bytes)
    inspection = inspect_pdf_text_layer(
        file_bytes,
        page_limit=settings.pdf_text_detection_page_limit,
        min_total_chars=settings.pdf_text_detection_min_chars,
        max_chars=settings.attachment_text_capture_max_bytes,
    )
    _patch_attachment_metadata(
        db,
        attachment_id,
        {
            "last_pdf_kind": inspection.pdf_kind,
            "last_pdf_text_detection": {
                "pdf_kind": inspection.pdf_kind,
                "page_count": inspection.page_count,
                "sampled_page_count": inspection.sampled_page_count,
                "extracted_char_count": inspection.extracted_char_count,
                "threshold_chars": inspection.threshold_chars,
                "error_message": inspection.error_message,
            },
        },
    )

    if inspection.is_text_pdf:
        text_path = _save_ocr_text_artifact(
            attachment_id=attachment_id,
            parsed_document_id=None,
            content=inspection.extracted_text,
            suffix="pdf-text.txt",
        )
        parsed_document_id = _insert_parsed_document_for_ocr(
            db,
            attachment_id=attachment_id,
            parse_status="parsed",
            extracted_text=inspection.extracted_text,
            error_message=None,
            parser_name="pdf_text_layer",
            parser_version="pypdf",
            text_path=text_path,
            page_count=inspection.page_count,
        )
        evidence_id = _insert_ocr_evidence_span(
            db,
            attachment_id=attachment_id,
            parsed_document_id=parsed_document_id,
            job_id=job.id,
            text_excerpt=inspection.extracted_text,
        )
        _update_attachment_parse_terminal(
            db,
            attachment_id=attachment_id,
            parse_status="parsed",
            job_id=job.id,
            parsed_document_id=parsed_document_id,
            evidence_id=evidence_id,
            text_length=len(inspection.extracted_text),
            metadata_patch={
                "last_ocr_provider": "pdf_text_layer",
                "last_pdf_kind": inspection.pdf_kind,
            },
        )
        touched_seller_target_count = _touch_seller_targets_linked_to_attachment(db, attachment_id)
        child_parse_jobs = _enqueue_linked_parse_jobs_after_ocr(
            db,
            job=job,
            attachment_id=attachment_id,
            parsed_document_id=parsed_document_id,
            evidence_id=evidence_id,
            extracted_text=inspection.extracted_text,
        )
        business_update_process_job = _enqueue_business_update_process_after_ocr(
            db,
            job=job,
            attachment_id=attachment_id,
            evidence_id=evidence_id,
            extracted_text=inspection.extracted_text,
        )
        _insert_ocr_trace(
            db,
            job=job,
            attachment_id=attachment_id,
            node_config=node_config,
            status="succeeded",
            input_json={
                "attachment_id": str(attachment_id),
                "provider": "pdf_text_layer",
                "pdf_text_detection": {
                    "pdf_kind": inspection.pdf_kind,
                    "page_count": inspection.page_count,
                    "sampled_page_count": inspection.sampled_page_count,
                    "extracted_char_count": inspection.extracted_char_count,
                    "threshold_chars": inspection.threshold_chars,
                },
            },
            raw_output_text=inspection.extracted_text,
            parsed_output_json={
                "execution_mode": "pdf_text_layer",
                "pdf_kind": inspection.pdf_kind,
                "parsed_document_id": str(parsed_document_id),
                "evidence_id": str(evidence_id),
                "child_parse_jobs": child_parse_jobs,
                "business_update_process_job": business_update_process_job,
            },
            latency_ms=0,
            error_message=None,
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "attachment_id": str(attachment_id),
            "parse_status": "parsed",
            "provider": "pdf_text_layer",
            "pdf_kind": inspection.pdf_kind,
            "parsed_document_id": str(parsed_document_id),
            "evidence_id": str(evidence_id),
            "text_length": len(inspection.extracted_text),
            "touched_seller_target_count": touched_seller_target_count,
            "child_parse_jobs": child_parse_jobs,
            "child_parse_job_count": len(child_parse_jobs),
            "business_update_process_job": business_update_process_job,
        }

    if settings.ocr_provider.strip().lower() != "doc2x":
        return None
    doc2x_api_key = settings.effective_doc2x_api_key
    if not doc2x_api_key:
        raise ValueError("DOC2X_API_KEY is required when OCR_PROVIDER=doc2x.")

    try:
        submit_result = submit_doc2x_pdf(
            base_url=settings.doc2x_base_url,
            api_key=doc2x_api_key,
            file_bytes=file_bytes,
            model=settings.doc2x_model,
            timeout_seconds=settings.doc2x_upload_timeout_seconds,
        )
    except Doc2xCallError as exc:
        _update_attachment_parse_terminal_without_document(
            db,
            attachment_id=attachment_id,
            parse_status="failed",
            job_id=job.id,
            metadata_patch={
                "last_ocr_status": "failed",
                "last_ocr_provider": "doc2x",
                "last_pdf_kind": inspection.pdf_kind,
                "last_doc2x_error": str(exc),
            },
        )
        _mark_business_updates_blocked_by_attachment_ocr(
            db,
            attachment_id=attachment_id,
            job_id=job.id,
            error_message=str(exc),
        )
        raise
    poll_job = _enqueue_doc2x_poll_job(
        db,
        parent_job_id=job.id,
        attachment_id=attachment_id,
        business_update_id=_optional_uuid(job.payload_json.get("business_update_id")),
        doc2x_uid=submit_result.uid,
        started_epoch=time.time(),
        source_payload=job.payload_json,
        run_after_seconds=settings.doc2x_poll_interval_seconds,
    )
    _patch_attachment_metadata(
        db,
        attachment_id,
        {
            "last_ocr_status": "provider_submitted",
            "last_ocr_provider": "doc2x",
            "last_doc2x_uid": submit_result.uid,
            "last_pdf_kind": inspection.pdf_kind,
            "last_doc2x_poll_job_id": str(poll_job["id"]),
        },
    )
    _insert_ocr_trace(
        db,
        job=job,
        attachment_id=attachment_id,
        node_config={
            **node_config,
            "provider_name": "doc2x",
            "model_name": settings.doc2x_model,
        },
        status="succeeded",
        input_json={
            "attachment_id": str(attachment_id),
            "provider": "doc2x",
            "doc2x_uid": submit_result.uid,
            "pdf_text_detection": {
                "pdf_kind": inspection.pdf_kind,
                "page_count": inspection.page_count,
                "sampled_page_count": inspection.sampled_page_count,
                "extracted_char_count": inspection.extracted_char_count,
                "threshold_chars": inspection.threshold_chars,
                "error_message": inspection.error_message,
            },
        },
        raw_output_text=None,
        parsed_output_json={
            "provider": "doc2x",
            "status": "submitted",
            "doc2x_uid": submit_result.uid,
            "poll_job": _json_safe_dict(poll_job),
        },
        latency_ms=submit_result.latency_ms,
        error_message=None,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "attachment_id": str(attachment_id),
        "parse_status": "parsing",
        "provider": "doc2x",
        "provider_status": "submitted",
        "doc2x_uid": submit_result.uid,
        "poll_job": _json_safe_dict(poll_job),
        "pdf_kind": inspection.pdf_kind,
    }


def _handle_office_attachment_ocr(
    db: Session,
    job: JobClaim,
    *,
    attachment_id: UUID,
    attachment: dict[str, Any],
    node_config: dict[str, Any],
) -> dict[str, object] | None:
    document_kind = office_document_kind(
        file_name=str(attachment.get("file_name") or ""),
        file_type=str(attachment.get("file_type") or ""),
        mime_type=str(attachment.get("mime_type") or ""),
    )
    if document_kind is None:
        return None

    settings = get_settings()
    file_bytes = _attachment_file_bytes(attachment, max_bytes=settings.attachment_max_upload_bytes)
    inspection = inspect_office_text(
        file_bytes,
        file_name=str(attachment.get("file_name") or ""),
        file_type=str(attachment.get("file_type") or ""),
        mime_type=str(attachment.get("mime_type") or ""),
        max_chars=settings.attachment_text_capture_max_bytes,
    )
    _patch_attachment_metadata(
        db,
        attachment_id,
        {
            "last_office_kind": inspection.document_kind,
            "last_office_text_extraction": {
                "document_kind": inspection.document_kind,
                "parser_name": inspection.parser_name,
                "parser_version": inspection.parser_version,
                "extracted_char_count": inspection.extracted_char_count,
                "item_count": inspection.item_count,
                "error_message": inspection.error_message,
            },
        },
    )
    if not inspection.has_text:
        return None

    text_path = _save_ocr_text_artifact(
        attachment_id=attachment_id,
        parsed_document_id=None,
        content=inspection.extracted_text,
        suffix=f"{inspection.document_kind}-text.txt",
    )
    parsed_document_id = _insert_parsed_document_for_ocr(
        db,
        attachment_id=attachment_id,
        parse_status="parsed",
        extracted_text=inspection.extracted_text,
        error_message=None,
        parser_name=inspection.parser_name,
        parser_version=inspection.parser_version,
        text_path=text_path,
        page_count=inspection.item_count or None,
    )
    evidence_id = _insert_ocr_evidence_span(
        db,
        attachment_id=attachment_id,
        parsed_document_id=parsed_document_id,
        job_id=job.id,
        text_excerpt=inspection.extracted_text,
    )
    _update_attachment_parse_terminal(
        db,
        attachment_id=attachment_id,
        parse_status="parsed",
        job_id=job.id,
        parsed_document_id=parsed_document_id,
        evidence_id=evidence_id,
        text_length=len(inspection.extracted_text),
        metadata_patch={
            "last_ocr_provider": "office_text_layer",
            "last_office_kind": inspection.document_kind,
        },
    )
    touched_seller_target_count = _touch_seller_targets_linked_to_attachment(db, attachment_id)
    child_parse_jobs = _enqueue_linked_parse_jobs_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        parsed_document_id=parsed_document_id,
        evidence_id=evidence_id,
        extracted_text=inspection.extracted_text,
    )
    business_update_process_job = _enqueue_business_update_process_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        evidence_id=evidence_id,
        extracted_text=inspection.extracted_text,
    )
    _insert_ocr_trace(
        db,
        job=job,
        attachment_id=attachment_id,
        node_config=node_config,
        status="succeeded",
        input_json={
            "attachment_id": str(attachment_id),
            "provider": "office_text_layer",
            "office_text_extraction": {
                "document_kind": inspection.document_kind,
                "parser_name": inspection.parser_name,
                "parser_version": inspection.parser_version,
                "extracted_char_count": inspection.extracted_char_count,
                "item_count": inspection.item_count,
            },
        },
        raw_output_text=inspection.extracted_text,
        parsed_output_json={
            "execution_mode": "office_text_layer",
            "office_kind": inspection.document_kind,
            "parsed_document_id": str(parsed_document_id),
            "evidence_id": str(evidence_id),
            "child_parse_jobs": child_parse_jobs,
            "business_update_process_job": business_update_process_job,
        },
        latency_ms=0,
        error_message=None,
    )
    return {
        "handled": True,
        "job_type": job.job_type,
        "attachment_id": str(attachment_id),
        "parse_status": "parsed",
        "provider": "office_text_layer",
        "office_kind": inspection.document_kind,
        "parsed_document_id": str(parsed_document_id),
        "evidence_id": str(evidence_id),
        "text_length": len(inspection.extracted_text),
        "touched_seller_target_count": touched_seller_target_count,
        "child_parse_jobs": child_parse_jobs,
        "child_parse_job_count": len(child_parse_jobs),
        "business_update_process_job": business_update_process_job,
    }


def _is_pdf_attachment(attachment: dict[str, Any]) -> bool:
    file_type = str(attachment.get("file_type") or "").lower()
    mime_type = str(attachment.get("mime_type") or "").split(";")[0].strip().lower()
    return file_type == "pdf" or mime_type == "application/pdf"


def _attachment_local_text_content(attachment: dict[str, Any], *, max_chars: int = 200_000) -> str | None:
    settings = get_settings()
    return read_local_text_content(
        attachment,
        storage_dir=settings.attachment_storage_dir,
        max_bytes=max_chars,
    )


def _attachment_file_bytes(attachment: dict[str, Any], *, max_bytes: int | None = None) -> bytes:
    settings = get_settings()
    data = read_attachment_bytes(
        attachment,
        storage_dir=settings.attachment_storage_dir,
        max_bytes=max_bytes or settings.attachment_max_upload_bytes,
        s3_endpoint_url=settings.effective_attachment_s3_endpoint_url,
        s3_region=settings.effective_attachment_s3_region,
        s3_bucket=settings.effective_attachment_s3_bucket,
        s3_access_key_id=settings.effective_attachment_s3_access_key_id,
        s3_secret_access_key=settings.effective_attachment_s3_secret_access_key,
        s3_force_path_style=settings.attachment_s3_force_path_style,
    )
    if data is None:
        raise AttachmentStorageError("Attachment file bytes are not available from configured storage.")
    return data


def _parse_source_context(
    job: JobClaim,
    *,
    default_source_type: str,
    default_source_label: str,
) -> dict[str, Any]:
    evidence_id = _optional_uuid(job.payload_json.get("evidence_id"))
    attachment_id = _optional_uuid(job.payload_json.get("attachment_id"))
    parsed_document_id = _optional_uuid(job.payload_json.get("parsed_document_id"))
    return {
        "source_type": str(job.payload_json.get("source_type") or default_source_type),
        "source_id": _optional_uuid(job.payload_json.get("source_id")) or job.id,
        "source_label": str(job.payload_json.get("source_label") or default_source_label),
        "evidence_id": evidence_id,
        "attachment_id": attachment_id,
        "parsed_document_id": parsed_document_id,
    }


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


def _get_recommendation_report_for_job(db: Session, report_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, session_id, report_type, selected_item_ids_json, title,
              markdown_content, status, generated_by_model, prompt_version,
              metadata_json
            from recommendation_report
            where id = :report_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Recommendation report not found: {report_id}")
    return dict(row)


def _get_recommendation_session_for_report(db: Session, session_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, mode, buyer_intent_id, buyer_party_id, seller_target_id,
              anonymous_input_snapshot, initial_condition_snapshot_json,
              latest_condition_snapshot_json, selected_count, report_count,
              metadata_json, created_at::text as created_at, updated_at::text as updated_at
            from recommendation_session
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Recommendation session not found: {session_id}")
    return _json_safe_dict(row)


def _get_selected_items_for_recommendation_report(
    db: Session,
    *,
    session_id: UUID,
    selected_item_ids: list[Any] | None,
) -> list[dict[str, Any]]:
    where = [
        "ri.session_id = :session_id",
        "ri.team_id = :team_id",
        "ri.workspace_id = :workspace_id",
        "ri.canceled_at is null",
    ]
    params: dict[str, Any] = {
        "session_id": session_id,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if selected_item_ids:
        where.append("ri.id in :selected_item_ids")
        params["selected_item_ids"] = tuple(UUID(str(item)) for item in selected_item_ids)

    statement = text(
        f"""
        select
          ri.id, ri.session_id, ri.mode,
          ri.seller_target_id, st.target_name as seller_target_name,
          ri.buyer_intent_id, bi.intent_name as buyer_intent_name,
          ri.buyer_party_id, bp.buyer_name,
          ri.rank_at_selection, ri.recommendation_level, ri.match_summary,
          ri.risk_summary, ri.gap_summary, ri.reason_snapshot,
          ri.evidence_snapshot_json, ri.selected_at::text as selected_at,
          ri.metadata_json
        from recommendation_selected_item ri
        left join seller_target st on st.id = ri.seller_target_id
        left join buyer_intent bi on bi.id = ri.buyer_intent_id
        left join buyer_party bp on bp.id = ri.buyer_party_id
        where {' and '.join(where)}
        order by ri.rank_at_selection nulls last, ri.selected_at asc
        """
    )
    if selected_item_ids:
        statement = statement.bindparams(bindparam("selected_item_ids", expanding=True))

    rows = db.execute(statement, params).mappings().all()
    return [_json_safe_dict(row) for row in rows]


def _build_recommendation_report_context(
    *,
    report: dict[str, Any],
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report": {
            "id": str(report["id"]),
            "report_type": report["report_type"],
            "title": report.get("title"),
        },
        "session": session,
        "selected_items": selected_items,
        "instructions": {
            "source_policy": "Use only provided context. State missing information as review needed.",
            "output_format": "Chinese Markdown",
            "generation_boundary": "This is a draft report for human review, not an external final document.",
        },
    }


def _build_fallback_recommendation_report_markdown(
    *,
    session: dict[str, Any],
    selected_items: list[dict[str, Any]],
    title: str,
    report_type: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- 推荐会话：`{session['id']}`",
        f"- 推荐方向：{session['mode']}",
        f"- 报告类型：{report_type}",
        f"- 已采用候选数：{len(selected_items)}",
        "",
        "## 推荐清单",
        "",
    ]
    for index, item in enumerate(selected_items, start=1):
        lines.extend(
            [
                f"### {index}. {item.get('seller_target_name') or '未绑定标的'} / {item.get('buyer_intent_name') or '未绑定意向'}",
                "",
                f"- 买家：{item.get('buyer_name') or '未绑定买家'}",
                f"- 推荐等级：{item.get('recommendation_level') or '未评级'}",
                f"- 匹配理由：{item.get('match_summary') or '暂无'}",
                f"- 信息缺口：{item.get('gap_summary') or '暂无'}",
                f"- 风险提示：{item.get('risk_summary') or '暂无'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 后续建议",
            "",
            "- 由业务人员复核推荐理由、信息缺口和风险提示。",
            "- 复核通过后，在买家-标的关系中继续记录推荐、反馈、尽调和终止等进展。",
        ]
    )
    return "\n".join(lines)


def _get_default_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
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


def _get_default_embedding_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.embedding_dimension,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'embedding'
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
        raise ValueError(f"Default embedding node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    if not config.get("embedding_dimension"):
        raise ValueError(f"Embedding dimension is not configured for node: {node_name}")
    return config


def _get_default_rerank_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'rerank'
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
        raise ValueError(f"Default rerank node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    return config


def _get_default_ocr_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'ocr'
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
        raise ValueError(f"Default OCR node is not configured: {node_name}")
    return dict(row)


def _get_model_node_config_by_id(db: Session, node_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.node_type,
              node.model_name,
              node.temperature,
              node.top_p,
              node.max_tokens,
              node.timeout_seconds,
              node.response_format,
              node.embedding_dimension,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.id = :node_id
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_id": node_id,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Model node is not configured or inactive: {node_id}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {config['node_name']}")
    if config.get("node_type") == "embedding" and not config.get("embedding_dimension"):
        raise ValueError(f"Embedding dimension is not configured for node: {config['node_name']}")
    return config


def _build_rerank_documents(
    db: Session,
    *,
    mode: str,
    candidates: list[Any],
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_key = _candidate_key(candidate)
        document_text = _get_candidate_search_doc_text(db, mode=mode, candidate=candidate)
        if not document_text:
            document_text = _candidate_fallback_text(candidate)
        documents.append({"candidate_key": candidate_key, "text": document_text})
    return documents


def _get_candidate_search_doc_text(db: Session, *, mode: str, candidate: dict[str, Any]) -> str | None:
    if mode == "buyer_to_target":
        seller_target_id = _optional_uuid(candidate.get("seller_target_id"))
        if not seller_target_id:
            return None
        row = db.execute(
            text(
                """
                select full_text
                from seller_target_search_doc
                where seller_target_id = :seller_target_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and doc_type = 'profile'
                order by updated_at desc
                limit 1
                """
            ),
            {
                "seller_target_id": seller_target_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).mappings().one_or_none()
    else:
        buyer_intent_id = _optional_uuid(candidate.get("buyer_intent_id"))
        if not buyer_intent_id:
            return None
        row = db.execute(
            text(
                """
                select full_text
                from buyer_intent_search_doc
                where buyer_intent_id = :buyer_intent_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                order by updated_at desc
                limit 1
                """
            ),
            {
                "buyer_intent_id": buyer_intent_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
            },
        ).mappings().one_or_none()
    return str(row["full_text"]) if row and row["full_text"] else None


def _candidate_fallback_text(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("seller_target_name"),
        candidate.get("buyer_intent_name"),
        candidate.get("buyer_name"),
        candidate.get("match_summary"),
        candidate.get("gap_summary"),
        candidate.get("risk_summary"),
        candidate.get("evidence_json"),
    ]
    return "\n".join(str(part) for part in parts if part)


def _candidate_key(candidate: dict[str, Any]) -> str:
    return "|".join(
        str(candidate.get(key) or "")
        for key in ["mode", "buyer_intent_id", "seller_target_id"]
    )


def _apply_rerank_results_to_candidates(
    *,
    candidates: list[Any],
    rerank_results: list[Any],
    model_name: str,
) -> list[dict[str, Any]]:
    normalized_candidates = [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
    score_by_index = {item.index: item.relevance_score for item in rerank_results}
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(normalized_candidates):
        rerank_score = float(score_by_index.get(index, 0.0))
        original_score = float(candidate.get("score") or 0)
        rerank_boost = round(max(0.0, min(rerank_score, 1.0)) * 15, 2)
        final_score = min(round(original_score + rerank_boost, 2), 100.0)
        evidence_json = candidate.get("evidence_json") if isinstance(candidate.get("evidence_json"), dict) else {}
        score_json = evidence_json.get("score") if isinstance(evidence_json.get("score"), dict) else {}
        candidate["score"] = final_score
        candidate["recommendation_level"] = _recommendation_level_from_score(final_score)
        candidate["evidence_json"] = {
            **evidence_json,
            "score": {
                **score_json,
                "rerank_score": rerank_score,
                "rerank_boost": rerank_boost,
                "rerank_model": model_name,
                "final_score": final_score,
            },
        }
        output.append(candidate)
    output.sort(
        key=lambda item: (
            item.get("evidence_json", {}).get("score", {}).get("rerank_score", 0),
            item.get("score") or 0,
        ),
        reverse=True,
    )
    for rank, candidate in enumerate(output, start=1):
        candidate["rank"] = rank
        candidate["evidence_json"]["score"]["rerank_rank"] = rank
    return output


def _recommendation_level_from_score(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 60:
        return "recommended"
    if score >= 35:
        return "possible"
    return "weak"


def _get_search_doc_for_embedding(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    search_doc_id: UUID | None,
) -> dict[str, Any]:
    if entity_type == "seller_target":
        where = "id = :search_doc_id" if search_doc_id else "seller_target_id = :entity_id and doc_type = 'profile'"
        params = {
            "search_doc_id": search_doc_id,
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        }
        row = db.execute(
            text(
                f"""
                select id, seller_target_id as entity_id, full_text
                from seller_target_search_doc
                where {where}
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                limit 1
                """
            ),
            params,
        ).mappings().one_or_none()
    else:
        where = "id = :search_doc_id" if search_doc_id else "buyer_intent_id = :entity_id"
        params = {
            "search_doc_id": search_doc_id,
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        }
        row = db.execute(
            text(
                f"""
                select id, buyer_intent_id as entity_id, full_text
                from buyer_intent_search_doc
                where {where}
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                limit 1
                """
            ),
            params,
        ).mappings().one_or_none()

    if row is None:
        raise ValueError(f"Search doc not found for {entity_type}: {entity_id}")
    return dict(row)


def _update_search_doc_embedding(
    db: Session,
    *,
    entity_type: str,
    search_doc_id: UUID,
    embedding: list[float],
    model_name: str,
) -> None:
    table_name = "seller_target_search_doc" if entity_type == "seller_target" else "buyer_intent_search_doc"
    db.execute(
        text(
            f"""
            update {table_name}
            set embedding = cast(:embedding as vector),
                embedding_model = :model_name,
                embedding_dim = :embedding_dim,
                updated_at = now()
            where id = :search_doc_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "embedding": embedding_to_pgvector_literal(embedding),
            "model_name": model_name,
            "embedding_dim": len(embedding),
            "search_doc_id": search_doc_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )


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


def _attach_multimodal_images(
    messages: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not messages or not images:
        return messages
    updated = [dict(message) for message in messages]
    user_index = next((idx for idx in range(len(updated) - 1, -1, -1) if updated[idx].get("role") == "user"), len(updated) - 1)
    user_message = dict(updated[user_index])
    content = user_message.get("content")
    parts: list[dict[str, Any]]
    if isinstance(content, list):
        parts = list(content)
    else:
        parts = [{"type": "text", "text": str(content or "")}]
    parts.append(
        {
            "type": "text",
            "text": (
                "The following images are business update attachments. "
                "Read them directly, extract only business facts visible in the images, "
                "and cite the attachment id in raw_evidence_text when relevant."
            ),
        }
    )
    for image in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": image["data_url"]},
            }
        )
    user_message["content"] = parts
    updated[user_index] = user_message
    return updated


def _safe_prompt_messages_for_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_messages: list[dict[str, Any]] = []
    for message in messages:
        safe_message = dict(message)
        content = safe_message.get("content")
        if isinstance(content, list):
            safe_parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_url = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
                    url = str(image_url.get("url") or "")
                    safe_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"<redacted data url: {len(url)} chars>",
                            },
                        }
                    )
                else:
                    safe_parts.append(part if isinstance(part, dict) else {"type": "text", "text": str(part)})
            safe_message["content"] = safe_parts
        safe_messages.append(safe_message)
    return safe_messages


def _business_update_raw_text_with_attachments(raw_text: Any, attachment_context: dict[str, Any]) -> str:
    base_text = str(raw_text or "").strip()
    attachment_text = str(attachment_context.get("combined_text") or "").strip()
    if not attachment_text:
        return base_text
    if not base_text:
        return f"Attachment OCR evidence:\n{attachment_text}"
    return f"{base_text}\n\nAttachment OCR evidence:\n{attachment_text}"


def _fetch_seller_targets(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, target_name, target_type, target_subject_name, industry_primary, industry_secondary,
              headquarter_province, headquarter_city, listed_status,
              current_revenue_yuan, current_net_profit_yuan, valuation_yuan,
              valuation_date, asking_price_yuan, asking_price_date, pe_ratio, is_for_sale, can_control,
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
              min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary,
              requires_control, requires_consolidation,
              accepts_minority_investment, preferred_listed_status,
              listing_board_requirement_summary, financing_stage_requirement_summary,
              transaction_type, transaction_types_json, premium_tolerance_summary,
              max_premium_rate, max_debt_ratio, debt_ratio_requirement_summary,
              major_risk_tolerance_summary, buyer_industry_advantage_summary,
              negative_summary, preference_summary, unknown_summary
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
    return _json_safe_value(dict(row))


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."


def _approx_token_count(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def _join_lines(values: Any) -> str:
    if not isinstance(values, list | tuple):
        return str(values or "").strip()
    return "\n".join(str(value).strip() for value in values if value is not None and str(value).strip())


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


BUYER_INTENT_PARSE_FIELDS = {
    "intent_name",
    "raw_requirement_text",
    "intent_summary",
    "parsed_requirement_json",
    "industry_primary",
    "industry_secondary",
    "region_scope_summary",
    "region_constraints_json",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_pe",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "market_cap_range_summary",
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

SELLER_TARGET_PARSE_FIELDS = {
    "target_name",
    "target_type",
    "target_subject_name",
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

BUYER_INTENT_PARSE_JSON_FIELDS = {
    "parsed_requirement_json",
    "region_constraints_json",
    "acceptable_control_paths_json",
    "transaction_types_json",
}

BUYER_INTENT_PARSE_NUMERIC_FIELDS = {
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_pe",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "max_premium_rate",
    "max_debt_ratio",
    "desired_equity_ratio_min",
    "desired_equity_ratio_max",
}

YES_NO_LIKE_FIELDS = {
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
}

BUYER_INTENT_TEXT_LIMITS = {
    "intent_name": 300,
}


# Buyer party (acquirer) fields the buyer intent parser may enrich from the same
# requirement material. Enrichment only fills empty party fields; it never
# overwrites existing buyer_party data because a party is shared across intents.
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
            "updated_by": DEFAULT_ADMIN_USER_ID,
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
                "applied_by": DEFAULT_ADMIN_USER_ID,
                "metadata_json": {
                    "source": "seller_target_parser",
                    "normalization_notes": normalization_notes,
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )


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
        if key in BUYER_INTENT_PARSE_JSON_FIELDS:
            changes[key] = value if isinstance(value, (list, dict)) else []
            continue
        text_value = str(value).strip() if value is not None else None
        if text_value and key in BUYER_INTENT_TEXT_LIMITS:
            text_value = text_value[: BUYER_INTENT_TEXT_LIMITS[key]]
        changes[key] = text_value

    changes.setdefault("raw_requirement_text", raw_requirement_text)
    if "parsed_requirement_json" not in changes:
        changes["parsed_requirement_json"] = {
            "source": "buyer_intent_parser",
            "raw_requirement_text": raw_requirement_text,
            "llm_fields": parsed_output_json,
        }
    return {key: value for key, value in changes.items() if value is not None}, notes


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
            "updated_by": DEFAULT_ADMIN_USER_ID,
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
                "applied_by": DEFAULT_ADMIN_USER_ID,
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
            "updated_by": DEFAULT_ADMIN_USER_ID,
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
                "applied_by": DEFAULT_ADMIN_USER_ID,
                "metadata_json": {
                    "source": "buyer_intent_parser",
                    "enrichment": "buyer_party",
                    "proposed_value": _json_safe_value(changes.get(field_path)),
                    "field_value_source": _json_safe_value(source_context),
                },
            },
        )


def _write_field_value_sources(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    source_context: dict[str, Any],
    review_status: str,
) -> None:
    for field_path in diff:
        db.execute(
            text(
                """
                insert into field_value_source (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  value_snapshot_json, source_type, source_id, evidence_id,
                  source_label, confidence, review_status, created_by
                )
                values (
                  :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
                  :value_snapshot_json, :source_type, :source_id, :evidence_id,
                  :source_label, :confidence, :review_status, :created_by
                )
                """
            ).bindparams(bindparam("value_snapshot_json", type_=JSONB)),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_path": field_path,
                "value_snapshot_json": {
                    "value": _json_safe_value(changes.get(field_path)),
                    "source_context": _json_safe_value(source_context),
                },
                "source_type": source_context.get("source_type"),
                "source_id": source_context.get("source_id"),
                "evidence_id": source_context.get("evidence_id"),
                "source_label": source_context.get("source_label"),
                "confidence": source_context.get("confidence"),
                "review_status": review_status,
                "created_by": DEFAULT_ADMIN_USER_ID,
            },
        )


def _diff_json_safe(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    diff: dict[str, tuple[Any, Any]] = {}
    for key, new_value in changes.items():
        old_value = original.get(key)
        if _json_safe_value(old_value) != _json_safe_value(new_value):
            diff[key] = (old_value, new_value)
    return diff


def _normalize_yes_no_like(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"yes", "true", "1", "是", "需要", "要求", "必须", "可以", "可接受", "接受", "likely"}:
        return "likely" if normalized == "likely" else "yes"
    if normalized in {"no", "false", "0", "否", "不需要", "不要求", "不可以", "不可接受", "不接受"}:
        return "no"
    return "unknown"


def _normalize_allowed_enum(value: Any, allowed: set[str]) -> str | None:
    normalized = _normalize_enum_value(value)
    return normalized if normalized in allowed else None


def _normalize_seller_listed_status(value: Any) -> str:
    listed_status = _normalize_listed_status(value)
    if listed_status == "preparing_listing":
        return "pre_ipo"
    return "unknown" if listed_status == "any" else listed_status


def _normalize_listed_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized_key = normalized.replace(" ", "_").replace("-", "_")
    if normalized_key in {"listed", "public", "public_company", "yes", "true", "1"} or normalized in {
        "上市",
        "已上市",
    }:
        return "listed"
    if normalized_key in {
        "unlisted",
        "not_listed",
        "non_listed",
        "private",
        "private_company",
        "non_public",
        "not_public",
        "unquoted",
        "no",
        "false",
        "0",
    } or normalized in {"非上市", "未上市"}:
        return "unlisted"
    if normalized_key in {
        "preparing_listing",
        "preparing_to_list",
        "planned_listing",
        "ipo_candidate",
    } or normalized in {"准备上市", "拟上市", "计划上市"}:
        return "preparing_listing"
    if normalized_key in {"pre_ipo", "preipo"}:
        return "pre_ipo"
    if normalized_key in {"any", "no_preference", "all"} or normalized in {"不限", "均可"}:
        return "any"
    return "unknown"

def _normalize_equity_requirement_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    allowed = {
        "control_required",
        "consolidation_required",
        "minority_acceptable",
        "minority_only",
        "flexible",
        "specific_range",
        "unknown",
    }
    if normalized in allowed:
        return normalized
    if "并表" in normalized:
        return "consolidation_required"
    if "控股" in normalized or "控制" in normalized:
        return "control_required"
    if "参股" in normalized or "少数" in normalized:
        return "minority_acceptable"
    if "灵活" in normalized or "可谈" in normalized:
        return "flexible"
    return None


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
    if action_type == "target_follow_up":
        return _normalize_target_follow_up_changes(proposed_changes)
    return proposed_changes, []


TARGET_FOLLOW_UP_DATE_PATTERNS = (
    ("%Y-%m-%d", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")),
    ("%Y/%m/%d", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")),
    ("%Y.%m.%d", re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}$")),
    ("%Y%m%d", re.compile(r"^\d{8}$")),
)


def _normalize_target_follow_up_changes(
    proposed_changes: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    content = str(proposed_changes.get("content") or "").strip()
    if len(content) > 2000:
        content = content[:2000]
        notes.append("content_truncated_to_2000")

    occurred_on: str | None = None
    raw_date = str(proposed_changes.get("occurred_on") or "").strip()
    if raw_date:
        parsed = _parse_follow_up_date(raw_date)
        if parsed is None:
            notes.append(f"occurred_on_unparseable:{raw_date[:40]}")
        else:
            if parsed > date.today():
                # Year-less dates resolved into the future are almost always
                # last year's follow-ups.
                parsed = _minus_one_year(parsed)
                notes.append("occurred_on_future_shifted_back_one_year")
            occurred_on = parsed.isoformat()

    buyer_names: list[str] = []
    raw_names = proposed_changes.get("buyer_names")
    if isinstance(raw_names, list):
        for raw_name in raw_names:
            name = str(raw_name or "").strip()
            if name and name not in buyer_names:
                buyer_names.append(name)
        if len(buyer_names) > 10:
            buyer_names = buyer_names[:10]
            notes.append("buyer_names_truncated_to_10")

    for key in proposed_changes:
        if key not in {"occurred_on", "content", "buyer_names"}:
            notes.append(f"ignored_unsupported_field:{key}")

    changes: dict[str, Any] = {"content": content, "buyer_names": buyer_names}
    if occurred_on:
        changes["occurred_on"] = occurred_on
    return changes, notes


def _parse_follow_up_date(raw: str) -> date | None:
    from datetime import datetime as _datetime

    for fmt, pattern in TARGET_FOLLOW_UP_DATE_PATTERNS:
        if pattern.match(raw):
            try:
                return _datetime.strptime(raw, fmt).date()
            except ValueError:
                return None
    return None


def _minus_one_year(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value - timedelta(days=366)


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


def _decimal_ratio(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        return Decimal("0")
    bigger = max(left, right)
    smaller = min(left, right)
    try:
        return bigger / smaller
    except Exception:
        return Decimal("0")


def _decimal_to_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


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
            normalized_value = _normalize_field_value(key, value, enum_fields, notes)
            if normalized_value is not _SKIP_FIELD:
                normalized[key] = normalized_value
            continue

        alias = aliases.get(key)
        if alias and alias in allowed_fields:
            normalized_value = _normalize_field_value(alias, value, enum_fields, notes)
            if normalized_value is not _SKIP_FIELD:
                normalized[alias] = normalized_value
            notes.append(f"{key}->{alias}")
            continue

        if isinstance(value, dict) and nested_aliases:
            for child_key, child_value in value.items():
                nested_alias = nested_aliases.get((key, child_key))
                if nested_alias and nested_alias in allowed_fields:
                    normalized_value = _normalize_field_value(
                        nested_alias,
                        child_value,
                        enum_fields,
                        notes,
                    )
                    if normalized_value is not _SKIP_FIELD:
                        normalized[nested_alias] = normalized_value
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

    if field == "listed_status":
        normalized = _normalize_seller_listed_status(value)
    elif field == "preferred_listed_status":
        normalized = _normalize_listed_status(value)
    else:
        normalized = _normalize_enum_value(value)
    allowed_values = enum_fields[field]
    if normalized in allowed_values:
        if normalized != value:
            notes.append(f"{field}:{value}->{normalized}")
        return normalized

    notes.append(f"{field}:{value}->dropped_invalid_enum")
    return _SKIP_FIELD


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

    if action_type in {"seller_fact_update", "target_follow_up"}:
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
                "proposed_changes_json": action["proposed_changes_json"],
                "raw_evidence_text": action["raw_evidence_text"],
                "evidence_id": action.get("evidence_id"),
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


AUTO_APPLY_ACTION_TYPE_ORDER = {
    "seller_fact_update": 0,
    "buyer_intent_update": 1,
    "buyer_seller_relation_update": 2,
    "buyer_intent_target_exclusion": 3,
    # Follow-ups apply last: fact updates must run the post-parse status flip
    # while the target is still in 'parsing'.
    "target_follow_up": 4,
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
    if action["action_type"] == "target_follow_up":
        return apply_target_follow_up_action(db, action, require_accepted=False)
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

    if action["action_type"] == "target_follow_up":
        changes = action["proposed_changes_json"]
        return (
            action["target_entity_type"] == "seller_target"
            and action["target_entity_id"] is not None
            and bool(str(changes.get("content") or "").strip())
        )

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


def _mark_business_update_failed_if_final_attempt(
    db: Session,
    job: JobClaim,
    business_update_id: UUID,
    error_message: str,
) -> None:
    if job.attempt_count < job.max_attempts:
        return
    _mark_business_update_failed(db, business_update_id, job.id, error_message)


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


def _mark_bound_seller_targets_pending_review_after_business_update_parse(
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
            set information_status = 'pending_review',
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
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "metadata_patch": {
                "last_parse_pending_review_job_id": str(job_id),
                "last_parse_pending_review_reason": "business_update_parsed_without_auto_apply",
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
            "updated_by": DEFAULT_ADMIN_USER_ID,
            "metadata_patch": {
                "last_parse_failed_job_id": str(job_id),
                "last_parse_error_message": _truncate_text(error_message, 500),
            },
        },
    )
    return int(result.rowcount or 0)


def _mark_business_updates_blocked_by_attachment_ocr(
    db: Session,
    *,
    attachment_id: UUID,
    job_id: UUID,
    error_message: str | None,
) -> None:
    rows = db.execute(
        text(
            """
            select bu.id as business_update_id, bu.bound_seller_target_ids_json
            from attachment_link al
            join business_update bu
              on bu.id = al.entity_id
             and bu.team_id = al.team_id
             and bu.workspace_id = al.workspace_id
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.attachment_id = :attachment_id
              and al.entity_type = 'business_update'
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    for row in rows:
        business_update_id = row["business_update_id"]
        active = db.execute(
            text(
                """
                select 1
                from background_job bj
                where bj.team_id = :team_id
                  and bj.workspace_id = :workspace_id
                  and bj.id <> :job_id
                  and bj.status in ('queued', 'running', 'retry_waiting')
                  and (
                    (bj.entity_type = 'business_update' and bj.entity_id = :business_update_id)
                    or bj.payload_json ->> 'business_update_id' = :business_update_id_text
                  )
                limit 1
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "job_id": job_id,
                "business_update_id": business_update_id,
                "business_update_id_text": str(business_update_id),
            },
        ).first()
        if active:
            continue
        target_failed_count = _mark_seller_targets_parse_failed(
            db,
            seller_target_ids=_uuid_list(row.get("bound_seller_target_ids_json")),
            job_id=job_id,
            error_message=error_message
            or "Attachment OCR did not produce text, so business update processing could not continue.",
        )
        db.execute(
            text(
                """
                update business_update
                set processing_status = 'failed',
                    metadata_json = metadata_json || :metadata_patch
                where id = :business_update_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and processing_status = 'processing'
                """
            ).bindparams(bindparam("metadata_patch", type_=JSONB)),
            {
                "business_update_id": business_update_id,
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "metadata_patch": {
                    "last_processed_job_id": str(job_id),
                    "last_processing_result": "attachment_ocr_blocked",
                    "last_error_message": error_message
                    or "Attachment OCR did not produce text, so business update processing could not continue.",
                    "last_ocr_blocked_attachment_id": str(attachment_id),
                    "last_ocr_blocked_job_id": str(job_id),
                    "last_ocr_blocked_target_parse_failed_count": target_failed_count,
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


def _insert_buyer_intent_parse_trace(
    db: Session,
    *,
    job: JobClaim,
    buyer_intent_id: UUID,
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
              :team_id, :workspace_id, 'llm', 'buyer_intent_parser',
              :job_id, :correlation_id, 'buyer_intent', :buyer_intent_id,
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
            "buyer_intent_id": buyer_intent_id,
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
            "metadata_json": {"source": "buyer_intent_parser"},
        },
    )


def _insert_seller_target_parse_trace(
    db: Session,
    *,
    job: JobClaim,
    seller_target_id: UUID,
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
              :team_id, :workspace_id, 'llm', 'seller_target_parser',
              :job_id, :correlation_id, 'seller_target', :seller_target_id,
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
            "seller_target_id": seller_target_id,
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
            "metadata_json": {"source": "seller_target_parser"},
        },
    )


def _update_recommendation_report_generated(
    db: Session,
    *,
    report_id: UUID,
    markdown_content: str,
    generated_by_model: str,
    prompt_version: str | None,
    metadata_patch: dict[str, Any],
) -> None:
    db.execute(
        text(
            """
            update recommendation_report
            set markdown_content = :markdown_content,
                status = 'generated',
                generated_by_model = :generated_by_model,
                prompt_version = :prompt_version,
                metadata_json = metadata_json || :metadata_patch
            where id = :report_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "report_id": report_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "markdown_content": markdown_content,
            "generated_by_model": generated_by_model,
            "prompt_version": prompt_version,
            "metadata_patch": metadata_patch,
        },
    )


def _insert_recommendation_report_message(
    db: Session,
    *,
    report_id: UUID,
    session_id: UUID,
    markdown_content: str,
    job_id: UUID,
    generation_mode: str,
) -> None:
    db.execute(
        text(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, 'assistant', :content,
              'markdown', :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "content": markdown_content,
            "metadata_json": {
                "report_id": str(report_id),
                "job_id": str(job_id),
                "message_type": "recommendation_report",
                "generation_mode": generation_mode,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )
    db.execute(
        text(
            """
            update recommendation_session
            set updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"session_id": session_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    )


def _insert_recommendation_report_llm_trace(
    db: Session,
    *,
    job: JobClaim,
    report_id: UUID,
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
              :team_id, :workspace_id, 'llm', 'recommendation_report_writer',
              :job_id, :correlation_id, 'recommendation_report', :report_id,
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
            "report_id": report_id,
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
            "metadata_json": {"source": "recommendation_report_generate"},
        },
    )


def _insert_rerank_trace(
    db: Session,
    *,
    job: JobClaim,
    session_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    parsed_output_json: dict[str, Any] | None,
    latency_ms: int,
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
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, total_tokens,
              created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'rerank', 'recommendation_reranker',
              :job_id, :correlation_id, 'recommendation_session', :session_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :total_tokens,
              :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "session_id": session_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": input_json,
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status == "succeeded"},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "total_tokens": total_tokens,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "recommendation_rerank"},
        },
    )


def _insert_parsed_document_for_ocr(
    db: Session,
    *,
    attachment_id: UUID,
    parse_status: str,
    extracted_text: str,
    error_message: str | None,
    parser_name: str = "ocr_attachment_parser",
    parser_version: str = "v0.1.0-skeleton",
    text_path: str | None = None,
    markdown_path: str | None = None,
    manifest_path: str | None = None,
    page_count: int | None = None,
) -> UUID:
    parsed_document_id = uuid4()
    token_count = _approx_token_count(extracted_text) if extracted_text else None
    resolved_text_path = text_path or (f"mock://parsed-documents/{parsed_document_id}.txt" if extracted_text else None)
    row = db.execute(
        text(
            """
            insert into parsed_document (
              id, team_id, workspace_id, attachment_id, parser_name, parser_version,
              parse_status, text_path, markdown_path, manifest_path, page_count,
              token_count, error_message
            )
            values (
              :id, :team_id, :workspace_id, :attachment_id, :parser_name,
              :parser_version, :parse_status, :text_path, :markdown_path, :manifest_path, :page_count,
              :token_count, :error_message
            )
            returning id
            """
        ),
        {
            "id": parsed_document_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_id": attachment_id,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "parse_status": parse_status,
            "text_path": resolved_text_path,
            "markdown_path": markdown_path,
            "manifest_path": manifest_path,
            "page_count": page_count if page_count is not None else (1 if extracted_text else None),
            "token_count": token_count,
            "error_message": error_message,
        },
    ).mappings().one()
    return row["id"]


def _insert_ocr_evidence_span(
    db: Session,
    *,
    attachment_id: UUID,
    parsed_document_id: UUID,
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
              :team_id, :workspace_id, 'attachment_ocr_parse', :job_id, :attachment_id,
              :parsed_document_id, 1, :text_excerpt, 0, :char_end
            )
            returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_id": job_id,
            "attachment_id": attachment_id,
            "parsed_document_id": parsed_document_id,
            "text_excerpt": excerpt,
            "char_end": len(excerpt),
        },
    ).mappings().one()
    return row["id"]


def _update_attachment_parse_terminal(
    db: Session,
    *,
    attachment_id: UUID,
    parse_status: str,
    job_id: UUID,
    parsed_document_id: UUID,
    evidence_id: UUID | None,
    text_length: int,
    metadata_patch: dict[str, Any] | None = None,
) -> None:
    patch = {
        "last_ocr_job_id": str(job_id),
        "last_ocr_status": parse_status,
        "last_parsed_document_id": str(parsed_document_id),
        "last_evidence_id": str(evidence_id) if evidence_id else None,
        "last_text_length": text_length,
    }
    if metadata_patch:
        patch.update(metadata_patch)
    db.execute(
        text(
            """
            update attachment
            set parse_status = :parse_status,
                metadata_json = metadata_json || :metadata_patch
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "parse_status": parse_status,
            "metadata_patch": patch,
        },
    )


def _update_attachment_parse_terminal_without_document(
    db: Session,
    *,
    attachment_id: UUID,
    parse_status: str,
    job_id: UUID,
    metadata_patch: dict[str, Any] | None = None,
) -> None:
    patch = {"last_ocr_job_id": str(job_id), "last_ocr_status": parse_status}
    if metadata_patch:
        patch.update(metadata_patch)
    db.execute(
        text(
            """
            update attachment
            set parse_status = :parse_status,
                metadata_json = metadata_json || :metadata_patch
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "parse_status": parse_status,
            "metadata_patch": patch,
        },
    )


def _patch_attachment_metadata(db: Session, attachment_id: UUID, metadata_patch: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            update attachment
            set metadata_json = metadata_json || :metadata_patch
            where id = :attachment_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": metadata_patch,
        },
    )


def _enqueue_doc2x_poll_job(
    db: Session,
    *,
    parent_job_id: Any,
    attachment_id: UUID,
    business_update_id: UUID | None,
    doc2x_uid: str,
    started_epoch: float,
    source_payload: dict[str, Any],
    run_after_seconds: int,
) -> dict[str, Any]:
    payload_json = {
        **source_payload,
        "attachment_id": str(attachment_id),
        "business_update_id": str(business_update_id) if business_update_id else source_payload.get("business_update_id"),
        "doc2x_uid": doc2x_uid,
        "doc2x_started_epoch": started_epoch,
        "submitted_by_job_id": str(parent_job_id),
    }
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, run_after, parent_job_id, correlation_id, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'attachment_ocr_poll', 100, 'ocr',
              'attachment', :attachment_id, :idempotency_key, :payload_json,
              1, now() + (:run_after_seconds * interval '1 second'),
              :parent_job_id, :correlation_id, :created_by, :metadata_json
            )
            returning id, job_type, status, queue_name, entity_type, entity_id, run_after::text as run_after
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_id": attachment_id,
            "idempotency_key": f"attachment_ocr_poll:doc2x:{doc2x_uid}:{uuid4()}",
            "payload_json": payload_json,
            "run_after_seconds": max(int(run_after_seconds), 1),
            "parent_job_id": _optional_uuid(parent_job_id),
            "correlation_id": business_update_id or _optional_uuid(source_payload.get("business_update_id")) or attachment_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "doc2x_poll",
                "attachment_id": str(attachment_id),
                "business_update_id": str(business_update_id) if business_update_id else source_payload.get("business_update_id"),
                "doc2x_uid": doc2x_uid,
            },
        },
    ).mappings().one()
    return _json_safe_dict(row)


def _save_ocr_text_artifact(
    *,
    attachment_id: UUID,
    parsed_document_id: UUID | None,
    content: str,
    suffix: str,
    content_type: str = "text/plain; charset=utf-8",
) -> str | None:
    if not content:
        return None
    settings = get_settings()
    document_part = str(parsed_document_id) if parsed_document_id else "pending"
    return save_generated_text(
        content,
        storage_backend=settings.effective_attachment_storage_backend,
        storage_dir=settings.attachment_storage_dir,
        key_prefix=f"parsed-documents/{attachment_id}/{document_part}",
        file_name=suffix,
        content_type=content_type,
        s3_endpoint_url=settings.effective_attachment_s3_endpoint_url,
        s3_region=settings.effective_attachment_s3_region,
        s3_bucket=settings.effective_attachment_s3_bucket,
        s3_access_key_id=settings.effective_attachment_s3_access_key_id,
        s3_secret_access_key=settings.effective_attachment_s3_secret_access_key,
        s3_force_path_style=settings.attachment_s3_force_path_style,
    )


def _doc2x_status_text_fallback(raw_response: dict[str, Any]) -> str:
    data = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    json_text = _json_dumps({"result": result})
    return _truncate_text(json_text, 200_000) or json_text


def _touch_seller_targets_linked_to_attachment(db: Session, attachment_id: UUID) -> int:
    result = db.execute(
        text(
            """
            update seller_target st
            set last_attachment_parse_at = now(),
                updated_at = now()
            from attachment_link al
            where al.attachment_id = :attachment_id
              and al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'seller_target'
              and al.entity_id = st.id
              and st.team_id = :team_id
              and st.workspace_id = :workspace_id
              and st.deleted_at is null
            """
        ),
        {
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
    return int(result.rowcount or 0)


def _enqueue_linked_parse_jobs_after_ocr(
    db: Session,
    *,
    job: JobClaim,
    attachment_id: UUID,
    parsed_document_id: UUID | None,
    evidence_id: UUID | None,
    extracted_text: str,
) -> list[dict[str, Any]]:
    if not extracted_text.strip() or not job.payload_json.get("auto_parse_linked_objects"):
        return []

    requested_entity_types = _parse_requested_entity_types(job.payload_json.get("parse_entity_types"))
    links = _attachment_parse_links(db, attachment_id, requested_entity_types=requested_entity_types)
    child_jobs: list[dict[str, Any]] = []
    for link in links:
        entity_type = str(link["entity_type"])
        if entity_type == "seller_target":
            raw_text_key = "raw_target_text"
            job_type = "seller_target_parse"
        elif entity_type == "buyer_intent":
            raw_text_key = "raw_requirement_text"
            job_type = "buyer_intent_parse"
        else:
            continue

        existing = _latest_active_child_parse_job(
            db,
            job_type=job_type,
            entity_type=entity_type,
            entity_id=link["entity_id"],
        )
        if existing:
            child_jobs.append(
                {
                    "id": str(existing["id"]),
                    "job_type": existing["job_type"],
                    "status": existing["status"],
                    "queue_name": existing["queue_name"],
                    "entity_type": entity_type,
                    "entity_id": str(link["entity_id"]),
                    "reused_existing": True,
                }
            )
            continue

        payload_json = {
            f"{entity_type}_id": str(link["entity_id"]),
            raw_text_key: extracted_text,
            "attachment_id": str(attachment_id),
            "parsed_document_id": str(parsed_document_id),
            "evidence_id": str(evidence_id) if evidence_id else None,
            "source_type": "attachment_ocr_parse",
            "source_id": str(job.id),
            "source_label": f"Attachment OCR: {link.get('link_type') or 'linked document'}",
        }
        row = db.execute(
            text(
                """
                insert into background_job (
                  team_id, workspace_id, job_type, priority, queue_name,
                  entity_type, entity_id, idempotency_key, payload_json,
                  max_attempts, parent_job_id, correlation_id, created_by, metadata_json
                )
                values (
                  :team_id, :workspace_id, :job_type, 105, 'llm',
                  :entity_type, :entity_id, :idempotency_key, :payload_json,
                  3, :parent_job_id, :correlation_id, :created_by, :metadata_json
                )
                returning id, job_type, status, queue_name, entity_type, entity_id
                """
            ).bindparams(
                bindparam("payload_json", type_=JSONB),
                bindparam("metadata_json", type_=JSONB),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "job_type": job_type,
                "entity_type": entity_type,
                "entity_id": link["entity_id"],
                "idempotency_key": f"{job_type}:attachment_ocr:{attachment_id}:{link['entity_id']}:{job.id}",
                "payload_json": payload_json,
                "parent_job_id": job.id,
                "correlation_id": job.correlation_id or job.id,
                "created_by": DEFAULT_ADMIN_USER_ID,
                "metadata_json": {
                    "source": "attachment_ocr_auto_parse",
                    "attachment_id": str(attachment_id),
                    "evidence_id": str(evidence_id) if evidence_id else None,
                },
            },
        ).mappings().one()
        child_jobs.append({**_json_safe_dict(row), "reused_existing": False})
    return child_jobs


def _parse_requested_entity_types(value: Any) -> set[str]:
    supported = {"seller_target", "buyer_intent"}
    if not isinstance(value, list) or not value:
        return supported
    requested = {str(item) for item in value if str(item) in supported}
    return requested or supported


def _attachment_parse_links(
    db: Session,
    attachment_id: UUID,
    *,
    requested_entity_types: set[str],
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select entity_type, entity_id, link_type
            from attachment_link
            where team_id = :team_id
              and workspace_id = :workspace_id
              and attachment_id = :attachment_id
              and entity_type = any(:entity_types)
            order by created_at asc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "attachment_id": attachment_id,
            "entity_types": list(requested_entity_types),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _enqueue_business_update_process_after_ocr(
    db: Session,
    *,
    job: JobClaim,
    attachment_id: UUID,
    evidence_id: UUID | None,
    extracted_text: str,
) -> dict[str, Any] | None:
    business_update_id = _optional_uuid(job.payload_json.get("business_update_id"))
    if (
        not business_update_id
        or not extracted_text.strip()
        or not job.payload_json.get("process_business_update_after_ocr")
    ):
        return None

    existing = _latest_active_business_update_process_job(db, business_update_id)
    if existing:
        return {**_json_safe_dict(existing), "reused_existing": True}

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              parent_job_id, correlation_id, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'business_update_extract_actions', 110, 'llm',
              'business_update', :business_update_id, :idempotency_key, :payload_json,
              :parent_job_id, :correlation_id, :created_by, :metadata_json
            )
            returning id, job_type, status, queue_name, entity_type, entity_id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
            "idempotency_key": f"business_update_extract_actions:attachment_ocr:{business_update_id}:{job.id}",
            "payload_json": {
                "business_update_id": str(business_update_id),
                "include_attachment_text": bool(job.payload_json.get("include_attachment_text", True)),
                "trigger_attachment_id": str(attachment_id),
                "trigger_evidence_id": str(evidence_id) if evidence_id else None,
            },
            "parent_job_id": job.id,
            "correlation_id": job.correlation_id or business_update_id,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "attachment_ocr_auto_business_update_process",
                "attachment_id": str(attachment_id),
                "evidence_id": str(evidence_id) if evidence_id else None,
            },
        },
    ).mappings().one()
    db.execute(
        text(
            """
            update business_update
            set processing_status = 'processing',
                metadata_json = metadata_json || :metadata_patch
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and processing_status in ('pending', 'failed', 'processing', 'parsed', 'partially_applied', 'applied')
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_ocr_trigger_job_id": str(job.id),
                "last_ocr_trigger_attachment_id": str(attachment_id),
                "last_ocr_trigger_evidence_id": str(evidence_id) if evidence_id else None,
                "last_ocr_process_job_id": str(row["id"]),
            },
        },
    )
    return {**_json_safe_dict(row), "reused_existing": False}


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


def _insert_recommendation_rerank_message(
    db: Session,
    *,
    session_id: UUID,
    job_id: UUID,
    reranked_candidates: list[dict[str, Any]],
    model_name: str,
) -> None:
    db.execute(
        text(
            """
            insert into recommendation_message (
              team_id, workspace_id, session_id, role, content,
              content_type, metadata_json, created_by
            )
            values (
              :team_id, :workspace_id, :session_id, 'tool', :content,
              'json', :metadata_json, :created_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "session_id": session_id,
            "content": _json_dumps(
                {
                    "message_type": "reranked_candidates",
                    "candidate_count": len(reranked_candidates),
                    "candidates": reranked_candidates,
                }
            ),
            "metadata_json": {
                "job_id": str(job_id),
                "message_type": "reranked_candidates",
                "model_name": model_name,
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    )
    db.execute(
        text(
            """
            update recommendation_session
            set latest_condition_snapshot_json = latest_condition_snapshot_json || :metadata_patch,
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {
                "last_rerank_job_id": str(job_id),
                "last_rerank_model": model_name,
                "last_reranked_candidate_count": len(reranked_candidates),
            },
        },
    )


def _insert_model_node_test_trace(
    db: Session,
    *,
    job: JobClaim,
    node_config: dict[str, Any],
    trace_type: str,
    status: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]] | None = None,
    raw_output_text: str | None = None,
    parsed_output_json: dict[str, Any] | None = None,
    latency_ms: int | None = None,
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
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, :trace_type, :node_name,
              :job_id, :correlation_id, 'model_node_config', :node_config_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "trace_type": trace_type,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "node_config_id": node_config["node_config_id"],
            "provider_config_id": node_config["provider_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json or [],
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status in {"succeeded", "skipped"}},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "model_node_test"},
        },
    )


def _insert_ocr_trace(
    db: Session,
    *,
    job: JobClaim,
    attachment_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    raw_output_text: str | None,
    parsed_output_json: dict[str, Any] | None,
    latency_ms: int,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              job_id, correlation_id, entity_type, entity_id,
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, raw_output_text, parsed_output_json,
              schema_validation_json, error_code, error_message,
              latency_ms, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'ocr', :node_name,
              :job_id, :correlation_id, 'attachment', :attachment_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :raw_output_text, :parsed_output_json,
              :schema_validation_json, :error_code, :error_message,
              :latency_ms, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "attachment_id": attachment_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": input_json,
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status in {"succeeded", "skipped"}},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "attachment_ocr_parse", "execution_mode": "skeleton"},
        },
    )


def _model_node_test_messages(job: JobClaim, node_config: dict[str, Any]) -> list[dict[str, str]]:
    messages = job.payload_json.get("messages")
    if isinstance(messages, list) and messages:
        output: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user")
            content = str(message.get("content") or "")
            if role in {"system", "user", "assistant", "tool"} and content:
                output.append({"role": role, "content": content})
        if output:
            return output

    input_text = str(job.payload_json.get("input_text") or "")
    if node_config.get("response_format") == "json_object":
        return [
            {"role": "system", "content": "You are a concise API connectivity tester. Output JSON only."},
            {"role": "user", "content": input_text or 'Return {"status":"ok"}.'},
        ]
    return [
        {"role": "system", "content": "You are a concise API connectivity tester."},
        {"role": "user", "content": input_text or "Return exactly: ok"},
    ]


def _model_node_test_input_json(
    job: JobClaim,
    node_config: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "node_config_id": str(node_config["node_config_id"]),
        "node_name": node_config["node_name"],
        "node_type": node_config["node_type"],
        **(extra or {}),
    }


def _model_node_test_result(
    job: JobClaim,
    node_config: dict[str, Any],
    status: str,
    output_json: dict[str, Any],
    latency_ms: int | None,
) -> dict[str, object]:
    return {
        "handled": True,
        "job_type": job.job_type,
        "node_id": str(node_config["node_config_id"]),
        "node_name": node_config["node_name"],
        "node_type": node_config["node_type"],
        "status": status,
        "latency_ms": latency_ms,
        "output_json": output_json,
        "trace_created": True,
    }


def _redact_test_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "content_preview": str(message.get("content") or "")[:300],
        }
        for message in messages
    ]


def _insert_embedding_trace(
    db: Session,
    *,
    job: JobClaim,
    entity_type: str,
    entity_id: UUID,
    node_config: dict[str, Any],
    status: str,
    input_json: dict[str, Any],
    parsed_output_json: dict[str, Any] | None,
    latency_ms: int,
    prompt_tokens: int | None = None,
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
              provider_config_id, node_config_id,
              provider_name, model_name, status,
              input_json, parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              total_tokens, created_by, finished_at, metadata_json
            )
            values (
              :team_id, :workspace_id, 'embedding', :node_name,
              :job_id, :correlation_id, :entity_type, :entity_id,
              :provider_config_id, :node_config_id,
              :provider_name, :model_name, :status,
              :input_json, :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :total_tokens, :created_by, now(), :metadata_json
            )
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_config["node_name"],
            "job_id": job.id,
            "correlation_id": job.correlation_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider_config_id": node_config["provider_config_id"],
            "node_config_id": node_config["node_config_id"],
            "provider_name": node_config["provider_name"],
            "model_name": node_config["model_name"],
            "status": status,
            "input_json": {
                **input_json,
                "text_preview": (input_json.get("text") or "")[:1000],
                "text": None,
            },
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status in {"succeeded", "skipped"}},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "total_tokens": total_tokens,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "embedding_generate"},
        },
    )
