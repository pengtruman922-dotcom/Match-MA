from uuid import UUID

from backend.app.api.routes.buyer_intents import _compact_parse_trace
from backend.app.jobs.handlers import (
    _normalize_buyer_intent_parse_changes,
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_yes_no_like,
    _validate_buyer_intent_parse_output,
)


JOB_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_buyer_intent_parse_output_validation_requires_supported_fields() -> None:
    valid = _validate_buyer_intent_parse_output({"fields": {"min_net_profit_yuan": 20000000}})
    invalid = _validate_buyer_intent_parse_output({"fields": {"unsupported": "x"}})

    assert valid["valid"] is True
    assert valid["field_count"] == 1
    assert invalid["valid"] is False


def test_buyer_intent_parse_changes_normalize_common_enums_and_numbers() -> None:
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "raw_requirement_text": "浙江医药健康，利润2000万以上，要并表，非上市。",
                "min_net_profit_yuan": "20000000",
                "requires_consolidation": "需要",
                "preferred_listed_status": "非上市",
                "equity_requirement_type": "可并表即可",
                "region_constraints_json": [{"province": "浙江省", "constraint_type": "hard"}],
                "unsupported_field": "ignored",
            }
        },
        "浙江医药健康，利润2000万以上，要并表，非上市。",
    )

    assert changes["min_net_profit_yuan"] == 20000000
    assert changes["requires_consolidation"] == "yes"
    assert changes["preferred_listed_status"] == "unlisted"
    assert changes["equity_requirement_type"] == "consolidation_required"
    assert changes["region_constraints_json"][0]["province"] == "浙江省"
    assert notes == ["ignored_unsupported_field:unsupported_field"]


def test_buyer_intent_parser_enum_helpers_are_tolerant() -> None:
    assert _normalize_yes_no_like("否") == "no"
    assert _normalize_yes_no_like("可能") == "unknown"
    assert _normalize_listed_status("不限") == "any"
    assert _normalize_equity_requirement_type("参股也可以") == "minority_acceptable"


def test_compact_parse_trace_hides_long_raw_output() -> None:
    trace = _compact_parse_trace(
        {
            "id": UUID("00000000-0000-0000-0000-000000000002"),
            "trace_type": "llm",
            "node_name": "buyer_intent_parser",
            "job_id": JOB_ID,
            "provider_name": "aliyun_dashscope",
            "model_name": "qwen3.6-flash",
            "prompt_version": "v0.2.0",
            "status": "succeeded",
            "raw_output_text": "x" * 1000,
            "parsed_output_json": {"fields": {"intent_summary": "x"}},
            "schema_validation_json": {"valid": True},
            "error_code": None,
            "error_message": None,
            "latency_ms": 100,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "started_at": "2026-06-02",
            "finished_at": "2026-06-02",
        }
    )

    assert trace["raw_output_preview"].endswith("…")
    assert len(trace["raw_output_preview"]) == 800
    assert trace["debug_ref"]["route"].endswith(f"/debug/entities/background_job/{JOB_ID}")
