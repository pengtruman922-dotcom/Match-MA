from uuid import UUID

from backend.app.api.routes.attachments import (
    _compact_ocr_job,
    _compact_ocr_trace,
    _linked_entity_refs,
)
from backend.app.jobs.handlers import _approx_token_count, _attachment_mock_extracted_text
from backend.app.jobs.queue import JobClaim

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
