from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.doc2x_client import Doc2xCallError, poll_doc2x_status, submit_doc2x_pdf
from backend.app.services.ocr_provider import resolve_ocr_provider
from backend.app.ai.ocr_client import OcrInput, build_attachment_ocr_input_json, call_attachment_ocr
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.jobs.queue import JobClaim
from backend.app.services.attachment_storage import (
    save_generated_text,
)
from backend.app.services.office_inspection import inspect_office_text, office_document_kind
from backend.app.services.pdf_inspection import extract_pdf_text, inspect_pdf_text_layer
from backend.app.services.business_update_flow import _enqueue_business_update_process_job

from backend.app.jobs.handlers.business_update import (
    _build_business_update_attachment_context,
    _get_business_update,
    _latest_active_child_parse_job,
)
from backend.app.jobs.handlers.common import (
    _approx_token_count,
    _attachment_file_bytes,
    _attachment_local_text_content,
    _get_default_ocr_node_config,
    _is_pdf_attachment,
    _json_dumps,
    _json_safe_dict,
    _optional_uuid,
    _resolve_entity_id,
    _truncate_text,
    _uuid_list,
)
from backend.app.jobs.handlers.seller_target_parse import (
    _mark_seller_targets_parse_failed,
)
from backend.app.jobs.handlers.traces import (
    _insert_ocr_trace,
)

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

    _get_attachment_for_ocr(db, attachment_id)
    settings = get_settings()
    uid = str(job.payload_json.get("doc2x_uid") or "").strip()
    if not uid:
        raise ValueError("attachment_ocr_poll job requires doc2x_uid.")
    ocr_config = resolve_ocr_provider(db)
    doc2x_api_key = ocr_config.api_key
    if not doc2x_api_key:
        raise ValueError("Doc2X API key is not configured (settings page or DOC2X_SECRET).")

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
            base_url=ocr_config.base_url,
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
                "model_name": ocr_config.model,
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
                "model_name": ocr_config.model,
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
        parser_version=ocr_config.model,
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
            "model_name": ocr_config.model,
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
        # 检测只采样前几页；正文必须重新整篇抽一次，否则第 6 页以后的内容
        # （年报里财务数据往往就在那）永远进不了解析。
        document = extract_pdf_text(file_bytes, max_chars=settings.attachment_text_capture_max_bytes)
        document_text = document.extracted_text or inspection.extracted_text
        _patch_attachment_metadata(
            db,
            attachment_id,
            {
                "last_pdf_text_extraction": {
                    "page_count": document.page_count,
                    "extracted_char_count": document.extracted_char_count,
                    "truncated": document.truncated,
                    "max_chars": settings.attachment_text_capture_max_bytes,
                    "error_message": document.error_message,
                    "fell_back_to_detection_sample": not document.extracted_text,
                },
            },
        )
        text_path = _save_ocr_text_artifact(
            attachment_id=attachment_id,
            parsed_document_id=None,
            content=document_text,
            suffix="pdf-text.txt",
        )
        parsed_document_id = _insert_parsed_document_for_ocr(
            db,
            attachment_id=attachment_id,
            parse_status="parsed",
            extracted_text=document_text,
            error_message=None,
            parser_name="pdf_text_layer",
            parser_version="pypdf",
            text_path=text_path,
            page_count=document.page_count or inspection.page_count,
        )
        evidence_id = _insert_ocr_evidence_span(
            db,
            attachment_id=attachment_id,
            parsed_document_id=parsed_document_id,
            job_id=job.id,
            text_excerpt=document_text,
        )
        _update_attachment_parse_terminal(
            db,
            attachment_id=attachment_id,
            parse_status="parsed",
            job_id=job.id,
            parsed_document_id=parsed_document_id,
            evidence_id=evidence_id,
            text_length=len(document_text),
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
            extracted_text=document_text,
        )
        business_update_process_job = _enqueue_business_update_process_after_ocr(
            db,
            job=job,
            attachment_id=attachment_id,
            evidence_id=evidence_id,
            extracted_text=document_text,
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
                "pdf_text_extraction": {
                    "page_count": document.page_count,
                    "extracted_char_count": document.extracted_char_count,
                    "truncated": document.truncated,
                },
            },
            raw_output_text=document_text,
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
            "text_length": len(document_text),
            "page_count": document.page_count,
            "text_truncated": document.truncated,
            "touched_seller_target_count": touched_seller_target_count,
            "child_parse_jobs": child_parse_jobs,
            "child_parse_job_count": len(child_parse_jobs),
            "business_update_process_job": business_update_process_job,
        }

    ocr_config = resolve_ocr_provider(db)
    if ocr_config.adapter != "doc2x":
        return None
    doc2x_api_key = ocr_config.api_key
    if not doc2x_api_key:
        raise ValueError("Doc2X API key is not configured (settings page or DOC2X_SECRET).")

    try:
        submit_result = submit_doc2x_pdf(
            base_url=ocr_config.base_url,
            api_key=doc2x_api_key,
            file_bytes=file_bytes,
            model=ocr_config.model,
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
            "model_name": ocr_config.model,
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
        readiness = _business_update_content_readiness(db, business_update_id)
        if readiness["has_usable_text"]:
            db.execute(
                text(
                    """
                    update business_update
                    set metadata_json = metadata_json || :metadata_patch
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
                        "attachment_extraction_warning": True,
                        "failed_attachment_id": str(attachment_id),
                        "failed_attachment_job_id": str(job_id),
                        "last_ocr_error": error_message,
                    },
                },
            )
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


def _finalize_attachment_job_failure(db: Session, job: JobClaim, error_message: str) -> None:
    """Close user-visible state only after the worker recorded a final job failure."""
    if job.job_type not in {"attachment_ocr_parse", "attachment_ocr_poll"}:
        return
    attachment_id = _resolve_entity_id(job, expected_entity_type="attachment")
    if attachment_id is None:
        attachment_id = _optional_uuid(job.payload_json.get("attachment_id"))
    if attachment_id is None:
        return

    failed = db.execute(
        text(
            """
            select status
            from background_job
            where id = :job_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {"job_id": job.id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if not failed or failed["status"] != "failed":
        return

    newer_active = db.execute(
        text(
            """
            select 1
            from background_job newer
            join background_job failed_job on failed_job.id = :job_id
            where newer.team_id = :team_id
              and newer.workspace_id = :workspace_id
              and newer.entity_type = 'attachment'
              and newer.entity_id = :attachment_id
              and newer.job_type in ('attachment_ocr_parse', 'attachment_ocr_poll')
              and newer.status in ('queued', 'running', 'retry_waiting')
              and newer.created_at > failed_job.created_at
            limit 1
            """
        ),
        {
            "job_id": job.id,
            "attachment_id": attachment_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).first()
    if newer_active:
        return

    _update_attachment_parse_terminal_without_document(
        db,
        attachment_id=attachment_id,
        parse_status="failed",
        job_id=job.id,
        metadata_patch={
            "last_ocr_error": _truncate_text(error_message, 1000),
            "last_ocr_failed_at": _utc_now_text(),
            "last_ocr_failed_job_id": str(job.id),
        },
    )
    _mark_business_updates_blocked_by_attachment_ocr(
        db,
        attachment_id=attachment_id,
        job_id=job.id,
        error_message=error_message,
    )
    _enqueue_linked_parse_jobs_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        parsed_document_id=None,
        evidence_id=None,
        extracted_text="",
    )
    _enqueue_business_update_process_after_ocr(
        db,
        job=job,
        attachment_id=attachment_id,
        evidence_id=None,
        extracted_text="",
    )


def _utc_now_text() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()

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
    # 这里存的是附件正文，下游解析读的就是它 —— 曾经的 2000 字上限把 10 页年报
    # 砍成 2 页，财务表整段丢失。上限只保留和抽取端同一个天花板做兜底。
    excerpt = _truncate_text(text_excerpt, get_settings().attachment_text_capture_max_bytes) or ""
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
            "created_by": SYSTEM_USER_ID,
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
            set updated_at = now()
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
    if not job.payload_json.get("auto_parse_linked_objects"):
        return []

    parse_text = extracted_text.strip()
    business_update_id = _optional_uuid(job.payload_json.get("business_update_id"))
    if business_update_id:
        readiness = _business_update_content_readiness(db, business_update_id)
        if not readiness["all_terminal"] or not readiness["combined_text"]:
            return []
        parse_text = str(readiness["combined_text"])
    # 落库存全文，进提示词再收一道：两个上限各管各的，谁也不该替对方做决定。
    parse_text = _truncate_text(parse_text, get_settings().attachment_prompt_text_max_chars) or ""
    if not parse_text:
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
            raw_text_key: parse_text,
            "business_update_id": str(business_update_id) if business_update_id else None,
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
                "created_by": SYSTEM_USER_ID,
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
        or not job.payload_json.get("process_business_update_after_ocr")
    ):
        return None

    readiness = _business_update_content_readiness(db, business_update_id)
    if not readiness["all_terminal"] or not readiness["combined_text"]:
        return None

    row = _enqueue_business_update_process_job(
        db,
        business_update_id=business_update_id,
        include_attachment_text=bool(job.payload_json.get("include_attachment_text", True)),
        source="attachment_ocr_auto_business_update_process",
    )
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
    return _json_safe_dict(row)


def _business_update_content_readiness(db: Session, business_update_id: UUID) -> dict[str, Any]:
    """Return one batch-level decision after every linked attachment reaches a terminal state."""
    status_row = db.execute(
        text(
            """
            select
              count(*)::int as total,
              count(*) filter (where a.parse_status in ('pending', 'parsing'))::int as active,
              count(*) filter (where a.parse_status = 'parsed')::int as succeeded,
              count(*) filter (where a.parse_status = 'failed')::int as failed,
              count(*) filter (where a.parse_status = 'skipped')::int as skipped
            from attachment_link al
            join attachment a on a.id = al.attachment_id
            where al.team_id = :team_id
              and al.workspace_id = :workspace_id
              and al.entity_type = 'business_update'
              and al.entity_id = :business_update_id
              and a.deleted_at is null
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "business_update_id": business_update_id,
        },
    ).mappings().one()
    business_update = _get_business_update(db, business_update_id)
    raw_text = _meaningful_business_update_raw_text(business_update)
    attachment_context = _build_business_update_attachment_context(db, business_update_id)
    attachment_text = str(attachment_context.get("combined_text") or "").strip()
    combined_text = "\n\n".join(part for part in (raw_text, attachment_text) if part).strip()
    return {
        **_json_safe_dict(status_row),
        "all_terminal": int(status_row.get("active") or 0) == 0,
        "combined_text": combined_text,
        "has_usable_text": bool(combined_text),
    }


def _meaningful_business_update_raw_text(business_update: dict[str, Any]) -> str:
    raw_text = str(business_update.get("raw_text") or "").strip()
    if not raw_text:
        return ""
    metadata = business_update.get("metadata_json")
    source = str(metadata.get("source") or "") if isinstance(metadata, dict) else ""
    if source == "frontend_buyer_create_modal":
        marker = "【需求原文/补充材料】"
        if marker not in raw_text:
            return ""
        return raw_text.split(marker, 1)[1].strip()
    return raw_text
