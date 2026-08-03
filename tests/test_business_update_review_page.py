from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.app.api.routes.business_updates import (
    _compact_review_attachment,
    _compact_review_job,
    _compact_sample_run,
    _enrich_review_action,
    _entity_ref,
    _is_dedicated_buyer_intent_ingest,
    _parse_metadata_json_form,
    _parse_entity_types_form,
    _parse_uuid_list_form,
    _review_action_group_key,
    _review_page_overview,
    _should_auto_ocr_uploaded_attachment,
    _upload_ocr_policy,
    _unique_uuid_list,
    _validate_business_update_input_type,
    _validate_parse_entity_types,
)


BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000001")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000002")
ACTION_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_buyer_create_upload_uses_dedicated_intent_parser_only() -> None:
    assert _is_dedicated_buyer_intent_ingest(
        metadata={"source": "frontend_buyer_create_modal"},
        buyer_intent_ids=[BUSINESS_UPDATE_ID],
        auto_parse_linked_objects=True,
        parse_entity_types=["buyer_intent"],
    ) is True
    assert _is_dedicated_buyer_intent_ingest(
        metadata={"source": "business_update_drawer"},
        buyer_intent_ids=[BUSINESS_UPDATE_ID],
        auto_parse_linked_objects=True,
        parse_entity_types=["buyer_intent"],
    ) is False


def test_review_action_grouping_matches_review_page_tabs() -> None:
    assert _review_action_group_key({"action_type": "seller_fact_update"}) == "seller_update"
    assert _review_action_group_key({"action_type": "buyer_intent_update"}) == "buyer_intent_update"
    assert _review_action_group_key({"action_type": "buyer_seller_relation_update"}) == "relation_progress"
    assert _review_action_group_key({"action_type": "unresolved_item"}) == "exception"


def test_review_action_enrichment_exposes_change_preview_and_business_route() -> None:
    action = {
        "id": ACTION_ID,
        "business_update_id": BUSINESS_UPDATE_ID,
        "action_type": "seller_fact_update",
        "target_entity_type": "seller_target",
        "target_entity_id": SELLER_TARGET_ID,
        "proposed_changes_json": {"target_name": "新标的名", "pe_ratio": 12.5},
        "raw_evidence_text": "标的名和估值更新",
        "confidence": 0.86,
        "review_status": "pending_review",
        "applied_at": None,
        "seller_target_name": "旧标的名",
    }
    snapshots = {
        f"seller_target:{SELLER_TARGET_ID}": {
            "id": SELLER_TARGET_ID,
            "target_name": "旧标的名",
            "pe_ratio": 14,
        }
    }

    enriched = _enrich_review_action(action, [], snapshots)

    assert enriched["group_key"] == "seller_update"
    assert enriched["target_ref"]["route"] == f"/targets/{SELLER_TARGET_ID}"
    assert enriched["target_ref"]["debug_ref"] is None
    assert enriched["can_accept"] is True
    assert enriched["can_apply"] is False
    assert enriched["change_preview"][0]["field_path"] == "target_name"


def test_review_page_overview_counts_auto_apply_and_debug_flags() -> None:
    overview = _review_page_overview(
        {"processing_status": "partially_applied"},
        [
            {"review_status": "pending_review", "is_auto_applied": False, "applied_at": None},
            {"review_status": "auto_accepted", "is_auto_applied": True, "applied_at": "2026-06-02"},
        ],
        [{"id": "log-1"}],
        [{"status": "failed", "metadata_json": {}}, {"status": "failed", "metadata_json": {"failure_ignored": True}}, {"status": "running"}],
        [{"status": "failed", "error_code": "schema_failed"}],
    )

    assert overview["pending_review_count"] == 1
    assert overview["auto_applied_count"] == 1
    assert overview["failed_job_count"] == 1
    assert overview["ignored_failed_job_count"] == 1
    assert overview["running_job_count"] == 1
    assert overview["needs_review"] is True


