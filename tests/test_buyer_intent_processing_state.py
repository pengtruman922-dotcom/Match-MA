from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from backend.app.jobs.handlers import attachment_ocr
from backend.app.jobs.queue import JobClaim
from backend.app.services.buyer_intent_processing_state import (
    compute_buyer_intent_processing_state,
)
from backend.app.services.json_values import json_safe_value
from scripts.match_ma_api_tools import _buyer_recovery_succeeded

ROOT = Path(__file__).resolve().parents[1]
INTENT_ID = UUID("00000000-0000-0000-0000-000000000101")
UPDATE_ID = UUID("00000000-0000-0000-0000-000000000102")


def _intent(**overrides):
    return {
        "id": INTENT_ID,
        "preferred_listed_status": "any",
        "requires_control": "unknown",
        "requires_consolidation": "unknown",
        "needs_confirmation_json": [],
        "reviewed_at": None,
        **overrides,
    }


def _state(*, intent=None, update=None, attachments=None, parse_job=None, evidence=None):
    return compute_buyer_intent_processing_state(
        intent=intent or _intent(),
        business_update=update,
        attachments=attachments or [],
        parse_job=parse_job,
        evidence=evidence or {},
    )


def test_json_safe_value_recurses_through_nested_domain_values() -> None:
    value = {
        "jobs": [{"id": INTENT_ID, "amount": Decimal("12.50")}],
        "finished_at": datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        "ids": (UPDATE_ID,),
    }

    assert json_safe_value(value) == {
        "jobs": [{"id": str(INTENT_ID), "amount": 12.5}],
        "finished_at": "2026-07-30T12:00:00+00:00",
        "ids": [str(UPDATE_ID)],
    }


def test_default_buyer_intent_values_are_not_parse_success_evidence() -> None:
    state = _state()

    assert state["overall_status"] == "not_started"
    assert state["status_label"] == "未解析"


def test_failed_job_overrides_stale_attachment_parsing_storage_state() -> None:
    state = _state(
        update={
            "id": UPDATE_ID,
            "created_at": "2026-07-30T10:00:00+00:00",
            "processing_status": "processing",
            "latest_job_status": "failed",
            "latest_job_error_message": "Object of type UUID is not JSON serializable",
        },
        attachments=[{
            "parse_status": "parsing",
            "latest_job_status": "failed",
            "latest_job_error_message": "Object of type UUID is not JSON serializable",
            "latest_job_created_at": "2026-07-30T10:01:00+00:00",
        }],
    )

    assert state["overall_status"] == "failed"
    assert state["current_stage"] == "attachment_extraction"
    assert state["attachment_summary"]["failed"] == 1
    assert state["recoverable"] is True


def test_new_active_attachment_retry_wins_over_old_failure() -> None:
    state = _state(
        update={
            "id": UPDATE_ID,
            "created_at": "2026-07-30T10:00:00+00:00",
            "processing_status": "failed",
            "latest_job_status": "failed",
        },
        attachments=[{"parse_status": "parsing", "latest_job_status": "running"}],
    )

    assert state["overall_status"] == "processing"
    assert state["current_stage"] == "attachment_extraction"


def test_bulk_state_selects_latest_active_chain_not_newest_update_row() -> None:
    source = (
        ROOT / "backend/app/services/buyer_intent_processing_state.py"
    ).read_text(encoding="utf-8")

    assert "coalesce(latest_job.created_at, bu.created_at) desc" in source
    assert "order by bound.intent_id_text, bu.created_at desc" not in source


def test_partial_attachment_failure_can_finish_with_warning_after_ai_write() -> None:
    state = _state(
        intent=_intent(needs_confirmation_json=[{"field": "region_constraints_json"}]),
        update={
            "id": UPDATE_ID,
            "created_at": "2026-07-30T10:00:00+00:00",
            "processing_status": "applied",
            "latest_job_status": "succeeded",
        },
        attachments=[
            {"parse_status": "parsed", "latest_job_status": "succeeded"},
            {"parse_status": "failed", "latest_job_status": "failed"},
        ],
        parse_job={
            "id": UUID("00000000-0000-0000-0000-000000000103"),
            "status": "succeeded",
            "created_at": "2026-07-30T10:02:00+00:00",
            "payload_json": {"business_update_id": str(UPDATE_ID)},
            "metadata_json": {"processing_stage": "writing"},
        },
    )

    assert state["overall_status"] == "succeeded"
    assert state["attachment_warning_count"] == 1
    assert state["review_status"] == "needs_confirmation"
    assert state["needs_confirmation_count"] == 1


