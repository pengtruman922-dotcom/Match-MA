from decimal import Decimal
from uuid import UUID

from backend.app.api.routes.attachments import (
    _attachment_parse_readiness,
    _attachment_upload_policy,
    _compact_child_parse_job,
    _compact_ocr_job,
    _compact_ocr_trace,
    _linked_entity_refs,
    _parse_entity_types_form,
)
from backend.app.api.routes.business_updates import _save_business_update_upload_files
from backend.app.api.routes.field_sources import _field_value_source_out
from backend.app.config import get_settings
from backend.app.jobs.handlers import (
    _approx_token_count,
    _attachment_mock_extracted_text,
    _build_business_update_image_context,
    _business_update_action_evidence_id,
    _business_update_raw_text_with_attachments,
    _insert_llm_trace,
    _mark_bound_seller_targets_complete_after_business_update_parse,
    _mark_business_update_failed_if_final_attempt,
    _normalize_actions,
    _parse_requested_entity_types,
    _parse_source_context,
    _validate_extractor_output,
)
from backend.app.jobs.handlers.business_update import _verified_document_excerpt
from backend.app.jobs.queue import JobClaim
from backend.app.services.attachment_storage import decode_text_bytes, is_text_upload, safe_upload_filename

ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000001")
JOB_ID = UUID("00000000-0000-0000-0000-000000000002")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000003")
BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000004")


class _SqlCaptureResult:
    rowcount = 1

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return []


class _SqlCaptureDb:
    def __init__(self) -> None:
        self.sql_text = ""
        self.params = {}

    def execute(self, statement, params=None):
        self.sql_text = str(statement)
        self.params = params or {}
        return _SqlCaptureResult()


