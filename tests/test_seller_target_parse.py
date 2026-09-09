from backend.app.api.routes.extracted_actions import (
    _seller_target_changes_with_parse_completion as _action_seller_target_changes_with_parse_completion,
)
from backend.app.services.extracted_action_apply import _lifecycle_status_from_changes
from backend.app.jobs.handlers import (
    _normalize_change_fields,
    _normalize_seller_listed_status,
    _normalize_seller_target_parse_changes,
    _seller_target_changes_with_parse_completion,
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
                "management_retention_possible": "likely",
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
    assert changes["management_retention_possible"] == "likely"
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


def test_extracted_action_keeps_business_tags_and_drops_retired_industry_keys() -> None:
    """行业字典 0908 下线：业务标签原样进白名单，旧版 prompt 吐的行业键被滤掉。"""
    changes, notes = _normalize_change_fields(
        {
            "business_tags_json": ["医疗器械", "体外诊断"],
            "industry_pairs_json": [{"l1": "医药与健康", "l2": "医疗器械"}],
            "industry_l1": "医药与健康",
        },
        allowed_fields=SELLER_TARGET_CHANGE_FIELDS,
        aliases=SELLER_TARGET_FIELD_ALIASES,
        enum_fields=SELLER_TARGET_ENUM_FIELDS,
    )

    assert changes == {"business_tags_json": ["医疗器械", "体外诊断"]}
    assert "industry_pairs_json" not in changes
    assert "industry_l1" not in changes
    assert notes == []


def test_the_industry_alias_now_feeds_business_tags() -> None:
    """模型吐 `industry: "汽车零部件"` 时，以前映射到 002 就删掉的 industry_secondary
    列、被静默丢弃；0908 起映射到业务标签，单个字符串当一个标签。"""
    assert SELLER_TARGET_FIELD_ALIASES["industry"] == "business_tags_json"


def test_seller_target_parse_normalizes_business_tags_shape() -> None:
    """自由标签只做形状归一：去空白、去重、单字符串也认；归空了整列摘掉并留 note。"""
    changes, notes = _normalize_seller_target_parse_changes(
        {"fields": {"business_tags_json": [" 汽车零部件 ", "汽车零部件", "", "商用车车架"]}}
    )
    assert changes["business_tags_json"] == ["汽车零部件", "商用车车架"]
    assert notes == []

    changes, notes = _normalize_seller_target_parse_changes({"fields": {"business_tags_json": "PCB"}})
    assert changes["business_tags_json"] == ["PCB"]

    changes, notes = _normalize_seller_target_parse_changes({"fields": {"business_tags_json": ["", None]}})
    assert "business_tags_json" not in changes
    assert "dropped_business_tags_json:no_usable_tags" in notes


def test_seller_target_parse_ignores_retired_industry_fields() -> None:
    """旧版 prompt（v0.11.0）还会吐 industry_l1 / industry_l2；不再转换，如实记成不支持。"""
    changes, notes = _normalize_seller_target_parse_changes(
        {"fields": {"industry_l1": "制造与工业", "industry_l2": "汽车零部件", "business_summary": "做车架的"}}
    )
    assert changes == {"business_summary": "做车架的"}
    assert "ignored_unsupported_field:industry_l1" in notes
    assert "ignored_unsupported_field:industry_l2" in notes


def test_seller_target_parse_keeps_derived_state_out_of_fact_diff() -> None:
    changes = _seller_target_changes_with_parse_completion(
        {"information_status": "parsing"},
        {"business_summary": "parsed summary"},
    )

    assert changes == {"business_summary": "parsed summary"}


def test_extracted_action_apply_keeps_derived_state_out_of_fact_diff() -> None:
    changes = _action_seller_target_changes_with_parse_completion(
        {"information_status": "parsing"},
        {"business_summary": "parsed summary"},
    )

    assert changes == {"business_summary": "parsed summary"}


def test_parse_completion_touches_no_other_status() -> None:
    """写入事实只报告解析自身的进度，不再顺带开关任何推荐闸门。"""
    changes = _action_seller_target_changes_with_parse_completion(
        {"information_status": "normal", "lifecycle_status": "active"},
        {"business_summary": "later update"},
    )

    assert changes == {"business_summary": "later update"}


def test_terminal_sale_statuses_close_the_target_lifecycle() -> None:
    """Explicit transaction facts synchronise lifecycle and “是否还卖”."""
    assert _lifecycle_status_from_changes({"lifecycle_status": "已售出"}) == "sold"
    assert _lifecycle_status_from_changes({"sale_status": "已停售"}) == "off_market"
    assert _lifecycle_status_from_changes({"is_for_sale": "no"}) == "off_market"
    assert _lifecycle_status_from_changes({"is_for_sale": "yes"}) is None
