from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.app.api.routes.recommendations import (
    _ensure_session_is_not_temporary_filter,
    _is_temporary_filter_session,
)
from backend.app.services.recommendation_flow import _recommendation_session_display


def test_temporary_session_restores_its_saved_anchor_and_is_read_only() -> None:
    session = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "mode": "buyer_to_target",
        "metadata_json": {"temporary_filter": True},
        "initial_condition_snapshot_json": {"id": None, "intent_name": "临时买家需求"},
        "anonymous_input_snapshot": "寻找华北消费企业",
    }

    assert _is_temporary_filter_session(session) is True
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


