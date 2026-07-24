from backend.app.api.routes.extracted_actions import (
    _seller_target_changes_with_post_parse_status as _action_seller_target_changes_with_post_parse_status,
)
from backend.app.api.routes.seller_targets import _normalized_create_industry_pairs
from backend.app.services.extracted_action_apply import _lifecycle_status_from_changes
from backend.app.jobs.handlers import (
    _normalize_change_fields,
    _normalize_seller_listed_status,
    _normalize_seller_target_parse_changes,
    _seller_target_changes_with_post_parse_status,
    _validate_seller_target_parse_output,
    SELLER_TARGET_CHANGE_FIELDS,
    SELLER_TARGET_ENUM_FIELDS,
    SELLER_TARGET_FIELD_ALIASES,
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
                "target_subject_name": "Hangzhou Qiyuan Medical Device Co., Ltd.",
                "current_net_profit_yuan": "25000000",
                "pe_ratio": "12.8",
                "asking_price_date": "2025 Q1",
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
    assert changes["target_subject_name"] == "Hangzhou Qiyuan Medical Device Co., Ltd."
    assert changes["current_net_profit_yuan"] == 25000000
    assert str(changes["pe_ratio"]) == "12.8"
    assert changes["asking_price_date"] == "2025 Q1"
    assert changes["listed_status"] == "unlisted"
    assert changes["is_for_sale"] == "yes"
    assert changes["can_consolidate"] == "unknown"
    assert changes["transfer_flexibility_type"] == "flexible"
    assert "risk_summary" not in changes
    assert notes == ["ignored_unsupported_field:unsupported_field"]


def test_seller_listed_status_does_not_return_any() -> None:
    assert _normalize_seller_listed_status("any") == "unknown"


def test_seller_listed_status_accepts_llm_boolean_style_values() -> None:
    assert _normalize_seller_listed_status("no") == "unlisted"
    assert _normalize_seller_listed_status("not listed") == "unlisted"
    assert _normalize_seller_listed_status("private company") == "unlisted"
    assert _normalize_seller_listed_status("yes") == "listed"


def test_extracted_action_seller_fact_normalizes_listed_status_before_apply() -> None:
    changes, notes = _normalize_change_fields(
        {"listed_status": "no", "information_status": "bad_value"},
        allowed_fields=SELLER_TARGET_CHANGE_FIELDS,
        aliases=SELLER_TARGET_FIELD_ALIASES,
        enum_fields=SELLER_TARGET_ENUM_FIELDS,
    )

    assert changes["listed_status"] == "unlisted"
    assert "information_status" not in changes
    assert "listed_status:no->unlisted" in notes
    assert "information_status:bad_value->dropped_invalid_enum" in notes


def test_seller_target_parse_supports_rollback_fields() -> None:
    from backend.app.api.routes.update_logs import ROLLBACK_FIELDS_BY_ENTITY
    from backend.app.jobs.handlers import SELLER_TARGET_PARSE_FIELDS

    assert SELLER_TARGET_PARSE_FIELDS <= ROLLBACK_FIELDS_BY_ENTITY["seller_target"]


def test_extracted_action_keeps_normalized_industry_fields() -> None:
    changes, notes = _normalize_change_fields(
        {
            "industry_pairs_json": [{"l1": "医药与健康", "l2": "医疗器械"}],
        },
        allowed_fields=SELLER_TARGET_CHANGE_FIELDS,
        aliases=SELLER_TARGET_FIELD_ALIASES,
        enum_fields=SELLER_TARGET_ENUM_FIELDS,
    )

    assert changes == {
        "industry_pairs_json": [{"l1": "医药与健康", "l2": "医疗器械"}],
    }
    assert notes == []


def test_seller_target_parse_success_promotes_parsing_target_status() -> None:
    changes = _seller_target_changes_with_post_parse_status(
        {"information_status": "parsing", "recommendation_status": "not_recommendable"},
        {"business_summary": "parsed summary"},
    )

    assert changes["business_summary"] == "parsed summary"
    assert changes["information_status"] == "normal"
    assert changes["recommendation_status"] == "recommendable"


def test_extracted_action_apply_success_promotes_parsing_target_status() -> None:
    changes = _action_seller_target_changes_with_post_parse_status(
        {"information_status": "parsing", "recommendation_status": "not_recommendable"},
        {"business_summary": "parsed summary"},
    )

    assert changes["business_summary"] == "parsed summary"
    assert changes["information_status"] == "normal"
    assert changes["recommendation_status"] == "recommendable"


def test_post_parse_status_does_not_override_manual_recommendability() -> None:
    changes = _action_seller_target_changes_with_post_parse_status(
        {"information_status": "normal", "recommendation_status": "not_recommendable"},
        {"business_summary": "later update"},
    )

    assert changes == {"business_summary": "later update"}


def test_terminal_sale_statuses_close_the_target_lifecycle() -> None:
    """Explicit transaction facts synchronise lifecycle and “是否还卖”."""
    assert _lifecycle_status_from_changes({"lifecycle_status": "已售出"}) == "sold"
    assert _lifecycle_status_from_changes({"sale_status": "已停售"}) == "off_market"
    assert _lifecycle_status_from_changes({"is_for_sale": "no"}) == "off_market"
    assert _lifecycle_status_from_changes({"is_for_sale": "yes"}) is None


def test_blank_industry_is_allowed_when_creating_a_target() -> None:
    class _NoDbAccess:
        def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("blank industry must not query the taxonomy")

    assert _normalized_create_industry_pairs(
        _NoDbAccess(), {"industry_pairs_json": [], "industry_l1": None, "industry_l2": None}
    ) == []
