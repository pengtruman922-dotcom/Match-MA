from uuid import UUID

from backend.app.api.routes.attachments import (
    _compact_child_parse_job,
    _compact_ocr_job,
    _compact_ocr_trace,
    _linked_entity_refs,
    _parse_entity_types_form,
)
from backend.app.api.routes.field_sources import _field_value_source_out
from backend.app.jobs.handlers import (
    _approx_token_count,
    _attachment_mock_extracted_text,
    _business_update_action_evidence_id,
    _business_update_raw_text_with_attachments,
    _parse_requested_entity_types,
    _parse_source_context,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.attachment_storage import decode_text_bytes, is_text_upload, safe_upload_filename

ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
JOB_ID = UUID("00000000-0000-0000-0000-000000000002")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_attachment_mock_text_prefers_job_payload() -> None:
    job = JobClaim(
        id=JOB_ID,
        job_type="attachment_ocr_parse",
        queue_name="ocr",
        entity_type="attachment",
        entity_id=ATTACHMENT_ID,
        correlation_id=None,
        payload_json={"mock_extracted_text": "payload text"},
        attempt_count=1,
        max_attempts=1,
    )

    text = _attachment_mock_extracted_text(
        job,
        {"metadata_json": {"mock_extracted_text": "metadata text"}},
    )

    assert text == "payload text"


def test_attachment_mock_text_falls_back_to_metadata() -> None:
    job = JobClaim(
        id=JOB_ID,
        job_type="attachment_ocr_parse",
        queue_name="ocr",
        entity_type="attachment",
        entity_id=ATTACHMENT_ID,
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=1,
    )

    text = _attachment_mock_extracted_text(
        job,
        {"metadata_json": {"mock_extracted_text": " metadata text "}},
    )

    assert text == "metadata text"


def test_attachment_mock_text_uses_uploaded_text_metadata() -> None:
    job = JobClaim(
        id=JOB_ID,
        job_type="attachment_ocr_parse",
        queue_name="ocr",
        entity_type="attachment",
        entity_id=ATTACHMENT_ID,
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=1,
    )

    text = _attachment_mock_extracted_text(
        job,
        {"metadata_json": {"uploaded_text_content": " uploaded text "}},
    )

    assert text == "uploaded text"


def test_upload_helpers_normalize_file_inputs() -> None:
    assert safe_upload_filename("../foo bar(1).txt") == "foo_bar_1_.txt"
    assert is_text_upload("note.md", None) is True
    assert is_text_upload("file.bin", "application/octet-stream") is False
    assert _parse_entity_types_form("seller_target,buyer_intent") == ["seller_target", "buyer_intent"]
    assert _parse_entity_types_form('["seller_target"]') == ["seller_target"]


def test_decode_text_bytes_supports_utf8_and_gb18030() -> None:
    assert decode_text_bytes("测试文本".encode("utf-8")) == "测试文本"
    assert decode_text_bytes("测试文本".encode("gb18030")) == "测试文本"


def test_compact_attachment_ocr_status_helpers_expose_debug_refs() -> None:
    job = _compact_ocr_job(
        {
            "id": JOB_ID,
            "job_type": "attachment_ocr_parse",
            "status": "succeeded",
            "queue_name": "ocr",
            "error_code": None,
            "error_message": None,
            "attempt_count": 1,
            "max_attempts": 1,
            "started_at": "2026-06-03",
            "finished_at": "2026-06-03",
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "result_json": {"parse_status": "parsed"},
        }
    )
    trace = _compact_ocr_trace(
        {
            "id": UUID("00000000-0000-0000-0000-000000000004"),
            "trace_type": "ocr",
            "node_name": "ocr_attachment_parser",
            "job_id": JOB_ID,
            "provider_name": "aliyun_dashscope",
            "model_name": "ocr-skeleton-v0",
            "status": "succeeded",
            "raw_output_text": "x" * 900,
            "parsed_output_json": {"evidence_created": True},
            "schema_validation_json": {"valid": True},
            "error_code": None,
            "error_message": None,
            "latency_ms": 5,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "started_at": "2026-06-03",
            "finished_at": "2026-06-03",
        }
    )

    assert job["debug_ref"]["route"] == f"/debug/entities/background_job/{JOB_ID}"
    assert trace["raw_output_preview"].endswith("...")
    assert trace["debug_ref"]["entity_type"] == "background_job"


def test_linked_entity_refs_include_routes_and_debug_refs() -> None:
    refs = _linked_entity_refs(
        [
            {
                "entity_type": "seller_target",
                "entity_id": SELLER_TARGET_ID,
                "link_type": "source_document",
            }
        ]
    )

    assert refs[0]["route"] == f"/targets/{SELLER_TARGET_ID}"
    assert refs[0]["debug_ref"]["route"] == f"/debug/entities/seller_target/{SELLER_TARGET_ID}"


def test_approx_token_count_is_nonzero_for_short_text() -> None:
    assert _approx_token_count("abc") == 1
    assert _approx_token_count("a" * 20) == 5


def test_parse_source_context_carries_attachment_evidence() -> None:
    evidence_id = UUID("00000000-0000-0000-0000-000000000005")
    parsed_document_id = UUID("00000000-0000-0000-0000-000000000006")
    job = JobClaim(
        id=JOB_ID,
        job_type="seller_target_parse",
        queue_name="llm",
        entity_type="seller_target",
        entity_id=SELLER_TARGET_ID,
        correlation_id=None,
        payload_json={
            "source_type": "attachment_ocr_parse",
            "source_id": str(JOB_ID),
            "source_label": "Attachment OCR",
            "attachment_id": str(ATTACHMENT_ID),
            "parsed_document_id": str(parsed_document_id),
            "evidence_id": str(evidence_id),
        },
        attempt_count=1,
        max_attempts=3,
    )

    context = _parse_source_context(
        job,
        default_source_type="seller_target_parse",
        default_source_label="Seller parser",
    )

    assert context["source_type"] == "attachment_ocr_parse"
    assert context["source_id"] == JOB_ID
    assert context["attachment_id"] == ATTACHMENT_ID
    assert context["parsed_document_id"] == parsed_document_id
    assert context["evidence_id"] == evidence_id


def test_parse_requested_entity_types_defaults_to_supported_objects() -> None:
    assert _parse_requested_entity_types([]) == {"seller_target", "buyer_intent"}
    assert _parse_requested_entity_types(["seller_target", "unsupported"]) == {"seller_target"}


def test_business_update_raw_text_appends_attachment_evidence() -> None:
    raw_text = _business_update_raw_text_with_attachments(
        "manual note",
        {"combined_text": "[Attachment evidence ev-1]\nprofit 25m"},
    )

    assert raw_text.startswith("manual note")
    assert "Attachment OCR evidence" in raw_text
    assert "profit 25m" in raw_text


def test_business_update_action_evidence_id_uses_single_attachment_evidence() -> None:
    evidence_id = UUID("00000000-0000-0000-0000-000000000010")

    resolved = _business_update_action_evidence_id(
        {"raw_evidence_text": "profit 25m"},
        {"attachment_evidence_ids": [str(evidence_id)]},
    )

    assert resolved == evidence_id


def test_business_update_action_evidence_id_prefers_explicit_value() -> None:
    explicit_id = UUID("00000000-0000-0000-0000-000000000011")
    other_id = UUID("00000000-0000-0000-0000-000000000012")

    resolved = _business_update_action_evidence_id(
        {"evidence_id": str(explicit_id), "raw_evidence_text": "profit 25m"},
        {"attachment_evidence_ids": [str(other_id)]},
    )

    assert resolved == explicit_id


def test_business_update_action_evidence_id_skips_ambiguous_attachment_evidence() -> None:
    resolved = _business_update_action_evidence_id(
        {"raw_evidence_text": "profit 25m"},
        {
            "attachment_evidence_ids": [
                "00000000-0000-0000-0000-000000000013",
                "00000000-0000-0000-0000-000000000014",
            ]
        },
    )

    assert resolved is None


def test_compact_child_parse_job_links_debug_refs() -> None:
    child = _compact_child_parse_job(
        {
            "id": JOB_ID,
            "job_type": "seller_target_parse",
            "status": "queued",
            "queue_name": "llm",
            "entity_type": "seller_target",
            "entity_id": SELLER_TARGET_ID,
            "error_code": None,
            "error_message": None,
            "attempt_count": 0,
            "max_attempts": 3,
            "started_at": None,
            "finished_at": None,
            "created_at": "2026-06-03",
            "updated_at": "2026-06-03",
            "result_json": {},
        }
    )

    assert child["debug_ref"]["route"] == f"/debug/entities/background_job/{JOB_ID}"
    assert child["target_debug_ref"]["route"] == f"/debug/entities/seller_target/{SELLER_TARGET_ID}"


def test_field_value_source_out_includes_evidence_and_debug_ref() -> None:
    source = _field_value_source_out(
        {
            "id": UUID("00000000-0000-0000-0000-000000000007"),
            "entity_type": "seller_target",
            "entity_id": SELLER_TARGET_ID,
            "field_path": "business_summary",
            "value_snapshot_json": {"value": "summary"},
            "source_type": "attachment_ocr_parse",
            "source_id": JOB_ID,
            "evidence_id": UUID("00000000-0000-0000-0000-000000000008"),
            "source_label": "Attachment OCR",
            "confidence": None,
            "review_status": "auto_accepted",
            "created_at": "2026-06-03",
            "created_by": UUID("00000000-0000-0000-0000-000000000201"),
            "ev_id": UUID("00000000-0000-0000-0000-000000000008"),
            "ev_source_type": "attachment_ocr_parse",
            "ev_source_id": JOB_ID,
            "ev_attachment_id": ATTACHMENT_ID,
            "ev_parsed_document_id": UUID("00000000-0000-0000-0000-000000000009"),
            "ev_page_no": 1,
            "ev_slide_no": None,
            "ev_sheet_name": None,
            "ev_cell_range": None,
            "ev_text_excerpt": "OCR excerpt",
            "ev_char_start": 0,
            "ev_char_end": 11,
            "ev_created_at": "2026-06-03",
        }
    )

    assert source["debug_ref"]["route"] == f"/debug/entities/background_job/{JOB_ID}"
    assert source["evidence_span"]["text_excerpt"] == "OCR excerpt"
