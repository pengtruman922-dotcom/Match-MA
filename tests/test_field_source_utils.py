from uuid import UUID

from backend.app.api.routes.extracted_actions import _action_source_context
from backend.app.api.routes.field_sources import _debug_ref
from backend.app.api.routes.update_logs import _mark_field_sources_ignored_after_rollback
from backend.app.api.routes.utils import diff_payload, write_action_logs_for_diff, write_field_value_sources_for_diff


ACTION_ID = UUID("00000000-0000-0000-0000-000000000001")
BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-000000000002")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000003")
ENTITY_ID = UUID("00000000-0000-0000-0000-000000000004")


class FakeDb:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return None


def test_action_source_context_prefers_action_evidence_id() -> None:
    context = _action_source_context(
        {
            "id": ACTION_ID,
            "business_update_id": BUSINESS_UPDATE_ID,
            "action_type": "seller_fact_update",
            "evidence_id": EVIDENCE_ID,
            "confidence": 0.86,
            "raw_evidence_text": "evidence",
            "metadata_json": {"source_label": "LLM extracted evidence"},
        },
        default_source_label="Business update extracted action",
    )

    assert context["source_type"] == "extracted_action"
    assert context["source_id"] == ACTION_ID
    assert context["business_update_id"] == BUSINESS_UPDATE_ID
    assert context["extracted_action_id"] == ACTION_ID
    assert context["evidence_id"] == EVIDENCE_ID
    assert context["source_label"] == "LLM extracted evidence"


def test_write_action_logs_for_diff_carries_source_and_evidence_ids() -> None:
    db = FakeDb()
    diff = diff_payload({"business_summary": "old"}, {"business_summary": "new"})

    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=ENTITY_ID,
        diff=diff,
        source_type="extracted_action",
        source_id=ACTION_ID,
        evidence_id=EVIDENCE_ID,
        business_update_id=BUSINESS_UPDATE_ID,
        extracted_action_id=ACTION_ID,
        metadata_json={"source": "unit_test"},
    )

    params = db.calls[0][1]
    assert params["source_type"] == "extracted_action"
    assert params["source_id"] == ACTION_ID
    assert params["evidence_id"] == EVIDENCE_ID
    assert params["metadata_json"]["source"] == "unit_test"


def test_write_field_value_sources_for_diff_creates_auto_accepted_source() -> None:
    db = FakeDb()
    diff = diff_payload({"business_summary": "old"}, {"business_summary": "new"})

    write_field_value_sources_for_diff(
        db,
        entity_type="seller_target",
        entity_id=ENTITY_ID,
        changes={"business_summary": "new"},
        diff=diff,
        source_type="extracted_action",
        source_id=ACTION_ID,
        evidence_id=EVIDENCE_ID,
        source_label="Business update extracted action",
        confidence=0.9,
        review_status="auto_accepted",
        source_context={"source_type": "extracted_action", "source_id": ACTION_ID},
    )

    params = db.calls[0][1]
    assert params["field_path"] == "business_summary"
    assert params["value_snapshot_json"]["value"] == "new"
    assert params["value_snapshot_json"]["source_context"]["source_id"] == str(ACTION_ID)
    assert params["source_type"] == "extracted_action"
    assert params["source_id"] == ACTION_ID
    assert params["evidence_id"] == EVIDENCE_ID
    assert params["review_status"] == "auto_accepted"


def test_rollback_marks_matching_field_sources_ignored() -> None:
    db = FakeDb()

    _mark_field_sources_ignored_after_rollback(
        db,
        {
            "entity_type": "seller_target",
            "entity_id": ENTITY_ID,
            "field_path": "business_summary",
            "source_type": "extracted_action",
            "source_id": ACTION_ID,
        },
    )

    sql, params = db.calls[0]
    assert "update field_value_source" in sql
    assert "review_status = 'ignored'" in sql
    assert params["source_type"] == "extracted_action"
    assert params["source_id"] == ACTION_ID


def test_extracted_action_field_source_debug_ref_uses_api_route() -> None:
    ref = _debug_ref("extracted_action", ACTION_ID)

    assert ref["entity_type"] == "extracted_action"
    assert ref["route"] == f"/api/v1/extracted-actions/{ACTION_ID}"
