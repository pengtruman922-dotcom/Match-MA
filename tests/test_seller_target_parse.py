from backend.app.jobs.handlers import (
    _normalize_seller_listed_status,
    _normalize_seller_target_parse_changes,
    _validate_seller_target_parse_output,
)


def test_seller_target_parse_output_validation_requires_supported_fields() -> None:
    valid = _validate_seller_target_parse_output({"fields": {"current_net_profit_yuan": 25000000}})
    invalid = _validate_seller_target_parse_output({"fields": {"unsupported": "x"}})

    assert valid["valid"] is True
    assert valid["field_count"] == 1
    assert invalid["valid"] is False


def test_seller_target_parse_changes_normalize_enums_and_numbers() -> None:
    changes, notes = _normalize_seller_target_parse_changes(
        {
            "fields": {
                "target_name": "Hangzhou Qiyuan medical device project",
                "current_net_profit_yuan": "25000000",
                "pe_ratio": "12.8",
                "listed_status": "unlisted",
                "is_for_sale": "yes",
                "can_consolidate": "unknown",
                "transfer_flexibility_type": "flexible",
                "risk_summary": "",
                "unsupported_field": "ignored",
            }
        }
    )

    assert changes["target_name"] == "Hangzhou Qiyuan medical device project"
    assert changes["current_net_profit_yuan"] == 25000000
    assert str(changes["pe_ratio"]) == "12.8"
    assert changes["listed_status"] == "unlisted"
    assert changes["is_for_sale"] == "yes"
    assert changes["can_consolidate"] == "unknown"
    assert changes["transfer_flexibility_type"] == "flexible"
    assert "risk_summary" not in changes
    assert notes == ["ignored_unsupported_field:unsupported_field"]


def test_seller_listed_status_does_not_return_any() -> None:
    assert _normalize_seller_listed_status("any") == "unknown"


def test_seller_target_parse_supports_rollback_fields() -> None:
    from backend.app.api.routes.update_logs import ROLLBACK_FIELDS_BY_ENTITY
    from backend.app.jobs.handlers import SELLER_TARGET_PARSE_FIELDS

    assert SELLER_TARGET_PARSE_FIELDS <= ROLLBACK_FIELDS_BY_ENTITY["seller_target"]
