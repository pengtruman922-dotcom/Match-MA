from uuid import UUID

from backend.app.api.routes.business_updates import (
    _enrich_review_action,
    _entity_ref,
    _review_action_group_key,
    _review_page_overview,
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
        [{"status": "failed"}, {"status": "running"}],
        [{"status": "failed", "error_code": "schema_failed"}],
    )

    assert overview["pending_review_count"] == 1
    assert overview["auto_applied_count"] == 1
    assert overview["failed_job_count"] == 1
    assert overview["running_job_count"] == 1
    assert overview["needs_review"] is True


def test_entity_ref_only_uses_debug_for_supported_entities() -> None:
    assert _entity_ref("seller_target", SELLER_TARGET_ID)["debug_ref"] is None
    session_ref = _entity_ref("recommendation_session", SELLER_TARGET_ID)
    assert session_ref["route"] == f"/recommendations/sessions/{SELLER_TARGET_ID}"
    assert session_ref["debug_ref"]["route"].endswith(f"/debug/entities/recommendation_session/{SELLER_TARGET_ID}")
