from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

import backend.app.api.routes.business_updates as business_update_routes
import backend.app.jobs.handlers.attachment_ocr as attachment_ocr
import backend.app.jobs.handlers.relation_followup as relation_followup
import backend.app.services.business_update_flow as business_update_flow
from backend.app.jobs.queue import JobClaim
from backend.app.services.attachment_status import (
    attachment_content_extraction_status,
    attachment_extraction_strategy,
    attachment_waits_for_text_extraction,
)


BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000101")
RELATION_ID = UUID("00000000-0000-0000-0000-000000000102")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000103")
BUYER_INTENT_ID = UUID("00000000-0000-0000-0000-000000000104")
OTHER_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000105")
JOB_ID = UUID("00000000-0000-0000-0000-000000000106")
ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000107")


class _RelationResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _RelationDb:
    def __init__(self, row):
        self.row = row

    def execute(self, statement, params=None):
        return _RelationResult(self.row)


class _CaptureDb:
    def __init__(self):
        self.executions: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params or {}))
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _job(*, attempt_count: int = 1, max_attempts: int = 1, payload_json=None) -> JobClaim:
    return JobClaim(
        id=JOB_ID,
        job_type="relation_followup_draft_parse",
        queue_name="llm",
        entity_type="business_update",
        entity_id=BUSINESS_UPDATE_ID,
        correlation_id=BUSINESS_UPDATE_ID,
        payload_json=payload_json or {"include_attachment_text": True},
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    )


def test_both_scope_dispatches_basic_info_and_follow_up_jobs(monkeypatch) -> None:
    job_types: list[str] = []
    monkeypatch.setattr(
        business_update_flow,
        "_business_update_processing_scope",
        lambda db, business_update_id: "both",
    )

    def fake_enqueue(db, *, business_update_id, include_attachment_text, source, job_type):
        job_types.append(job_type)
        return {
            "id": UUID(int=len(job_types)),
            "job_type": job_type,
            "status": "queued",
            "queue_name": "llm",
            "entity_id": business_update_id,
            "reused_existing": False,
        }

    monkeypatch.setattr(business_update_flow, "_enqueue_business_update_process_job_type", fake_enqueue)

    result = business_update_flow._enqueue_business_update_process_job(
        object(),
        business_update_id=BUSINESS_UPDATE_ID,
        include_attachment_text=True,
        source="test",
    )

    assert job_types == [
        business_update_flow.BUSINESS_UPDATE_BASIC_JOB_TYPE,
        business_update_flow.BUSINESS_UPDATE_FOLLOWUP_JOB_TYPE,
    ]
    assert [job["job_type"] for job in result["jobs"]] == job_types
    assert result["processing_scope"] == "both"


def test_follow_up_retry_dispatches_only_follow_up_job(monkeypatch) -> None:
    job_types: list[str] = []
    monkeypatch.setattr(
        business_update_flow,
        "_business_update_processing_scope",
        lambda db, business_update_id: "both",
    )

    def fake_enqueue(db, *, business_update_id, include_attachment_text, source, job_type):
        job_types.append(job_type)
        return {
            "id": JOB_ID,
            "job_type": job_type,
            "status": "queued",
            "queue_name": "llm",
            "entity_id": business_update_id,
        }

    monkeypatch.setattr(business_update_flow, "_enqueue_business_update_process_job_type", fake_enqueue)

    result = business_update_flow._enqueue_business_update_process_job(
        object(),
        business_update_id=BUSINESS_UPDATE_ID,
        include_attachment_text=True,
        source="test_retry",
        branch="follow_up",
    )

    assert job_types == [business_update_flow.BUSINESS_UPDATE_FOLLOWUP_JOB_TYPE]
    assert result["job_type"] == business_update_flow.BUSINESS_UPDATE_FOLLOWUP_JOB_TYPE
    assert result["branch"] == "follow_up"


