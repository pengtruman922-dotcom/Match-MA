from decimal import Decimal
from uuid import UUID

from backend.app.api.routes.update_logs import (
    _batch_key_for_log,
    _batch_category,
    _batch_record,
    _batch_rollback_block_reason,
    _latest_effective_batch,
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


def test_research_listing_market_and_internal_period_are_rollbackable() -> None:
    for field_path in ("listing_market_region", "financial_period_end_date"):
        result = _rollbackability(
            {
                "id": LOG_ID,
                "entity_type": "seller_target",
                "field_path": field_path,
                "can_rollback": True,
                "rollback_at": None,
                "source_type": "research_proposal",
            }
        )
        assert result["ok"] is True


def test_research_logs_are_grouped_by_original_research_job() -> None:
    key = _batch_key_for_log(
        {
            "id": LOG_ID,
            "source_type": "research_proposal",
            "source_id": UUID("00000000-0000-0000-0000-000000000002"),
            "research_job_id": UUID("00000000-0000-0000-0000-000000000003"),
        },
        {},
    )
    assert key == "research-job-00000000-0000-0000-0000-000000000003"


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


def test_rollback_value_match_treats_database_decimals_as_json_numbers() -> None:
    assert _values_match_for_rollback(Decimal("550000000.00"), 550000000)
    assert _values_match_for_rollback(Decimal("12.0000"), 12.0)
    assert _values_match_for_rollback({"ratio": Decimal("0.1200")}, {"ratio": 0.12})
    assert not _values_match_for_rollback(Decimal("12.0001"), 12)
    assert _values_match_for_rollback(Decimal("12.0000"), "12.0000")
    assert _values_match_for_rollback({"amount": Decimal("550000000.00")}, {"amount": "550000000.00"})
    assert _values_match_for_rollback("12.0000", 12)
    assert _values_match_for_rollback(Decimal("5.5E+8"), "5.5E+8")
    assert not _values_match_for_rollback("12万元", 12)
    assert not _values_match_for_rollback("普通文本", 0)
    assert not _values_match_for_rollback(True, 1)


def test_research_batch_changes_include_field_level_evidence() -> None:
    log = _batch_log(
        log_id="00000000-0000-0000-0000-000000000209",
        applied_at="2026-07-12T12:00:00+00:00",
        source_type="research_proposal",
    )
    log.update(
        {
            "source_id": UUID("00000000-0000-0000-0000-000000000210"),
            "research_job_id": UUID("00000000-0000-0000-0000-000000000211"),
            "research_source_type": "public_web",
            "research_source_url": "https://example.com/report",
            "research_source_title": "2025 年年度报告",
            "research_source_excerpt": "营业收入为 5.5 亿元。",
            "research_period_label": "2025年度",
            "research_as_of_date": "2025-12-31",
        }
    )

    batch = _batch("research-job-test", log)
    evidence = batch["changes"][0]["research_evidence"]

    assert evidence["job_id"] == "00000000-0000-0000-0000-000000000211"
    assert evidence["source_url"] == "https://example.com/report"
    assert evidence["source_excerpt"] == "营业收入为 5.5 亿元。"


def _batch_log(*, log_id: str, applied_at: str, source_type: str = "direct_api", rollback_at: str | None = None) -> dict:
    return {
        "id": UUID(log_id),
        "entity_type": "seller_target",
        "entity_id": UUID("00000000-0000-0000-0000-000000000101"),
        "field_path": "business_summary",
        "old_value_json": "old",
        "new_value_json": "new",
        "source_type": source_type,
        "source_id": None,
        "business_update_id": None,
        "extracted_action_id": None,
        "applied_by": UUID("00000000-0000-0000-0000-000000000102"),
        "applied_by_name": "测试顾问",
        "applied_at": applied_at,
        "can_rollback": source_type != "rollback",
        "rollback_at": rollback_at,
        "edited_before_apply": False,
        "metadata_json": {},
    }


def _batch(batch_key: str, log: dict) -> dict:
    return _batch_record(
        batch_key=batch_key,
        entity_type="seller_target",
        entity_id=log["entity_id"],
        source_type=log["source_type"],
        source_id=None,
        input_type="text",
        raw_input="更新材料",
        attachments=[],
        operator_user_id=log["applied_by"],
        operator_name=log["applied_by_name"],
        submitted_at=log["applied_at"],
        status_value="applied",
        logs=[log],
    )


def test_latest_effective_batch_is_the_only_rollback_candidate() -> None:
    older = _batch(
        "manual-older",
        _batch_log(
            log_id="00000000-0000-0000-0000-000000000201",
            applied_at="2026-07-12T10:00:00+00:00",
        ),
    )
    latest = _batch(
        "manual-latest",
        _batch_log(
            log_id="00000000-0000-0000-0000-000000000202",
            applied_at="2026-07-12T11:00:00+00:00",
        ),
    )

    selected = _latest_effective_batch([older, latest])

    assert selected is latest
    assert _batch_rollback_block_reason(older, selected) == "仅最近一次有效更新可以撤回"
    assert _batch_rollback_block_reason(latest, selected) is None


def test_management_batch_does_not_block_latest_business_update() -> None:
    business = _batch(
        "manual-business",
        _batch_log(
            log_id="00000000-0000-0000-0000-000000000206",
            applied_at="2026-07-12T10:00:00+00:00",
        ),
    )
    management_log = _batch_log(
        log_id="00000000-0000-0000-0000-000000000207",
        applied_at="2026-07-12T11:00:00+00:00",
        source_type="owner_assignment",
    )
    management_log["field_path"] = "owner_user_id"
    management = _batch("manual-management", management_log)

    selected = _latest_effective_batch([business, management])

    assert selected is business
    assert management["batch_category"] == "management_operation"
    assert _batch_rollback_block_reason(management, selected) == "管理操作，不参与撤回"


def test_direct_status_only_batch_is_classified_as_management() -> None:
    log = _batch_log(
        log_id="00000000-0000-0000-0000-000000000208",
        applied_at="2026-07-12T12:00:00+00:00",
    )
    log["entity_type"] = "buyer_intent"
    log["field_path"] = "status"

    assert _batch_category("direct_api", [log]) == "management_operation"


def test_failed_or_rolled_back_batch_is_not_effective() -> None:
    rolled_back_log = _batch_log(
        log_id="00000000-0000-0000-0000-000000000203",
        applied_at="2026-07-12T12:00:00+00:00",
        rollback_at="2026-07-12T12:30:00+00:00",
    )
    rolled_back = _batch("manual-rolled-back", rolled_back_log)
    rolled_back["status"] = "rolled_back"
    failed = _batch_record(
        batch_key="business-update-failed",
        entity_type="seller_target",
        entity_id=rolled_back_log["entity_id"],
        source_type="business_update",
        source_id=None,
        input_type="mixed",
        raw_input="失败材料",
        attachments=[],
        operator_user_id=rolled_back_log["applied_by"],
        operator_name="测试顾问",
        submitted_at="2026-07-12T13:00:00+00:00",
        status_value="failed",
        logs=[],
    )

    assert _latest_effective_batch([rolled_back, failed]) is None
    assert _batch_rollback_block_reason(rolled_back, None) == "本次更新已撤回"
    assert _batch_rollback_block_reason(failed, None) == "本次更新未写入字段"


def test_rollback_logs_form_a_separate_batch_from_business_update() -> None:
    original = _batch_log(
        log_id="00000000-0000-0000-0000-000000000204",
        applied_at="2026-07-12T14:00:00+00:00",
    )
    original["business_update_id"] = UUID("00000000-0000-0000-0000-000000000301")
    rollback = _batch_log(
        log_id="00000000-0000-0000-0000-000000000205",
        applied_at="2026-07-12T15:00:00+00:00",
        source_type="rollback",
    )
    rollback["business_update_id"] = original["business_update_id"]
    keys: dict[tuple[str, str, str], str] = {}

    assert _batch_key_for_log(original, keys) == f"business-update-{original['business_update_id']}"
    assert _batch_key_for_log(rollback, keys).startswith("rollback-")
