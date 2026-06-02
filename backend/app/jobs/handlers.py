from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.embedding_client import (
    EmbeddingCallError,
    call_openai_compatible_embedding,
    embedding_to_pgvector_literal,
)
from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.prompting import render_template
from backend.app.ai.rerank_client import RerankCallError, call_dashscope_compatible_rerank
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.api.routes.extracted_actions import (
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.search_docs import (
    create_embedding_job_for_search_doc,
    rebuild_buyer_intent_search_doc,
    rebuild_seller_target_search_doc,
)

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
        input_json = _model_node_test_input_json(job, node_config)
        _insert_model_node_test_trace(
            db,
            job=job,
            node_config=node_config,
            trace_type="ocr",
            status="skipped",
            input_json=input_json,
            parsed_output_json={"reason": "OCR node test is not implemented in v0.1."},
            latency_ms=0,
        )
        return {
            "handled": True,
            "job_type": job.job_type,
            "node_id": str(node_id),
            "node_name": node_config["node_name"],
            "node_type": node_type,
            "status": "skipped",
            "trace_created": True,
        }
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
