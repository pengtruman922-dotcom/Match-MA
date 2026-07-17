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
    _get_model_node_config_by_id,
    _optional_uuid,
    _resolve_entity_id,
)
from backend.app.jobs.handlers.traces import (
    _insert_model_node_test_trace,
)

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
            api_key_encrypted=node_config.get("api_key_encrypted"),
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
