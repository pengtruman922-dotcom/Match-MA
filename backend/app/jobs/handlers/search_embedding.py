from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
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
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.api.routes.extracted_actions import (
    apply_buyer_intent_follow_up_action,
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
    apply_target_follow_up_action,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.search_docs import (
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
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    normalize_excluded_terms,
    normalize_l1_values,
    resolve_l1,
)
from backend.app.services.office_inspection import inspect_office_text, office_document_kind
from backend.app.services.pdf_inspection import inspect_pdf_text_layer

from backend.app.jobs.handlers.common import (
    _get_default_embedding_node_config,
    _optional_uuid,
    _resolve_entity_id,
)
from backend.app.jobs.handlers.traces import (
    _insert_embedding_trace,
)

def _handle_seller_search_doc_rebuild(db: Session, job: JobClaim) -> dict[str, object]:
    seller_target_id = _resolve_entity_id(job, expected_entity_type="seller_target")
    if seller_target_id is None:
        raise ValueError("seller_search_doc_rebuild job requires a seller_target entity_id.")

    result = rebuild_seller_target_search_doc(db, seller_target_id)
    return {
        "handled": True,
        "job_type": job.job_type,
        "seller_target_id": str(seller_target_id),
        "search_doc_id": str(result["search_doc_id"]),
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": None,
    }

def _handle_buyer_intent_search_doc_rebuild(db: Session, job: JobClaim) -> dict[str, object]:
    buyer_intent_id = _resolve_entity_id(job, expected_entity_type="buyer_intent")
    if buyer_intent_id is None:
        raise ValueError("buyer_intent_search_doc_rebuild job requires a buyer_intent entity_id.")

    result = rebuild_buyer_intent_search_doc(db, buyer_intent_id)
    return {
        "handled": True,
        "job_type": job.job_type,
        "buyer_intent_id": str(buyer_intent_id),
        "search_doc_id": str(result["search_doc_id"]),
        "source_version": result["source_version"],
        "full_text_length": len(result["full_text"] or ""),
        "embedding_job_id": None,
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
            api_key_encrypted=node_config.get("api_key_encrypted"),
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