def test_follow_up_scope_requires_relation() -> None:
    with pytest.raises(HTTPException) as exc_info:
        business_update_routes._validated_processing_scope_metadata(
            object(),
            SimpleNamespace(user_id=UUID(int=1)),
            processing_scope="follow_up",
            bound_relation_id=None,
            seller_target_ids=[SELLER_TARGET_ID],
            buyer_intent_ids=[],
        )

    assert exc_info.value.status_code == 422
    assert "必须选择推进关系" in str(exc_info.value.detail)


def test_direct_follow_up_is_recorded_without_requesting_a_draft(monkeypatch) -> None:
    monkeypatch.setattr(business_update_routes, "ensure_relation_visible", lambda *args: None)
    metadata = business_update_routes._validated_processing_scope_metadata(
        _RelationDb({"seller_target_id": SELLER_TARGET_ID, "buyer_intent_id": BUYER_INTENT_ID}),
        SimpleNamespace(user_id=UUID(int=1)),
        processing_scope="follow_up",
        bound_relation_id=RELATION_ID,
        seller_target_ids=[SELLER_TARGET_ID],
        buyer_intent_ids=[],
        followup_entry_mode="direct",
        followup_event_type="call",
    )

    assert metadata["followup_entry_mode"] == "direct"
    assert metadata["followup_event_type"] == "call"
    assert metadata["followup_draft_status"] == "not_requested"


def test_follow_up_rejects_system_event_types(monkeypatch) -> None:
    monkeypatch.setattr(business_update_routes, "ensure_relation_visible", lambda *args: None)
    with pytest.raises(HTTPException) as exc_info:
        business_update_routes._validated_processing_scope_metadata(
            _RelationDb({"seller_target_id": SELLER_TARGET_ID, "buyer_intent_id": BUYER_INTENT_ID}),
            SimpleNamespace(user_id=UUID(int=1)),
            processing_scope="follow_up",
            bound_relation_id=RELATION_ID,
            seller_target_ids=[SELLER_TARGET_ID],
            buyer_intent_ids=[],
            followup_event_type="deal_closed",
        )

    assert exc_info.value.status_code == 422
    assert "动态类型" in str(exc_info.value.detail)


def test_follow_up_only_update_does_not_mark_bound_target_parsing() -> None:
    class _CaptureDb:
        def __init__(self) -> None:
            self.sql = ""

        def execute(self, statement, params):
            self.sql = str(statement)

    db = _CaptureDb()

    business_update_flow._mark_bound_seller_targets_parsing(db, BUSINESS_UPDATE_ID)

    assert "metadata_json ->> 'processing_scope'" in db.sql
    assert "in ('basic_info', 'both')" in db.sql


