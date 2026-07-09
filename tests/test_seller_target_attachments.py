from uuid import UUID

from backend.app.api.routes.seller_targets import (
    _compact_target_attachment,
    _target_attachment_display_status,
)

TARGET_ID = UUID("00000000-0000-0000-0000-000000000101")
ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000201")


def _row(**overrides):
    base = {
        "seller_target_id": TARGET_ID,
        "id": ATTACHMENT_ID,
        "file_name": "memo.pdf",
        "file_type": "pdf",
        "mime_type": "application/pdf",
        "file_size": 1024,
        "storage_path": "local://attachments/example/memo.pdf",
        "uploaded_by": UUID("00000000-0000-0000-0000-000000000301"),
        "uploaded_by_name": "管理员",
        "uploaded_at": "2026-07-09 10:00:00+00",
        "parse_status": "pending",
        "metadata_json": {},
        "deleted_at": None,
        "link_type": "business_update_context",
        "linked_at": "2026-07-09 10:00:01+00",
        "latest_job_id": None,
        "latest_job_status": None,
        "latest_job_queue": None,
        "latest_job_error_message": None,
        "latest_parsed_document_id": None,
        "latest_parsed_document_status": None,
        "latest_parsed_document_page_count": None,
        "latest_parsed_document_token_count": None,
        "latest_parsed_document_error_message": None,
        "latest_evidence_id": None,
        "latest_evidence_text_excerpt": None,
        "latest_evidence_page_no": None,
        "evidence_count": 0,
    }
    return {**base, **overrides}


def test_target_attachment_display_status_prioritizes_failed_job() -> None:
    status = _target_attachment_display_status(
        _row(latest_job_status="failed"),
        {"readiness_status": "parsed"},
    )

    assert status == "failed"


def test_target_attachment_display_status_treats_supported_image_as_image_evidence() -> None:
    status = _target_attachment_display_status(
        _row(file_name="chat.png", file_type="png", mime_type="image/png"),
        {"readiness_status": "ready_for_multimodal"},
    )

    assert status == "image_evidence"


def test_compact_target_attachment_includes_routes_and_latest_evidence() -> None:
    item = _compact_target_attachment(
        _row(
            parse_status="parsed",
            latest_evidence_id=UUID("00000000-0000-0000-0000-000000000401"),
            latest_evidence_text_excerpt="报价约10亿元。",
            latest_evidence_page_no=3,
            evidence_count=2,
        ),
        [{"id": UUID("00000000-0000-0000-0000-000000000501"), "review_route": "/updates/demo"}],
    )

    assert item["display_status"] == "parsed"
    assert item["uploaded_by_name"] == "管理员"
    assert item["latest_evidence"]["page_no"] == 3
    assert item["download_route"].endswith(f"/attachments/{ATTACHMENT_ID}/download")
    assert item["delete_route"].endswith(f"/attachments/{ATTACHMENT_ID}")
