import json
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.authn import AuthContext
from backend.app.api.routes.recommendations import (
    RecommendationSelectedItemCreate,
    _build_recommendation_report_status,
    _build_recommendation_selected_status,
    _ensure_selected_item_allowed_from_session_candidates,
    _ensure_selected_item_matches_session,
    _filter_recommendation_session_summaries,
    _list_recommendation_session_overview_rows,
    _recommendation_page_overview,
    _recommendation_session_display,
    _recommendation_session_is_processing,
    _recommendation_session_polling_hint,
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


def test_recommendation_session_filter_and_polling_hint() -> None:
    running_summary = {
        "rerank_status": {"status": "running", "job_id": str(SELLER_TARGET_ID), "queue_name": "llm"},
        "report_status": {"status": "not_requested", "latest_job": None},
        "selected_status": {"active_count": 0},
    }
    generated_summary = {
        "rerank_status": {"status": "succeeded", "job_id": None},
        "report_status": {"status": "generated", "latest_job": None},
        "selected_status": {"active_count": 1},
    }
    failed_summary = {
        "rerank_status": {"status": "failed", "job_id": None},
        "report_status": {"status": "not_requested", "latest_job": None},
        "selected_status": {"active_count": 0},
    }

    summaries = [running_summary, generated_summary, failed_summary]

    assert _filter_recommendation_session_summaries(summaries, "running") == [running_summary]
    assert _filter_recommendation_session_summaries(summaries, "generated") == [generated_summary]
    assert _filter_recommendation_session_summaries(summaries, "selected") == [generated_summary]
    assert _filter_recommendation_session_summaries(summaries, "failed") == [failed_summary]

    hint = _recommendation_session_polling_hint(running_summary, session_id=SESSION_ID)

    assert hint["enabled"] is True
    assert hint["endpoint"] == f"/api/v1/recommendations/sessions/{SESSION_ID}/page-state"
    assert hint["watched_jobs"][0]["job_type"] == "recommendation_deep_eval"


def test_selected_item_must_match_session_anchor() -> None:
    payload = RecommendationSelectedItemCreate(
        mode="buyer_to_target",
        buyer_intent_id=uuid4(),
        seller_target_id=SELLER_TARGET_ID,
    )

    with pytest.raises(HTTPException) as exc_info:
        _ensure_selected_item_matches_session(
            {
                "mode": "buyer_to_target",
                "buyer_intent_id": BUYER_INTENT_ID,
                "seller_target_id": None,
            },
            payload,
        )

    assert exc_info.value.status_code == 400


class _MessageResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_MessageResult":
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _MessageDb:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def execute(self, *_args, **_kwargs) -> _MessageResult:
        return _MessageResult(self._rows)


class _OverviewDb:
    def __init__(self) -> None:
        self.statement = ""
        self.params: dict = {}

    def execute(self, statement, params) -> _MessageResult:
        self.statement = str(statement)
        self.params = params
        return _MessageResult([])


def test_recommendation_history_search_is_scoped_and_mode_specific() -> None:
    current_user = AuthContext(user_id=uuid4(), role="consultant", name="consultant")
    db = _OverviewDb()

    rows = _list_recommendation_session_overview_rows(
        db,
        current_user=current_user,
        mode=None,
        limit=20,
        offset=0,
        q="  医疗  ",
    )

    assert rows == []
    assert "rs.created_by = :scope_user_id" in db.statement
    assert "rs.mode = 'buyer_to_target'" in db.statement
    assert "coalesce(bi.intent_name, '') ilike :q" in db.statement
    assert "rs.mode = 'target_to_buyer'" in db.statement
    assert "coalesce(st.target_name, '') ilike :q" in db.statement
    assert "left join app_user creator on creator.id = rs.created_by" in db.statement
    assert "creator.username" in db.statement
    assert db.params["scope_user_id"] == current_user.user_id
    assert db.params["q"] == "%医疗%"


def test_owner_scoped_selected_item_must_come_from_session_candidates() -> None:
    current_user = AuthContext(user_id=uuid4(), role="consultant", name="consultant")
    db = _MessageDb(
        [
            {
                "id": uuid4(),
                "content_type": "json",
                "content": json.dumps(
                    {
                        "message_type": "initial_candidates",
                        "candidates": [
                            {
                                "seller_target_id": str(SELLER_TARGET_ID),
                                "buyer_intent_id": str(BUYER_INTENT_ID),
                            }
                        ],
                    }
                ),
                "metadata_json": {"message_type": "initial_candidates"},
                "created_at": "2026-07-09T00:00:00",
            }
        ]
    )

    _ensure_selected_item_allowed_from_session_candidates(
        db,
        current_user,
        SESSION_ID,
        RecommendationSelectedItemCreate(
            mode="buyer_to_target",
            buyer_intent_id=BUYER_INTENT_ID,
            seller_target_id=SELLER_TARGET_ID,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        _ensure_selected_item_allowed_from_session_candidates(
            db,
            current_user,
            SESSION_ID,
            RecommendationSelectedItemCreate(
                mode="buyer_to_target",
                buyer_intent_id=BUYER_INTENT_ID,
                seller_target_id=uuid4(),
            ),
        )

    assert exc_info.value.status_code == 403


def test_owner_scoped_selected_item_rejects_other_users_candidate() -> None:
    current_user = AuthContext(user_id=uuid4(), role="consultant", name="consultant")
    messages = [
        {
            "id": uuid4(),
            "content_type": "json",
            "content": json.dumps(
                {
                    "message_type": "initial_candidates",
                    "candidates": [
                        {
                            "seller_target_id": str(SELLER_TARGET_ID),
                            "buyer_intent_id": str(BUYER_INTENT_ID),
                        }
                    ],
                }
            ),
            "metadata_json": {"message_type": "initial_candidates"},
            "created_at": "2026-08-03T00:00:00",
        }
    ]

    class _OwnerDb:
        def execute(self, statement, *_args, **_kwargs):
            if "from recommendation_message" in str(statement):
                return _MessageResult(messages)
            return _MessageResult([])

    with pytest.raises(HTTPException) as exc_info:
        _ensure_selected_item_allowed_from_session_candidates(
            _OwnerDb(),
            current_user,
            SESSION_ID,
            RecommendationSelectedItemCreate(
                mode="buyer_to_target",
                buyer_intent_id=BUYER_INTENT_ID,
                seller_target_id=SELLER_TARGET_ID,
            ),
        )

    assert exc_info.value.status_code == 403


def test_create_selected_item_only_writes_collection(monkeypatch) -> None:
    from backend.app.api.routes import recommendations as route

    selected_item_id = uuid4()
    current_user = AuthContext(user_id=uuid4(), role="consultant", name="consultant")
    row = {
        "id": selected_item_id,
        "session_id": SESSION_ID,
        "mode": "buyer_to_target",
        "seller_target_id": SELLER_TARGET_ID,
        "buyer_intent_id": BUYER_INTENT_ID,
        "buyer_party_id": None,
        "selected_by": current_user.user_id,
        "metadata_json": {},
    }

    class _InsertResult:
        def mappings(self):
            return self

        def one(self):
            return row

    class _Db:
        statements: list[str] = []
        committed = False

        def execute(self, statement, *_args, **_kwargs):
            self.statements.append(str(statement))
            return _InsertResult()

        def commit(self):
            self.committed = True

    db = _Db()
    monkeypatch.setattr(route, "ensure_recommendation_session_visible", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        route,
        "_get_recommendation_session_or_404",
        lambda *_args, **_kwargs: {"id": SESSION_ID, "mode": "buyer_to_target", "buyer_intent_id": BUYER_INTENT_ID, "metadata_json": {}},
    )
    monkeypatch.setattr(route, "_ensure_selected_item_allowed_from_session_candidates", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_get_active_selected_item_for_pair", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "_refresh_session_selected_count", lambda *_args, **_kwargs: None)

    created = route.create_selected_item(
        SESSION_ID,
        RecommendationSelectedItemCreate(
            mode="buyer_to_target",
            buyer_intent_id=BUYER_INTENT_ID,
            seller_target_id=SELLER_TARGET_ID,
        ),
        current_user,
        db,
    )

    assert created["id"] == selected_item_id
    assert db.committed is True
    assert len(db.statements) == 1
    assert "insert into recommendation_selected_item" in db.statements[0]
    assert "buyer_seller_relation" not in db.statements[0]
    assert "relation_event" not in db.statements[0]