def test_entity_ref_only_uses_debug_for_supported_entities() -> None:
    assert _entity_ref("seller_target", SELLER_TARGET_ID)["debug_ref"] is None
    session_ref = _entity_ref("recommendation_session", SELLER_TARGET_ID)
    assert session_ref["route"] == f"/recommendations/sessions/{SELLER_TARGET_ID}"
    assert session_ref["debug_ref"]["route"].endswith(f"/debug/entities/recommendation_session/{SELLER_TARGET_ID}")


def test_compact_review_attachment_exposes_latest_job_and_evidence() -> None:
    attachment_id = UUID("00000000-0000-0000-0000-000000000004")
    evidence_id = UUID("00000000-0000-0000-0000-000000000005")
    job_id = UUID("00000000-0000-0000-0000-000000000006")
    parsed_document_id = UUID("00000000-0000-0000-0000-000000000007")

    compacted = _compact_review_attachment(
        {
            "id": attachment_id,
            "file_name": "teaser.pdf",
            "file_type": "pdf",
            "mime_type": "application/pdf",
            "file_size": 1200,
            "storage_path": "mock://teaser.pdf",
            "parse_status": "parsed",
            "metadata_json": {
                "storage_backend": "local",
                "storage_uri": "mock://teaser.pdf",
                "content_sha256": "abc",
                "uploaded_text_content": "net profit 25m",
                "last_text_length": 24,
            },
            "link_type": "source_document",
            "linked_at": "2026-06-03",
            "latest_job_id": job_id,
            "latest_job_status": "succeeded",
            "latest_job_queue": "ocr",
            "latest_job_error_message": None,
            "latest_parsed_document_id": parsed_document_id,
            "latest_parsed_document_status": "parsed",
            "latest_evidence_id": evidence_id,
            "latest_evidence_text_excerpt": "net profit 25m",
            "latest_evidence_page_no": 1,
        }
    )

    assert compacted["latest_job"]["debug_ref"]["route"] == f"/debug/entities/background_job/{job_id}"
    assert compacted["parse_readiness"]["readiness_status"] == "parsed"
    assert compacted["parse_readiness"]["available_text_source"] == "parsed_document"
    assert compacted["parse_readiness"]["storage_backend"] == "local"
    assert compacted["parse_readiness"]["parsed_document_id"] == str(parsed_document_id)
    assert compacted["parse_readiness"]["evidence_id"] == str(evidence_id)
    assert compacted["parse_readiness"]["parsed_text_length"] == 24
    assert compacted["latest_parsed_document"]["id"] == parsed_document_id
    assert compacted["latest_evidence"]["id"] == evidence_id
    assert compacted["debug_ref"]["route"] == f"/debug/entities/attachment/{attachment_id}"