def test_current_parse_failure_wins_over_historical_business_update_write() -> None:
    state = _state(
        update={
            "id": UPDATE_ID,
            "created_at": "2026-07-30T10:00:00+00:00",
            "processing_status": "applied",
            "latest_job_status": "failed",
        },
        parse_job={
            "id": UUID("00000000-0000-0000-0000-000000000104"),
            "status": "failed",
            "created_at": "2026-07-30T10:02:00+00:00",
            "payload_json": {"business_update_id": str(UPDATE_ID)},
            "metadata_json": {"processing_stage": "semantic_parsing"},
        },
        evidence={"has_business_update_write": True},
    )

    assert state["overall_status"] == "failed"
    assert state["current_stage"] == "semantic_parsing"


def test_production_recovery_requires_all_ai_stages_to_succeed() -> None:
    latest = {
        "processing_state": {
            "overall_status": "succeeded",
            "ai_parse_status": "failed",
            "semantic_parse_status": "failed",
            "normalization_status": "not_started",
            "write_status": "not_started",
        },
        "attachment": {"content_extraction_status": "succeeded"},
        "business_update_batch": {"status": "applied"},
    }

    assert _buyer_recovery_succeeded(latest) is False
    latest["processing_state"].update(
        {
            "ai_parse_status": "succeeded",
            "semantic_parse_status": "succeeded",
            "normalization_status": "succeeded",
            "write_status": "succeeded",
        }
    )
    assert _buyer_recovery_succeeded(latest) is True


def test_frontend_list_uses_bulk_state_without_per_row_parse_status_requests() -> None:
    source = (ROOT / "frontend/src/features/buyers/IntentsList.tsx").read_text(encoding="utf-8")
    presentation = (ROOT / "frontend/src/features/buyers/presentation.tsx").read_text(encoding="utf-8")

    assert "buyerIntents.parseStatus(item.id)" not in source
    assert "hasStructuredIntentFields" not in source
    assert "hasStructuredIntentFields" not in presentation
    assert "item.processing_state" in presentation


def test_stuck_repair_is_dry_run_by_default_and_preserves_audit_rows() -> None:
    source = (ROOT / "backend/app/api/routes/background_jobs.py").read_text(encoding="utf-8")

    assert "class StuckProcessingRepairRequest" in source
    assert "apply: bool = False" in source
    assert "metadata_json = metadata_json || :metadata_patch" in source
    assert 'bindparam("metadata_patch", type_=JSONB)' in source
    assert "delete from attachment" not in source


def test_final_attachment_exception_closes_state_after_job_is_failed(monkeypatch) -> None:
    class Result:
        def __init__(self, row=None, first=None):
            self.row = row
            self.first_value = first

        def mappings(self):
            return self

        def one_or_none(self):
            return self.row

        def first(self):
            return self.first_value

    class Db:
        def __init__(self):
            self.results = [Result({"status": "failed"}), Result(first=None)]

        def execute(self, *_args, **_kwargs):
            return self.results.pop(0)

    calls: list[str] = []
    monkeypatch.setattr(
        attachment_ocr,
        "_update_attachment_parse_terminal_without_document",
        lambda *_args, **_kwargs: calls.append("attachment_failed"),
    )
    monkeypatch.setattr(
        attachment_ocr,
        "_mark_business_updates_blocked_by_attachment_ocr",
        lambda *_args, **_kwargs: calls.append("business_update_closed"),
    )
    monkeypatch.setattr(
        attachment_ocr,
        "_enqueue_linked_parse_jobs_after_ocr",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        attachment_ocr,
        "_enqueue_business_update_process_after_ocr",
        lambda *_args, **_kwargs: None,
    )
    job = JobClaim(
        id=UUID("00000000-0000-0000-0000-000000000104"),
        job_type="attachment_ocr_parse",
        queue_name="ocr",
        entity_type="attachment",
        entity_id=UUID("00000000-0000-0000-0000-000000000105"),
        correlation_id=UPDATE_ID,
        payload_json={"business_update_id": str(UPDATE_ID)},
        attempt_count=1,
        max_attempts=1,
    )

    attachment_ocr._finalize_attachment_job_failure(Db(), job, "trace insert failed")

    assert calls == ["attachment_failed", "business_update_closed"]
