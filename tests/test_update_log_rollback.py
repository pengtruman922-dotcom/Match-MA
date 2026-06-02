from uuid import UUID

from backend.app.api.routes.update_logs import (
    _rollbackability,
    _values_match_for_rollback,
)


LOG_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_rollbackability_accepts_supported_fields() -> None:
    result = _rollbackability(
        {
            "id": LOG_ID,
            "entity_type": "seller_target",
            "field_path": "business_summary",
            "can_rollback": True,
            "rollback_at": None,
            "source_type": "extracted_action",
        }
    )

    assert result["ok"] is True


def test_rollbackability_rejects_unsafe_or_already_rolled_back_logs() -> None:
    unsupported = _rollbackability(
        {
            "id": LOG_ID,
            "entity_type": "seller_target",
            "field_path": "deleted_at",
            "can_rollback": True,
            "rollback_at": None,
            "source_type": "direct_api",
        }
    )
    already_done = _rollbackability(
        {
            "id": LOG_ID,
            "entity_type": "buyer_intent",
            "field_path": "intent_summary",
            "can_rollback": True,
            "rollback_at": "2026-06-02",
            "source_type": "extracted_action",
        }
    )
    rollback_log = _rollbackability(
        {
            "id": LOG_ID,
            "entity_type": "buyer_intent",
            "field_path": "intent_summary",
            "can_rollback": False,
            "rollback_at": None,
            "source_type": "rollback",
        }
    )

    assert unsupported["ok"] is False
    assert "field_path" in unsupported["reason"]
    assert already_done["ok"] is False
    assert rollback_log["ok"] is False


def test_rollback_value_match_is_json_safe() -> None:
    assert _values_match_for_rollback(UUID("00000000-0000-0000-0000-000000000002"), "00000000-0000-0000-0000-000000000002")
    assert _values_match_for_rollback({"a": UUID("00000000-0000-0000-0000-000000000003")}, {"a": "00000000-0000-0000-0000-000000000003"})
    assert not _values_match_for_rollback("new", "old")
