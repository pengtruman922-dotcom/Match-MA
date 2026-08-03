from __future__ import annotations

from typing import Any

from backend.app.services.image_inputs import is_supported_multimodal_image


def attachment_waits_for_text_extraction(attachment: dict[str, Any]) -> bool:
    if str(attachment.get("parse_status") or "") not in {"pending", "parsing"}:
        return False
    ocr_policy = _attachment_ocr_policy(attachment)
    if ocr_policy in {"multimodal_image_only", "skip_ocr"}:
        return False
    # Older image rows may predate the explicit upload policy.
    return not is_supported_multimodal_image(attachment)


def attachment_content_extraction_status(
    attachment: dict[str, Any],
    *,
    latest_job_status: str | None = None,
) -> str:
    """Map storage state to the product-facing attachment reading state."""
    stored_status = str(attachment.get("parse_status") or "pending")
    job_status = str(latest_job_status or "")
    if stored_status in {"pending", "parsing"} and job_status in {"failed", "canceled", "cancelled"}:
        stored_status = "failed"
    if stored_status in {"pending", "parsing", "skipped"}:
        ocr_policy = _attachment_ocr_policy(attachment)
        if ocr_policy == "multimodal_image_only" or is_supported_multimodal_image(attachment):
            return "multimodal"
        if ocr_policy == "skip_ocr":
            return "skipped"
    return {
        "pending": "pending",
        "parsing": "processing",
        "parsed": "succeeded",
        "failed": "failed",
        "skipped": "skipped",
    }.get(stored_status, "pending")


def attachment_extraction_strategy(attachment: dict[str, Any]) -> str | None:
    if _attachment_ocr_policy(attachment) == "multimodal_image_only" or is_supported_multimodal_image(attachment):
        return "multimodal_llm_direct"
    metadata = attachment.get("metadata_json")
    if not isinstance(metadata, dict):
        return None
    if metadata.get("last_ocr_provider"):
        return str(metadata["last_ocr_provider"])
    if metadata.get("last_office_kind"):
        return "office_text_layer"
    return None


def _attachment_ocr_policy(attachment: dict[str, Any]) -> str:
    metadata = attachment.get("metadata_json")
    return str(metadata.get("ocr_policy") or "") if isinstance(metadata, dict) else ""
