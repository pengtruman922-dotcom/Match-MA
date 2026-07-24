from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.api.routes.recommendations import (
    RecommendationCandidateRequest,
    _build_temporary_anchor,
    _ensure_session_is_not_temporary_filter,
    _is_temporary_filter_session,
    _temporary_anchor_from_session,
    generate_recommendation_candidates,
)
from backend.app.api.authn import AuthContext
from backend.app.services.recommendation_flow import _recommendation_session_display


def test_temporary_request_needs_no_persisted_anchor() -> None:
    request = RecommendationCandidateRequest(
        mode="buyer_to_target",
        temporary_input="寻找华北殡葬服务企业，净利润 2000 万以上",
    )

    assert request.buyer_intent_id is None
    assert request.temporary_input


def test_temporary_request_cannot_mix_with_real_anchor() -> None:
    with pytest.raises(ValidationError):
        RecommendationCandidateRequest(
            mode="buyer_to_target",
            buyer_intent_id=UUID("00000000-0000-0000-0000-000000000002"),
            temporary_input="寻找华北殡葬服务企业",
        )


def test_temporary_anchor_is_explicitly_unbound() -> None:
    buyer_anchor = _build_temporary_anchor("buyer_to_target", "寻找消费品牌")
    target_anchor = _build_temporary_anchor("target_to_buyer", "消费品牌拟出售控股权")

    assert buyer_anchor["id"] is None
    assert buyer_anchor["intent_name"] == "临时买家需求"
    assert buyer_anchor["preference_summary"] == "寻找消费品牌"
    assert target_anchor["id"] is None
    assert target_anchor["target_name"] == "临时标的画像"
    assert target_anchor["business_summary"] == "消费品牌拟出售控股权"


def test_temporary_session_restores_its_saved_anchor_and_is_read_only() -> None:
    session = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "mode": "buyer_to_target",
        "metadata_json": {"temporary_filter": True},
        "initial_condition_snapshot_json": {"id": None, "intent_name": "临时买家需求"},
        "anonymous_input_snapshot": "寻找华北消费企业",
    }

    assert _is_temporary_filter_session(session) is True
    assert _temporary_anchor_from_session(session) == session["initial_condition_snapshot_json"]
    with pytest.raises(HTTPException, match="read-only"):
        _ensure_session_is_not_temporary_filter(session)


def test_temporary_session_is_clearly_labeled_in_history() -> None:
    display = _recommendation_session_display(
        {
            "id": UUID("00000000-0000-0000-0000-000000000001"),
            "mode": "target_to_buyer",
            "metadata_json": {"temporary_filter": True},
        }
    )

    assert display["title"] == "临时条件筛选"
    assert display["anchor"] == {"entity_type": None, "entity_id": None}
    assert display["primary_action"] == "temporary_filter"


def test_temporary_filter_creates_an_unbound_session_without_entity_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The candidate flow must never manufacture a buyer intent or target."""
    from backend.app.api.routes import recommendations as route

    captured: dict[str, object] = {}

    class _Db:
        committed = False

        def commit(self) -> None:
            self.committed = True

    db = _Db()
    session_id = uuid4()
    monkeypatch.setattr(route, "parse_recommendation_message", lambda *_args, **_kwargs: {
        "condition_ops": [],
        "semantic_preferences": ["殡葬服务"],
        "display_ops": [],
        "question": None,
        "parser_status": "fallback",
    })
    monkeypatch.setattr(route, "_candidate_targets_for_intent", lambda *_args, **_kwargs: {
        "candidates": [], "funnel": {"scan_count": 0, "eligible_count": 0, "deep_eval_count": 0}, "scenarios": [],
    })
    monkeypatch.setattr(route, "_enrich_candidates_for_frontend", lambda candidates: candidates)
    monkeypatch.setattr(route, "_create_recommendation_session", lambda *_args, **kwargs: captured.update(kwargs) or session_id)
    monkeypatch.setattr(route, "_insert_recommendation_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(route, "persist_session_overrides", lambda *_args, **_kwargs: None)

    result = generate_recommendation_candidates(
        RecommendationCandidateRequest(mode="buyer_to_target", temporary_input="寻找殡葬服务企业"),
        AuthContext(user_id=uuid4(), role="admin", name="admin"),
        db,  # type: ignore[arg-type]
    )

    assert result["session_id"] == session_id
    assert captured["buyer_intent_id"] is None
    assert captured["buyer_party_id"] is None
    assert captured["seller_target_id"] is None
    assert captured["is_temporary_filter"] is True
    assert captured["initial_snapshot"] == _build_temporary_anchor("buyer_to_target", "寻找殡葬服务企业")
    assert db.committed is True
