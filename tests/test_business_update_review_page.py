from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.app.api.routes.business_updates import (
    _compact_review_attachment,
    _enrich_review_action,
    _entity_ref,
    _review_action_group_key,
    _review_page_overview,
    _unique_uuid_list,
    _validate_parse_entity_types,
)


BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000001")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000002")
ACTION_ID = UUID("00000000-0000-0000-0000-000000000003")


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
    assert compacted["parse_readiness"]["readiness_status"] == "ready"
    assert compacted["parse_readiness"]["available_text_source"] == "uploaded_text_content"
    assert compacted["parse_readiness"]["storage_backend"] == "local"
    assert compacted["latest_parsed_document"]["id"] == parsed_document_id
    assert compacted["latest_evidence"]["id"] == evidence_id
    assert compacted["debug_ref"]["route"] == f"/debug/entities/attachment/{attachment_id}"


def test_validate_parse_entity_types_rejects_unsupported_values() -> None:
    _validate_parse_entity_types(["seller_target", "buyer_intent"])

    with pytest.raises(HTTPException) as exc_info:
        _validate_parse_entity_types(["buyer_party"])

    assert exc_info.value.status_code == 422


def test_unique_uuid_list_preserves_order_and_dedupes() -> None:
    first = UUID("00000000-0000-0000-0000-000000000008")
    second = UUID("00000000-0000-0000-0000-000000000009")

    assert _unique_uuid_list([first, second, first]) == [first, second]
