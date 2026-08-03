from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.jobs.queue import JobClaim
from backend.app.jobs.handlers.business_update import (
    _build_business_update_attachment_context,
    _build_business_update_image_context,
    _business_update_raw_text_with_attachments,
    _get_business_update,
    _resolve_business_update_id,
)
from backend.app.jobs.handlers.common import (
    _attach_multimodal_images,
    _get_default_node_config,
    _optional_uuid,
    _render_prompt_messages,
    _safe_prompt_messages_for_trace,
)
from backend.app.jobs.handlers.traces import _insert_llm_trace
from backend.app.services.relation_flow import (
    complete_ai_followup_event,
    fail_ai_followup_event,
)


FOLLOWUP_NODE_NAME = "relation_followup_draft_parser"


def _handle_relation_followup_draft_parse(db: Session, job: JobClaim) -> dict[str, object]:
    business_update_id = _resolve_business_update_id(job)
    if business_update_id is None:
        raise ValueError("relation_followup_draft_parse requires a business_update_id.")

    business_update = _get_business_update(db, business_update_id)
    metadata = business_update.get("metadata_json") if isinstance(business_update.get("metadata_json"), dict) else {}
    processing_scope = str(metadata.get("processing_scope") or "basic_info")
    if processing_scope not in {"follow_up", "both"}:
        raise ValueError("relation_followup_draft_parse requires follow_up or both processing_scope.")
    relation_id = _optional_uuid(metadata.get("bound_relation_id"))
    if relation_id is None:
        raise ValueError("relation_followup_draft_parse requires bound_relation_id.")

    try:
        # Keep context preparation inside the guarded section. A relation may be
        # deleted, or attachment storage may fail, after the update was queued;
        # the final attempt must still release the UI from its pending state.
        relation_context = _relation_followup_context(db, relation_id)
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
        raw_text = _business_update_raw_text_with_attachments(business_update.get("raw_text"), attachment_context)
        image_context = _build_business_update_image_context(
            db,
            business_update_id,
            trigger_attachment_id=_optional_uuid(job.payload_json.get("trigger_attachment_id")),
        )

        node_config = _get_default_node_config(db, FOLLOWUP_NODE_NAME)
        prompt_messages = _render_prompt_messages(
            node_config,
            {
                "relation_context_json": relation_context,
                "raw_text": raw_text,
            },
        )
        if image_context["images"]:
            prompt_messages = _attach_multimodal_images(
                prompt_messages,
                image_context["images"],
                instruction=(
                    "The following images are source material for the selected relation follow-up. "
                    "Read them directly and clearly preserve who said what, the concrete communication content, "
                    "and any explicit next action with its actor and deadline. "
                    "Do not output attachment ids, raw_evidence_text, relation ids, status, or event type."
                ),
            )
        input_json = {
            "business_update_id": str(business_update_id),
            "relation_context_json": relation_context,
            "raw_text": raw_text,
            "original_raw_text": business_update.get("raw_text"),
            "attachment_count": len(attachment_context.get("attachments", [])),
            "image_attachment_count": len(image_context.get("summaries", [])),
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

        draft, validation = _normalize_relation_followup_draft(llm_result.parsed_output_json)
        _insert_llm_trace(
            db,
            job=job,
            business_update_id=business_update_id,
            node_config=node_config,
            status="succeeded" if validation["valid"] else "failed",
            input_json=input_json,
            prompt_messages_json=_safe_prompt_messages_for_trace(prompt_messages),
            raw_output_text=llm_result.raw_output_text,
            parsed_output_json=llm_result.parsed_output_json,
            schema_validation_json=validation,
            latency_ms=llm_result.latency_ms,
            prompt_tokens=llm_result.prompt_tokens,
            completion_tokens=llm_result.completion_tokens,
            total_tokens=llm_result.total_tokens,
            error_code=None if validation["valid"] else "schema_validation_failed",
            error_message=None if validation["valid"] else str(validation.get("error")),
        )
        if not validation["valid"]:
            db.commit()
            raise ValueError(str(validation.get("error") or "Invalid relation follow-up draft output."))

        _store_relation_followup_draft(
            db,
            business_update_id=business_update_id,
            processing_scope=processing_scope,
            job_id=job.id,
            draft=draft,
        )
        db.commit()
        return {
            "handled": True,
            "job_type": job.job_type,
            "business_update_id": str(business_update_id),
            "relation_id": str(relation_id),
            "draft": draft,
            "trace_created": True,
            "model_name": node_config["model_name"],
            "prompt_version": node_config["prompt_version"],
        }
    except Exception as exc:
        db.rollback()
        if job.attempt_count >= job.max_attempts:
            _store_relation_followup_failure(
                db,
                business_update_id=business_update_id,
                processing_scope=processing_scope,
                job_id=job.id,
                error_message=str(exc),
            )
            db.commit()
        raise


def _relation_followup_context(db: Session, relation_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              r.id, r.status, r.seller_target_id, st.target_name as seller_target_name,
              r.buyer_intent_id, bi.intent_name as buyer_intent_name,
              r.buyer_party_id, bp.buyer_name
            from buyer_seller_relation r
            join seller_target st on st.id = r.seller_target_id and st.deleted_at is null
            join buyer_intent bi on bi.id = r.buyer_intent_id and bi.deleted_at is null
            left join buyer_party bp on bp.id = r.buyer_party_id and bp.deleted_at is null
            where r.id = :relation_id
              and r.team_id = :team_id
              and r.workspace_id = :workspace_id
              and r.deleted_at is null
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError("Bound relation no longer exists.")
    return {key: str(value) if isinstance(value, UUID) else value for key, value in dict(row).items()}


def _normalize_relation_followup_draft(value: Any) -> tuple[dict[str, str | None], dict[str, Any]]:
    if not isinstance(value, dict):
        return {"content": "", "next_step": None}, {"valid": False, "error": "Output must be a JSON object."}
    extra_keys = sorted(set(value) - {"content", "next_step"})
    raw_content = value.get("content")
    raw_next_step = value.get("next_step")
    if not isinstance(raw_content, str) or not raw_content.strip():
        return {"content": "", "next_step": None}, {"valid": False, "error": "content must be a non-empty string."}
    if raw_next_step is not None and not isinstance(raw_next_step, str):
        return {"content": "", "next_step": None}, {"valid": False, "error": "next_step must be a string or null."}
    if extra_keys:
        return {"content": "", "next_step": None}, {
            "valid": False,
            "error": f"Unsupported output fields: {', '.join(extra_keys)}",
        }
    draft = {
        # Keep the generated draft inside the relation-event API contract so a
        # valid AI result cannot later fail only when the consultant confirms it.
        "content": raw_content.strip()[:4000],
        "next_step": raw_next_step.strip()[:1000] if isinstance(raw_next_step, str) and raw_next_step.strip() else None,
    }
    return draft, {"valid": True, "fields": ["content", "next_step"]}


def _store_relation_followup_draft(
    db: Session,
    *,
    business_update_id: UUID,
    processing_scope: str,
    job_id: UUID,
    draft: dict[str, str | None],
) -> None:
    complete_ai_followup_event(
        db,
        business_update_id=business_update_id,
        job_id=job_id,
        content=str(draft["content"]),
        next_step=draft.get("next_step"),
    )
    db.execute(
        text(
            """
            update business_update
            set processing_status = case when :processing_scope = 'follow_up' then 'parsed' else processing_status end,
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
            "processing_scope": processing_scope,
            "metadata_patch": {
                "followup_draft_status": "succeeded",
                "followup_draft": draft,
                "followup_draft_job_id": str(job_id),
                "followup_draft_error": None,
            },
        },
    )


def _store_relation_followup_failure(
    db: Session,
    *,
    business_update_id: UUID,
    processing_scope: str,
    job_id: UUID,
    error_message: str,
) -> None:
    fail_ai_followup_event(
        db,
        business_update_id=business_update_id,
        job_id=job_id,
        error_message=error_message,
    )
    db.execute(
        text(
            """
            update business_update
            set processing_status = case when :processing_scope = 'follow_up' then 'failed' else processing_status end,
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
            "processing_scope": processing_scope,
            "metadata_patch": {
                "followup_draft_status": "failed",
                "followup_draft_job_id": str(job_id),
                "followup_draft_error": error_message[:1000],
            },
        },
    )