class _IndustryLookupResult:
    def __init__(self, value=None, values=None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.values


class _IndustryLookupDb:
    TERM_TO_L1 = {
        "医药与健康": "医药与健康",
        "医疗器械": "医药与健康",
    }

    def execute(self, statement, params=None):
        sql = str(statement)
        if "select l1_name" in sql:
            return _IndustryLookupResult(self.TERM_TO_L1.get((params or {}).get("term")))
        if "and level = 'l2'" in sql:
            return _IndustryLookupResult(values=["医疗器械"])
        raise AssertionError(f"Unexpected industry query: {sql}")


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


def test_attachment_upload_policy_explains_pdf_image_and_ocr(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "doc2x")
    monkeypatch.setenv("DOC2X_API_KEY", "sk-test")
    monkeypatch.setenv("ATTACHMENT_S3_BUCKET", "match-ma-test")
    monkeypatch.setenv("ATTACHMENT_S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ATTACHMENT_S3_SECRET_ACCESS_KEY", "sk")

    policy = _attachment_upload_policy()

    try:
        assert policy["max_upload_bytes"] > 0
        assert policy["max_files_per_business_update"] == 10
        assert policy["storage_backend"] == "s3"
        assert policy["object_storage_configured"] is True
        assert ".txt" in policy["supported_uploads"]["text_extensions"]
        assert policy["pdf_policy"]["text_detection"]["sample_page_limit"] == 5
        assert policy["pdf_policy"]["text_detection"]["min_total_chars_for_text_pdf"] == 200
        assert policy["pdf_policy"]["scanned_pdf"]["strategy"] == "doc2x_async_ocr"
        assert policy["pdf_policy"]["scanned_pdf"]["doc2x_configured"] is True
        assert policy["image_policy"]["strategy"] == "multimodal_llm_direct"
        assert policy["image_policy"]["auto_ocr"] is False
        assert policy["ocr_policy"]["doc2x"]["upload_timeout_seconds"] == 180
        assert policy["ocr_policy"]["doc2x"]["max_wait_seconds"] > 0
    finally:
        get_settings.cache_clear()


def test_business_update_upload_rejects_too_many_files() -> None:
    class _Settings:
        business_update_max_upload_files = 1

    try:
        _save_business_update_upload_files(None, [object(), object()], settings=_Settings())
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 413
        assert "Maximum is 1 files" in str(getattr(exc, "detail", ""))
    else:
        raise AssertionError("Expected too many files to be rejected.")


def test_decode_text_bytes_supports_utf8_and_gb18030() -> None:
    assert decode_text_bytes("测试文本".encode("utf-8")) == "测试文本"
    assert decode_text_bytes("测试文本".encode("gb18030")) == "测试文本"


def test_attachment_parse_readiness_is_ready_when_uploaded_text_exists() -> None:
    readiness = _attachment_parse_readiness(
        {
            "id": ATTACHMENT_ID,
            "file_name": "note.txt",
            "file_type": "txt",
            "mime_type": "text/plain",
            "storage_path": "local://attachments/note.txt",
            "metadata_json": {
                "storage_backend": "local",
                "storage_uri": "local://attachments/note.txt",
                "content_sha256": "abc",
                "uploaded_text_content": "  ready text  ",
            },
            "links": [],
        }
    )

    assert readiness["readiness_status"] == "ready"
    assert readiness["can_parse_now"] is True
    assert readiness["expected_parse_status"] == "parsed"
    assert readiness["available_text_source"] == "uploaded_text_content"
    assert readiness["text_preview"] == "ready text"


def test_attachment_parse_readiness_blocks_binary_without_text() -> None:
    readiness = _attachment_parse_readiness(
        {
            "id": ATTACHMENT_ID,
            "file_name": "teaser.pdf",
            "file_type": "pdf",
            "mime_type": "application/pdf",
            "storage_path": "local://attachments/teaser.pdf",
            "metadata_json": {"storage_backend": "local"},
            "links": [],
        }
    )

    assert readiness["readiness_status"] == "blocked"
    assert readiness["can_parse_now"] is False
    assert readiness["expected_parse_status"] == "skipped"
    assert readiness["is_binary_or_document"] is True
    assert "PDF OCR requires object storage" in readiness["blocking_reasons"][1]


def test_attachment_parse_readiness_does_not_treat_zero_text_document_as_parsed() -> None:
    readiness = _attachment_parse_readiness(
        {
            "id": ATTACHMENT_ID,
            "file_name": "need-parser.docx",
            "file_type": "docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "storage_path": "s3://bucket/need-parser.docx",
            "parse_status": "skipped",
            "metadata_json": {
                "storage_backend": "s3",
                "last_parsed_document_id": "pd-empty",
                "last_text_length": 0,
            },
            "links": [],
        }
    )

    assert readiness["readiness_status"] == "blocked"
    assert readiness["text_available"] is False
    assert readiness["parsed_document_id"] == "pd-empty"
    assert readiness["parsed_text_length"] == 0


def test_attachment_parse_readiness_marks_parsed_binary_as_parsed() -> None:
    readiness = _attachment_parse_readiness(
        {
            "id": ATTACHMENT_ID,
            "file_name": "teaser.pdf",
            "file_type": "pdf",
            "mime_type": "application/pdf",
            "storage_path": "s3://bucket/teaser.pdf",
            "parse_status": "parsed",
            "metadata_json": {
                "storage_backend": "s3",
                "last_parsed_document_id": "pd-1",
                "last_evidence_id": "ev-1",
                "last_text_length": 21802,
            },
            "links": [],
        }
    )

    assert readiness["readiness_status"] == "parsed"
    assert readiness["can_parse_now"] is False
    assert readiness["expected_parse_status"] == "parsed"
    assert readiness["available_text_source"] == "parsed_document"
    assert readiness["text_available"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["parsed_document_id"] == "pd-1"
    assert readiness["evidence_id"] == "ev-1"
    assert readiness["parsed_text_length"] == 21802


def test_attachment_parse_readiness_needs_text_for_non_binary_without_text() -> None:
    readiness = _attachment_parse_readiness(
        {
            "id": ATTACHMENT_ID,
            "file_name": "unknown.dat",
            "file_type": "dat",
            "mime_type": "application/octet-stream",
            "storage_path": "local://attachments/unknown.dat",
            "metadata_json": {},
            "links": [],
        }
    )

    assert readiness["readiness_status"] == "needs_text"
    assert readiness["can_parse_now"] is False
    assert readiness["is_binary_or_document"] is False


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
            "input_json": {
                "attachment_id": str(ATTACHMENT_ID),
                "storage_backend": "local",
                "storage_uri": "local://attachments/x",
                "content_sha256": "abc",
                "text_capture_source": "uploaded_text_content",
                "node_execution_mode": "skeleton",
                "api_key": "should-not-leak",
            },
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
    assert trace["input_json"]["storage_backend"] == "local"
    assert trace["input_json"]["content_sha256"] == "abc"
    assert "api_key" not in trace["input_json"]
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


def test_business_update_image_context_omits_null_trigger_uuid_predicate() -> None:
    db = _SqlCaptureDb()

    context = _build_business_update_image_context(db, BUSINESS_UPDATE_ID)

    assert context["images"] == []
    assert ":trigger_attachment_id is null" not in db.sql_text
    assert "and a.id = :trigger_attachment_id" not in db.sql_text


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


def test_business_update_retry_attempt_does_not_mark_failed() -> None:
    db = _SqlCaptureDb()
    job = JobClaim(
        id=JOB_ID,
        job_type="business_update_extract_actions",
        queue_name="llm",
        entity_type="business_update",
        entity_id=BUSINESS_UPDATE_ID,
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=3,
    )

    _mark_business_update_failed_if_final_attempt(db, job, BUSINESS_UPDATE_ID, "timeout")

    assert db.sql_text == ""


def test_business_update_final_attempt_marks_failed() -> None:
    db = _SqlCaptureDb()
    job = JobClaim(
        id=JOB_ID,
        job_type="business_update_extract_actions",
        queue_name="llm",
        entity_type="business_update",
        entity_id=BUSINESS_UPDATE_ID,
        correlation_id=None,
        payload_json={},
        attempt_count=3,
        max_attempts=3,
    )

    _mark_business_update_failed_if_final_attempt(db, job, BUSINESS_UPDATE_ID, "timeout")

    assert "set processing_status = 'failed'" in db.sql_text
    assert db.params["metadata_patch"]["last_processing_result"] == "failed"


def test_business_update_accepts_unambiguous_action_shape_aliases() -> None:
    parsed_output = {
        "actions": [
            {
                "action": "seller_fact_update",
                "target": "seller_target",
                "target_id": str(SELLER_TARGET_ID),
                "proposed_changes_json": {
                    "target_subject_name": "测试主体有限公司",
                    "listed_status": "listed",
                    "industry_primary": "制造与工业",
                },
            }
        ]
    }

    validation = _validate_extractor_output(parsed_output)
    actions = _normalize_actions(
        parsed_output,
        {
            "raw_text": "正式材料确认主体与上市状态",
            "bound_seller_target_ids_json": [str(SELLER_TARGET_ID)],
            "bound_buyer_party_ids_json": [],
            "bound_buyer_intent_ids_json": [],
            "attachment_evidence_ids": [],
            "image_evidence_attachment_ids": [],
        },
    )

    assert validation["valid"] is True
    assert validation["accepted_aliases"] == {
        "0": [
            "action_type<-action",
            "target_entity_type<-target",
            "target_entity_id<-target_id",
        ]
    }
    assert len(actions) == 1
    assert actions[0]["action_type"] == "seller_fact_update"
    assert actions[0]["target_entity_type"] == "seller_target"
    assert actions[0]["target_entity_id"] == SELLER_TARGET_ID
    assert actions[0]["proposed_changes_json"]["listed_status"] == "listed"
    assert actions[0]["normalization_notes"][:3] == validation["accepted_aliases"]["0"]


def test_business_update_derives_and_keeps_seller_industry_dimensions() -> None:
    actions = _normalize_actions(
        {
            "actions": [
                {
                    "action_type": "seller_fact_update",
                    "target_entity_type": "seller_target",
                    "target_entity_id": str(SELLER_TARGET_ID),
                    "proposed_changes_json": {
                        "industry_primary": "医药与健康",
                        "industry_secondary": "医疗器械",
                    },
                }
            ]
        },
        {
            "bound_seller_target_ids_json": [str(SELLER_TARGET_ID)],
            "bound_buyer_party_ids_json": [],
            "bound_buyer_intent_ids_json": [],
            "attachment_evidence_ids": [],
            "image_evidence_attachment_ids": [],
        },
        db=_IndustryLookupDb(),
    )

    assert actions[0]["proposed_changes_json"] == {
        "industry_l1": "医药与健康",
        "industry_l2": "医疗器械",
        "industry_primary": "医药与健康",
        "industry_secondary": "医疗器械",
    }


def test_business_update_extracts_profile_sections_outside_seller_columns() -> None:
    actions = _normalize_actions(
        {
            "actions": [
                {
                    "action_type": "seller_fact_update",
                    "target_entity_type": "seller_target",
                    "target_entity_id": str(SELLER_TARGET_ID),
                    "proposed_changes_json": {
                        "business_summary": "生命科学自动化设备企业",
                        "profile_sections_json": [
                            {
                                "section_code": "business_product",
                                "content_text": "提供实验室自动化设备及成套解决方案",
                                "source_excerpt": "为生命科学实验室提供自动化设备",
                                "confidence": 0.94,
                            },
                            {
                                "section_code": "tech_team",
                                "content_text": "移液技术全部自研，团队来自产业公司",
                            },
                        ],
                    },
                }
            ]
        },
        {
            "bound_seller_target_ids_json": [str(SELLER_TARGET_ID)],
            "bound_buyer_party_ids_json": [],
            "bound_buyer_intent_ids_json": [],
            "attachment_evidence_ids": [],
            "image_evidence_attachment_ids": [],
        },
    )

    assert actions[0]["proposed_changes_json"] == {
        "business_summary": "生命科学自动化设备企业"
    }
    assert [item["section_code"] for item in actions[0]["profile_sections"]] == [
        "business_product",
        "tech_team",
    ]


def test_attachment_profile_excerpt_tolerates_ocr_whitespace_only() -> None:
    excerpt = _verified_document_excerpt(
        "移液技术 100%自研，产品出货量 6000 台国内第一",
        attachment_evidence="其中移液技术 100% 自研。产品出货量 6000 台国内第一。",
        fallback_excerpt="fallback",
    )

    # Punctuation still differs, so this is not accepted as a verbatim-like quote.
    assert excerpt == "fallback"

    excerpt = _verified_document_excerpt(
        "移液技术 100%自研",
        attachment_evidence="其中移液技术 100% 自研，团队稳定",
        fallback_excerpt="fallback",
    )
    assert excerpt == "移液技术 100%自研"


def test_business_update_rejects_empty_actions_instead_of_reporting_success() -> None:
    validation = _validate_extractor_output({"actions": []})

    assert validation == {
        "valid": False,
        "error": "LLM output actions array must not be empty.",
    }


def test_business_update_unapplied_target_action_moves_target_to_pending_review() -> None:
    db = _SqlCaptureDb()

    changed = _mark_bound_seller_targets_complete_after_business_update_parse(
        db,
        {"bound_seller_target_ids_json": [str(SELLER_TARGET_ID)]},
        [],
        JOB_ID,
        pending_review=True,
    )

    assert changed == 1
    assert "set information_status = :information_status" in db.sql_text
    assert db.params["information_status"] == "pending_review"
    assert (
        db.params["metadata_patch"]["last_parse_completed_reason"]
        == "business_update_requires_review"
    )


def test_business_update_trace_uses_the_actual_specialized_node_name() -> None:
    db = _SqlCaptureDb()
    job = JobClaim(
        id=JOB_ID,
        job_type="business_update_extract_actions",
        queue_name="llm",
        entity_type="business_update",
        entity_id=BUSINESS_UPDATE_ID,
        correlation_id=BUSINESS_UPDATE_ID,
        payload_json={},
        attempt_count=1,
        max_attempts=3,
    )

    _insert_llm_trace(
        db,
        job=job,
        business_update_id=BUSINESS_UPDATE_ID,
        node_config={
            "node_name": "seller_target_update_parser",
            "provider_config_id": JOB_ID,
            "node_config_id": JOB_ID,
            "prompt_template_id": JOB_ID,
            "provider_name": "test",
            "model_name": "test-model",
            "prompt_version": "v-test",
            "output_schema_json": {},
        },
        status="failed",
        input_json={},
        prompt_messages_json=[],
        raw_output_text="{}",
        parsed_output_json={},
        schema_validation_json={"valid": False},
        latency_ms=1,
        error_code="schema_validation_failed",
        error_message="invalid",
    )

    assert ":node_name" in db.sql_text
    assert db.params["node_name"] == "seller_target_update_parser"
    assert db.params["metadata_json"]["source"] == "seller_target_update_parser"


def test_business_update_money_unit_normalization_corrects_100_yi_off_by_ten() -> None:
    actions = _normalize_actions(
        {
            "actions": [
                {
                    "action_type": "buyer_intent_update",
                    "target_entity_type": "buyer_intent",
                    "target_entity_id": None,
                    "proposed_changes_json": {
                        "max_valuation_yuan": 100000000000,
                        "raw_requirement_text": "市值范围：50亿元以内，可适当放宽到100亿。",
                    },
                    "raw_evidence_text": "市值范围\n50亿元以内，可适当放宽到100亿，具体视标的情况确定",
                    "confidence": 0.95,
                }
            ]
        },
        {
            "bound_seller_target_ids_json": [],
            "bound_buyer_party_ids_json": [],
            "bound_buyer_intent_ids_json": [],
        },
    )

    assert actions[0]["proposed_changes_json"]["max_valuation_yuan"] == Decimal("10000000000")
    assert actions[0]["normalization_notes"] == [
        "max_valuation_yuan:evidence_money_unit:100000000000->10000000000"
    ]


def test_business_update_money_unit_normalization_leaves_matching_amount() -> None:
    actions = _normalize_actions(
        {
            "actions": [
                {
                    "action_type": "buyer_intent_update",
                    "target_entity_type": "buyer_intent",
                    "target_entity_id": None,
                    "proposed_changes_json": {
                        "max_valuation_yuan": 1500000000,
                        "raw_requirement_text": "预算10-15亿。",
                    },
                    "raw_evidence_text": "上市公司收购款预算约10-15亿，可通过并购贷操作。",
                    "confidence": 0.95,
                }
            ]
        },
        {
            "bound_seller_target_ids_json": [],
            "bound_buyer_party_ids_json": [],
            "bound_buyer_intent_ids_json": [],
        },
    )

    assert actions[0]["proposed_changes_json"]["max_valuation_yuan"] == 1500000000
    assert actions[0]["normalization_notes"] == []


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
