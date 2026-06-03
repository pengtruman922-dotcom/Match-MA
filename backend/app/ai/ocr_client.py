from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class OcrCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrInput:
    attachment_id: str
    file_name: str
    file_type: str | None
    mime_type: str | None
    file_size: int | None
    storage_path: str | None
    metadata_json: dict[str, Any]
    extracted_text_hint: str


@dataclass(frozen=True)
class OcrResult:
    terminal_parse_status: str
    trace_status: str
    execution_mode: str
    extracted_text: str
    raw_output_text: str | None
    parsed_output_json: dict[str, Any]
    error_message: str | None
    latency_ms: int


def call_attachment_ocr(
    *,
    node_config: dict[str, Any],
    ocr_input: OcrInput,
) -> OcrResult:
    """Run the configured OCR node.

    v0.1 intentionally keeps real provider execution disabled. Text captured during upload,
    manual mock text, or local text fallback is treated as the OCR output so the evidence
    pipeline can be tested end-to-end before durable object storage and real OCR are added.
    """

    started = time.perf_counter()
    metadata_json = node_config.get("metadata_json") if isinstance(node_config.get("metadata_json"), dict) else {}
    execution_mode = str(metadata_json.get("execution_mode") or "skeleton")
    extracted_text = ocr_input.extracted_text_hint.strip()

    if extracted_text:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return OcrResult(
            terminal_parse_status="parsed",
            trace_status="succeeded",
            execution_mode="mock_text",
            extracted_text=extracted_text,
            raw_output_text=extracted_text,
            parsed_output_json={
                "execution_mode": "mock_text",
                "provider_execution_mode": execution_mode,
                "text_length": len(extracted_text),
                "text_preview": extracted_text[:1000],
                "evidence_created": True,
            },
            error_message=None,
            latency_ms=latency_ms,
        )

    error_message = _not_implemented_message(node_config, ocr_input)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return OcrResult(
        terminal_parse_status="skipped",
        trace_status="skipped",
        execution_mode=execution_mode,
        extracted_text="",
        raw_output_text=None,
        parsed_output_json={
            "execution_mode": execution_mode,
            "provider_execution_mode": execution_mode,
            "reason": error_message,
            "evidence_created": False,
        },
        error_message=error_message,
        latency_ms=latency_ms,
    )


def build_attachment_ocr_input_json(
    *,
    node_config: dict[str, Any],
    ocr_input: OcrInput,
) -> dict[str, Any]:
    metadata_json = ocr_input.metadata_json if isinstance(ocr_input.metadata_json, dict) else {}
    node_metadata = node_config.get("metadata_json") if isinstance(node_config.get("metadata_json"), dict) else {}
    return {
        "attachment_id": ocr_input.attachment_id,
        "file_name": ocr_input.file_name,
        "file_type": ocr_input.file_type,
        "mime_type": ocr_input.mime_type,
        "file_size": ocr_input.file_size,
        "storage_path": ocr_input.storage_path,
        "storage_backend": metadata_json.get("storage_backend"),
        "storage_uri": metadata_json.get("storage_uri") or ocr_input.storage_path,
        "content_sha256": metadata_json.get("content_sha256"),
        "text_capture_source": metadata_json.get("text_capture_source"),
        "uploaded_text_truncated": metadata_json.get("uploaded_text_truncated"),
        "has_text_hint": bool(ocr_input.extracted_text_hint.strip()),
        "node_execution_mode": node_metadata.get("execution_mode") or "skeleton",
        "provider_name": node_config.get("provider_name"),
        "model_name": node_config.get("model_name"),
    }


def _not_implemented_message(node_config: dict[str, Any], ocr_input: OcrInput) -> str:
    model_name = str(node_config.get("model_name") or "ocr")
    if _is_binary_or_document(ocr_input):
        return (
            f"OCR provider execution is not implemented for {model_name}; "
            "binary/document parsing requires durable object storage and a real OCR provider."
        )
    return (
        f"OCR provider execution is not implemented for {model_name}; "
        "provide mock_extracted_text or upload a supported text-like file for v0.1 parsing."
    )


def _is_binary_or_document(ocr_input: OcrInput) -> bool:
    file_type = (ocr_input.file_type or "").lower()
    mime_type = (ocr_input.mime_type or "").lower()
    return (
        file_type in {"pdf", "png", "jpg", "jpeg", "webp", "doc", "docx", "xls", "xlsx", "ppt", "pptx"}
        or mime_type.startswith("image/")
        or mime_type in {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    )