def test_compact_review_attachment_marks_parsed_pdf_without_upload_text_as_parsed() -> None:
    attachment_id = UUID("00000000-0000-0000-0000-000000000004")
    parsed_document_id = UUID("00000000-0000-0000-0000-000000000007")

    compacted = _compact_review_attachment(
        {
            "id": attachment_id,
            "file_name": "scan.pdf",
            "file_type": "pdf",
            "mime_type": "application/pdf",
            "file_size": 1200,
            "storage_path": "s3://bucket/scan.pdf",
            "parse_status": "parsed",
            "metadata_json": {
                "storage_backend": "s3",
                "storage_uri": "s3://bucket/scan.pdf",
                "last_text_length": 21802,
            },
            "link_type": "source_document",
            "linked_at": "2026-06-03",
            "latest_job_id": None,
            "latest_job_status": None,
            "latest_job_queue": None,
            "latest_job_error_message": None,
            "latest_parsed_document_id": parsed_document_id,
            "latest_parsed_document_status": "parsed",
            "latest_evidence_id": None,
            "latest_evidence_text_excerpt": None,
            "latest_evidence_page_no": None,
        }
    )

    readiness = compacted["parse_readiness"]

    assert readiness["readiness_status"] == "parsed"
    assert readiness["available_text_source"] == "parsed_document"
    assert readiness["text_available"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["parsed_document_id"] == str(parsed_document_id)
    assert readiness["parsed_text_length"] == 21802



def test_compact_review_job_exposes_ignore_metadata() -> None:
    job_id = UUID("00000000-0000-0000-0000-000000000010")

    compacted = _compact_review_job(
        {
            "id": job_id,
            "job_type": "business_update_extract_actions",
            "status": "failed",
            "queue_name": "llm",
            "attempt_count": 3,
            "max_attempts": 3,
            "error_code": "job_failed",
            "error_message": "Some actions are invalid.",
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "started_at": None,
            "finished_at": "2026-06-03",
            "metadata_json": {
                "failure_ignored": True,
                "failure_ignore_reason": "historical validation data",
                "failure_ignored_at": "2026-06-03T11:01:55+00:00",
            },
        }
    )

    assert compacted["ignored"] is True
    assert compacted["ignore_reason"] == "historical validation data"
    assert compacted["ignored_at"] == "2026-06-03T11:01:55+00:00"
    assert compacted["debug_ref"]["route"] == f"/debug/entities/background_job/{job_id}"


def test_compact_sample_run_exposes_pressure_test_summary() -> None:
    attachment_id = UUID("00000000-0000-0000-0000-000000000011")
    failed_job_id = UUID("00000000-0000-0000-0000-000000000012")

    compacted = _compact_sample_run(
        {
            "id": BUSINESS_UPDATE_ID,
            "raw_text": "sample raw text",
            "input_type": "mixed",
            "processing_status": "parsed",
            "created_at": "2026-06-05T10:00:00+00:00",
            "metadata_json": {
                "test_data": "true",
                "sample_label": "pinda_mixed_validation",
                "sample_object": "pinda_chuxing",
            },
            "action_count": 2,
            "pending_review_count": 2,
            "auto_applied_count": 0,
            "applied_action_count": 0,
            "job_count": 3,
            "failed_job_count": 1,
            "ignored_failed_job_count": 0,
            "running_job_count": 0,
            "trace_count": 2,
            "failed_trace_count": 0,
            "attachment_count": 2,
            "parsed_attachment_count": 1,
            "multimodal_image_count": 1,
            "parsing_attachment_count": 0,
            "skipped_attachment_count": 0,
            "failed_attachment_count": 0,
            "latest_failed_job": {
                "id": failed_job_id,
                "job_type": "business_update_extract_actions",
                "status": "failed",
                "queue_name": "llm",
                "error_code": "schema_validation",
                "error_message": "Some actions are invalid.",
                "created_at": "2026-06-05T10:01:00+00:00",
                "finished_at": "2026-06-05T10:02:00+00:00",
            },
            "attachment_preview": [
                {
                    "id": attachment_id,
                    "file_name": "teaser.pdf",
                    "file_type": "pdf",
                    "mime_type": "application/pdf",
                    "file_size": 1200,
                    "parse_status": "parsed",
                    "linked_at": "2026-06-05T10:00:30+00:00",
                    "parsed_document_id": "parsed-doc-1",
                    "parsed_text_length": "901",
                    "multimodal_image_supported": False,
                }
            ],
        }
    )

    assert compacted["business_update_id"] == BUSINESS_UPDATE_ID
    assert compacted["sample_metadata"]["test_data"] is True
    assert compacted["sample_metadata"]["sample_label"] == "pinda_mixed_validation"
    assert compacted["overview"]["action_count"] == 2
    assert compacted["overview"]["failed_job_count"] == 1
    assert compacted["overview"]["needs_attention"] is True
    assert compacted["latest_failed_job"]["debug_ref"]["route"] == f"/debug/entities/background_job/{failed_job_id}"
    assert compacted["attachments"][0]["parsed_text_length"] == 901
    assert compacted["attachments"][0]["debug_ref"]["route"] == f"/debug/entities/attachment/{attachment_id}"
    assert compacted["review_route"] == f"/business-updates/{BUSINESS_UPDATE_ID}/review-page"


def test_compact_sample_run_marks_skipped_attachment_as_attention() -> None:
    compacted = _compact_sample_run(
        {
            "id": BUSINESS_UPDATE_ID,
            "raw_text": "sample raw text",
            "input_type": "attachment",
            "processing_status": "failed",
            "created_at": "2026-06-05T10:00:00+00:00",
            "metadata_json": {"test_data": True, "sample_label": "docx"},
            "action_count": 0,
            "pending_review_count": 0,
            "auto_applied_count": 0,
            "applied_action_count": 0,
            "job_count": 1,
            "failed_job_count": 0,
            "ignored_failed_job_count": 0,
            "running_job_count": 0,
            "trace_count": 1,
            "failed_trace_count": 0,
            "attachment_count": 1,
            "parsed_attachment_count": 0,
            "multimodal_image_count": 0,
            "parsing_attachment_count": 0,
            "skipped_attachment_count": 1,
            "failed_attachment_count": 0,
            "latest_failed_job": None,
            "attachment_preview": [
                {
                    "id": UUID("00000000-0000-0000-0000-000000000013"),
                    "file_name": "need-parser.docx",
                    "parse_status": "skipped",
                    "parsed_document_id": None,
                    "parsed_text_length": 0,
                    "multimodal_image_supported": False,
                }
            ],
        }
    )

    assert compacted["overview"]["parsed_attachment_count"] == 0
    assert compacted["overview"]["skipped_attachment_count"] == 1
    assert compacted["overview"]["needs_attention"] is True


def test_validate_parse_entity_types_rejects_unsupported_values() -> None:
    _validate_parse_entity_types(["seller_target", "buyer_intent"])

    with pytest.raises(HTTPException) as exc_info:
        _validate_parse_entity_types(["buyer_party"])

    assert exc_info.value.status_code == 422


def test_business_update_upload_helpers_classify_images_as_multimodal_only() -> None:
    image = {"file_type": "jpg", "mime_type": "image/jpeg"}
    pdf = {"file_type": "pdf", "mime_type": "application/pdf"}
    text = {"file_type": "txt", "mime_type": "text/plain"}

    assert _upload_ocr_policy("jpg", "image/jpeg") == "multimodal_image_only"
    assert _should_auto_ocr_uploaded_attachment(image) is False
    assert _should_auto_ocr_uploaded_attachment(pdf) is True
    assert _should_auto_ocr_uploaded_attachment(text) is True


def test_business_update_form_helpers_parse_entity_types_and_validate_input_type() -> None:
    first = "00000000-0000-0000-0000-000000000008"
    second = "00000000-0000-0000-0000-000000000009"

    assert _parse_entity_types_form("seller_target,buyer_intent") == ["seller_target", "buyer_intent"]
    assert _parse_entity_types_form('["seller_target"]') == ["seller_target"]
    assert [str(item) for item in _parse_uuid_list_form(f'["{first}", "{second}"]')] == [first, second]
    assert [str(item) for item in _parse_uuid_list_form(f"{first},{first}")] == [first]
    assert _parse_metadata_json_form('{"test_data": true, "label": "pinda"}') == {
        "test_data": True,
        "label": "pinda",
    }
    _validate_business_update_input_type("mixed")

    with pytest.raises(HTTPException) as exc_info:
        _validate_business_update_input_type("attachment_validation")

    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as metadata_exc:
        _parse_metadata_json_form("[1,2,3]")

    assert metadata_exc.value.status_code == 422


def test_unique_uuid_list_preserves_order_and_dedupes() -> None:
    first = UUID("00000000-0000-0000-0000-000000000008")
    second = UUID("00000000-0000-0000-0000-000000000009")

    assert _unique_uuid_list([first, second, first]) == [first, second]
