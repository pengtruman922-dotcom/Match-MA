from uuid import UUID

from backend.app.api.routes.recommendations import (
    _build_recommendation_report_status,
    _build_recommendation_selected_status,
    _recommendation_page_overview,
    _recommendation_session_display,
    _recommendation_session_is_processing,
)

SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
BUYER_INTENT_ID = UUID("00000000-0000-0000-0000-000000000002")
SELLER_TARGET_ID = UUID("00000000-0000-0000-0000-000000000003")


def test_recommendation_session_display_for_buyer_to_target() -> None:
    display = _recommendation_session_display(
        {
            "id": SESSION_ID,
            "mode": "buyer_to_target",
            "buyer_intent_id": BUYER_INTENT_ID,
            "buyer_intent_name": "Healthcare consolidation need",
            "buyer_name": "Zhejiang SOE",
            "seller_target_id": None,
        }
    )

    assert display["title"] == "Healthcare consolidation need"
    assert display["anchor"] == {"entity_type": "buyer_intent", "entity_id": str(BUYER_INTENT_ID)}
    assert display["primary_action"] == "recommend_targets"


def test_recommendation_session_display_for_target_to_buyer() -> None:
    display = _recommendation_session_display(
        {
            "id": SESSION_ID,
            "mode": "target_to_buyer",
            "buyer_intent_id": None,
            "seller_target_id": SELLER_TARGET_ID,
            "seller_target_name": "Hangzhou Device Target",
        }
    )

    assert display["title"] == "Hangzhou Device Target"
    assert display["anchor"] == {"entity_type": "seller_target", "entity_id": str(SELLER_TARGET_ID)}
    assert display["primary_action"] == "recommend_buyers"


def test_report_status_prefers_running_job() -> None:
    status = _build_recommendation_report_status(
        reports=[{"id": SESSION_ID, "status": "generating", "created_at": "2026-06-02"}],
        jobs=[{"id": SELLER_TARGET_ID, "job_type": "recommendation_report_generate", "status": "running"}],
    )

    assert status["requested"] is True
    assert status["status"] == "generating"
    assert status["generating_count"] == 1
    assert status["latest_job"]["status"] == "running"


def test_report_status_without_reports_is_not_requested() -> None:
    status = _build_recommendation_report_status(reports=[], jobs=[])

    assert status["requested"] is False
    assert status["status"] == "not_requested"
    assert status["latest_report"] is None


def test_selected_status_counts_active_and_canceled() -> None:
    status = _build_recommendation_selected_status(
        [
            {"id": BUYER_INTENT_ID, "selected_at": "2026-06-02", "canceled_at": None},
            {"id": SELLER_TARGET_ID, "selected_at": "2026-06-01", "canceled_at": "2026-06-02"},
        ]
    )

    assert status["active_count"] == 1
    assert status["canceled_count"] == 1
    assert status["latest_selected_at"] == "2026-06-02"


def test_processing_and_page_overview_counts() -> None:
    processing_summary = {
        "rerank_status": {"status": "running"},
        "report_status": {"status": "not_requested", "generated_count": 0},
        "selected_status": {"active_count": 2},
    }
    failed_summary = {
        "rerank_status": {"status": "failed"},
        "report_status": {"status": "generated", "generated_count": 1},
        "selected_status": {"active_count": 1},
    }

    overview = _recommendation_page_overview([processing_summary, failed_summary], [processing_summary])

    assert _recommendation_session_is_processing(processing_summary) is True
    assert overview["recent_session_count"] == 2
    assert overview["running_session_count"] == 1
    assert overview["failed_session_count"] == 1
    assert overview["generated_report_count"] == 1
    assert overview["active_selected_item_count"] == 3
