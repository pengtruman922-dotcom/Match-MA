from uuid import UUID

import pytest
from fastapi import HTTPException

from backend.app.api.authn import AuthContext
from backend.app.api.routes.buyer_intents import (
    BuyerIntentCreate,
    _ensure_buyer_party_available_for_intent,
    _resolve_intent_owner,
)


class _ScalarResult:
    def __init__(self, value: int | None) -> None:
        self.value = value

    def scalar(self) -> int | None:
        return self.value


class _RecordingSession:
    def __init__(self, value: int | None) -> None:
        self.value = value
        self.sql = ""

    def execute(self, statement: object, params: dict[str, object]) -> _ScalarResult:
        self.sql = str(statement)
        return _ScalarResult(self.value)


def test_cross_owner_buyer_reuse_keeps_new_intent_with_creating_consultant() -> None:
    current_user = AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000123"),
        role="consultant",
        name="创建人",
    )
    payload = BuyerIntentCreate(
        intent_name="跨负责人买家新需求",
        buyer_party_id=UUID("10000000-0000-0000-0000-000000000001"),
    )

    assert _resolve_intent_owner(payload, current_user) == current_user.user_id


def test_admin_can_explicitly_assign_new_intent_owner() -> None:
    current_user = AuthContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        role="admin",
        name="管理员",
    )
    assigned_owner = UUID("00000000-0000-0000-0000-000000000456")
    payload = BuyerIntentCreate(intent_name="管理员代建需求", owner_user_id=assigned_owner)

    assert _resolve_intent_owner(payload, current_user) == assigned_owner


def test_existing_buyer_can_be_linked_without_owner_scope_filter() -> None:
    db = _RecordingSession(1)

    _ensure_buyer_party_available_for_intent(
        db,
        UUID("10000000-0000-0000-0000-000000000001"),
    )

    assert "deleted_at is null" in db.sql
    assert "owner_user_id" not in db.sql
    assert "scope_user_id" not in db.sql


def test_deleted_or_missing_buyer_cannot_be_linked() -> None:
    db = _RecordingSession(None)

    with pytest.raises(HTTPException) as exc_info:
        _ensure_buyer_party_available_for_intent(
            db,
            UUID("10000000-0000-0000-0000-000000000001"),
        )

    assert exc_info.value.status_code == 404