def test_bound_relation_must_belong_to_current_entity(monkeypatch) -> None:
    monkeypatch.setattr(business_update_routes, "ensure_relation_visible", lambda *args: None)
    db = _RelationDb(
        {
            "seller_target_id": OTHER_ENTITY_ID,
            "buyer_intent_id": BUYER_INTENT_ID,
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        business_update_routes._validated_processing_scope_metadata(
            db,
            SimpleNamespace(user_id=UUID(int=1)),
            processing_scope="both",
            bound_relation_id=RELATION_ID,
            seller_target_ids=[SELLER_TARGET_ID],
            buyer_intent_ids=[],
        )

    assert exc_info.value.status_code == 422
    assert "不属于当前标的" in str(exc_info.value.detail)


def test_bound_relation_must_be_visible(monkeypatch) -> None:
    def reject(*args):
        raise HTTPException(status_code=404, detail="Relation not found.")

    monkeypatch.setattr(business_update_routes, "ensure_relation_visible", reject)

    with pytest.raises(HTTPException) as exc_info:
        business_update_routes._validated_processing_scope_metadata(
            _RelationDb(None),
            SimpleNamespace(user_id=UUID(int=1)),
            processing_scope="follow_up",
            bound_relation_id=RELATION_ID,
            seller_target_ids=[SELLER_TARGET_ID],
            buyer_intent_ids=[],
        )

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    ("value", "error_fragment"),
    [
        ({"content": "", "next_step": None}, "non-empty"),
        ({"content": "已沟通", "next_step": None, "status": "interested"}, "Unsupported"),
        ({"content": "已沟通", "next_step": ["寄资料"]}, "string or null"),
        ([{"content": "已沟通"}], "JSON object"),
    ],
)
def test_follow_up_draft_normalizer_rejects_invalid_shapes(value, error_fragment) -> None:
    draft, validation = relation_followup._normalize_relation_followup_draft(value)

    assert validation["valid"] is False
    assert error_fragment in validation["error"]
    assert draft == {"content": "", "next_step": None}


def test_follow_up_draft_normalizer_accepts_only_content_and_next_step() -> None:
    draft, validation = relation_followup._normalize_relation_followup_draft(
        {"content": "  已与买方沟通  ", "next_step": "  周五发送材料  "}
    )

    assert validation["valid"] is True
    assert draft == {"content": "已与买方沟通", "next_step": "周五发送材料"}


def test_follow_up_draft_normalizer_respects_relation_event_limits() -> None:
    draft, validation = relation_followup._normalize_relation_followup_draft(
        {"content": "沟" * 4100, "next_step": "下一步" * 400}
    )

    assert validation["valid"] is True
    assert len(draft["content"]) == 4000
    assert len(draft["next_step"]) == 1000


def test_follow_up_handler_auto_fills_the_timeline_event(monkeypatch) -> None:
    db = _CaptureDb()
    traces: list[dict] = []
    llm_calls: list[dict] = []
    completed_events: list[dict] = []
    monkeypatch.setattr(
        relation_followup,
        "_get_business_update",
        lambda db, business_update_id: {
            "id": business_update_id,
            "raw_text": "买方表示感兴趣，下周发材料。",
            "metadata_json": {
                "processing_scope": "follow_up",
                "bound_relation_id": str(RELATION_ID),
            },
        },
    )
    monkeypatch.setattr(
        relation_followup,
        "_relation_followup_context",
        lambda db, relation_id: {"id": str(relation_id), "status": "interested"},
    )
    monkeypatch.setattr(
        relation_followup,
        "_build_business_update_attachment_context",
        lambda *args, **kwargs: {"attachments": [], "combined_text": "", "evidence_ids": []},
    )
    monkeypatch.setattr(
        relation_followup,
        "_build_business_update_image_context",
        lambda *args, **kwargs: {
            "images": [
                {
                    "attachment_id": str(ATTACHMENT_ID),
                    "file_name": "chat.png",
                    "data_url": "data:image/png;base64,YQ==",
                }
            ],
            "summaries": [{"attachment_id": str(ATTACHMENT_ID)}],
        },
    )
    monkeypatch.setattr(relation_followup, "_business_update_raw_text_with_attachments", lambda raw, ctx: raw)
    monkeypatch.setattr(
        relation_followup,
        "_get_default_node_config",
        lambda db, node_name: {
            "node_name": node_name,
            "base_url": "https://example.invalid",
            "api_key_secret_ref": "TEST_KEY",
            "api_key_encrypted": None,
            "model_name": "test-model",
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 1000,
            "timeout_seconds": 30,
            "response_format": {"type": "json_object"},
            "prompt_version": "v1",
        },
    )
    monkeypatch.setattr(
        relation_followup,
        "_render_prompt_messages",
        lambda config, values: [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
    )
    def fake_llm_call(**kwargs):
        llm_calls.append(kwargs)
        return SimpleNamespace(
            parsed_output_json={"content": "买方表示感兴趣。", "next_step": "下周发送材料。"},
            raw_output_text='{"content":"买方表示感兴趣。","next_step":"下周发送材料。"}',
            latency_ms=12,
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        )

    monkeypatch.setattr(relation_followup, "call_openai_compatible_chat", fake_llm_call)
    monkeypatch.setattr(
        relation_followup,
        "_insert_llm_trace",
        lambda db, **kwargs: traces.append(kwargs),
    )
    monkeypatch.setattr(
        relation_followup,
        "complete_ai_followup_event",
        lambda db, **kwargs: completed_events.append(kwargs) or True,
    )

    result = relation_followup._handle_relation_followup_draft_parse(db, _job())

    assert result["draft"] == {"content": "买方表示感兴趣。", "next_step": "下周发送材料。"}
    assert traces[0]["status"] == "succeeded"
    image_instruction = llm_calls[0]["messages"][1]["content"][1]["text"]
    assert "clearly preserve who said what" in image_instruction
    assert "explicit next action with its actor and deadline" in image_instruction
    assert "Do not output attachment ids, raw_evidence_text" in image_instruction
    assert db.commits == 1
    all_sql = "\n".join(sql.lower() for sql, _ in db.executions)
    assert "update business_update" in all_sql
    assert completed_events == [{
        "business_update_id": BUSINESS_UPDATE_ID,
        "job_id": JOB_ID,
        "content": "买方表示感兴趣。",
        "next_step": "下周发送材料。",
    }]
    metadata_patch = db.executions[-1][1]["metadata_patch"]
    assert metadata_patch["followup_draft_status"] == "succeeded"


def test_final_context_failure_marks_follow_up_draft_failed(monkeypatch) -> None:
    db = _CaptureDb()
    failed_events: list[dict] = []
    monkeypatch.setattr(
        relation_followup,
        "_get_business_update",
        lambda db, business_update_id: {
            "id": business_update_id,
            "raw_text": "沟通内容",
            "metadata_json": {
                "processing_scope": "follow_up",
                "bound_relation_id": str(RELATION_ID),
            },
        },
    )
    monkeypatch.setattr(
        relation_followup,
        "_relation_followup_context",
        lambda db, relation_id: (_ for _ in ()).throw(ValueError("Bound relation no longer exists.")),
    )
    monkeypatch.setattr(
        relation_followup,
        "fail_ai_followup_event",
        lambda db, **kwargs: failed_events.append(kwargs) or True,
    )

    with pytest.raises(ValueError, match="no longer exists"):
        relation_followup._handle_relation_followup_draft_parse(db, _job())

    assert db.rollbacks == 1
    assert db.commits == 1
    metadata_patch = db.executions[-1][1]["metadata_patch"]
    assert metadata_patch["followup_draft_status"] == "failed"
    assert "no longer exists" in metadata_patch["followup_draft_error"]
    assert failed_events[0]["business_update_id"] == BUSINESS_UPDATE_ID
    assert failed_events[0]["job_id"] == JOB_ID
    assert "no longer exists" in failed_events[0]["error_message"]


def test_ocr_completion_uses_scope_aware_business_update_dispatcher(monkeypatch) -> None:
    db = _CaptureDb()
    calls: list[dict] = []

    def fake_enqueue(db, **kwargs):
        calls.append(kwargs)
        return {
            "id": JOB_ID,
            "job_type": business_update_flow.BUSINESS_UPDATE_BASIC_JOB_TYPE,
            "status": "queued",
            "queue_name": "llm",
            "entity_id": BUSINESS_UPDATE_ID,
            "processing_scope": "both",
            "jobs": [
                {"job_type": business_update_flow.BUSINESS_UPDATE_BASIC_JOB_TYPE},
                {"job_type": business_update_flow.BUSINESS_UPDATE_FOLLOWUP_JOB_TYPE},
            ],
        }

    monkeypatch.setattr(attachment_ocr, "_enqueue_business_update_process_job", fake_enqueue)
    monkeypatch.setattr(
        attachment_ocr,
        "_business_update_content_readiness",
        lambda *_args, **_kwargs: {"all_terminal": True, "combined_text": "OCR 文本"},
    )
    ocr_job = JobClaim(
        id=UUID(int=200),
        job_type="attachment_ocr_parse",
        queue_name="ocr",
        entity_type="attachment",
        entity_id=ATTACHMENT_ID,
        correlation_id=BUSINESS_UPDATE_ID,
        payload_json={
            "business_update_id": str(BUSINESS_UPDATE_ID),
            "process_business_update_after_ocr": True,
            "include_attachment_text": True,
        },
        attempt_count=1,
        max_attempts=3,
    )

    result = attachment_ocr._enqueue_business_update_process_after_ocr(
        db,
        job=ocr_job,
        attachment_id=ATTACHMENT_ID,
        evidence_id=None,
        extracted_text="OCR 文本",
    )

    assert calls == [
        {
            "business_update_id": BUSINESS_UPDATE_ID,
            "include_attachment_text": True,
            "source": "attachment_ocr_auto_business_update_process",
        }
    ]
    assert result["id"] == str(JOB_ID)
    assert [job["job_type"] for job in result["jobs"]] == [
        business_update_flow.BUSINESS_UPDATE_BASIC_JOB_TYPE,
        business_update_flow.BUSINESS_UPDATE_FOLLOWUP_JOB_TYPE,
    ]
    assert "update business_update" in db.executions[-1][0].lower()


def test_ocr_fan_in_does_not_wait_for_direct_multimodal_images() -> None:
    summary = attachment_ocr._summarize_business_update_attachment_statuses(
        [
            {
                "parse_status": "parsed",
                "file_type": "pdf",
                "mime_type": "application/pdf",
                "metadata_json": {"ocr_policy": "auto_ocr"},
            },
            {
                "parse_status": "parsed",
                "file_type": None,
                "mime_type": "text/plain",
                "metadata_json": {"ocr_policy": "auto_ocr"},
            },
            {
                "parse_status": "pending",
                "file_type": "jpg",
                "mime_type": "image/jpeg",
                "metadata_json": {"ocr_policy": "multimodal_image_only"},
            },
            {
                "parse_status": "pending",
                "file_type": "webp",
                "mime_type": None,
                "metadata_json": {},
            },
        ]
    )

    assert summary == {"total": 4, "active": 0, "succeeded": 2, "failed": 0, "skipped": 0}


def test_ocr_fan_in_still_waits_for_pending_text_extraction() -> None:
    summary = attachment_ocr._summarize_business_update_attachment_statuses(
        [
            {
                "parse_status": "parsing",
                "file_type": "pdf",
                "mime_type": "application/pdf",
                "metadata_json": {"ocr_policy": "auto_ocr"},
            },
            {
                "parse_status": "pending",
                "file_type": "bin",
                "mime_type": "application/octet-stream",
                "metadata_json": {"ocr_policy": "skip_ocr"},
            },
        ]
    )

    assert summary == {"total": 2, "active": 1, "succeeded": 0, "failed": 0, "skipped": 0}


def test_pending_image_is_exposed_as_direct_multimodal_input() -> None:
    attachment = {
        "parse_status": "pending",
        "file_type": "jpg",
        "mime_type": "image/jpeg",
        "metadata_json": {"ocr_policy": "multimodal_image_only"},
    }

    assert attachment_content_extraction_status(attachment) == "multimodal"
    assert attachment_extraction_strategy(attachment) == "multimodal_llm_direct"
    assert attachment_waits_for_text_extraction(attachment) is False


def test_explicit_skip_ocr_attachment_is_not_exposed_as_waiting() -> None:
    attachment = {
        "parse_status": "pending",
        "file_type": "bin",
        "mime_type": "application/octet-stream",
        "metadata_json": {"ocr_policy": "skip_ocr"},
    }

    assert attachment_content_extraction_status(attachment) == "skipped"
    assert attachment_waits_for_text_extraction(attachment) is False
