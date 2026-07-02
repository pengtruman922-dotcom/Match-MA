from uuid import UUID

from backend.app.api.routes.buyer_intents import _compact_parse_trace
from backend.app.jobs.handlers import (
    _build_buyer_profile_context,
    _normalize_buyer_party_parse_changes,
    _normalize_buyer_intent_parse_changes,
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_yes_no_like,
    _validate_buyer_intent_parse_output,
)


JOB_ID = UUID("00000000-0000-0000-0000-000000000001")


class _FakeMappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _FakeMappingResult(self.row)


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
                "listing_board_requirement_summary": "北交所或创业板均可",
                "financing_stage_requirement_summary": "pre-IPO",
                "min_market_cap_yuan": "500000000",
                "max_market_cap_yuan": "3000000000",
                "transaction_types_json": ["control", "minority"],
                "max_debt_ratio": "65",
                "major_risk_tolerance_summary": "不接受重大诉讼、冻结、执行",
                "buyer_industry_advantage_summary": "浙江本地国资有医药产业资源",
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
    assert changes["listing_board_requirement_summary"] == "北交所或创业板均可"
    assert changes["financing_stage_requirement_summary"] == "pre-IPO"
    assert changes["min_market_cap_yuan"] == 500000000
    assert changes["max_market_cap_yuan"] == 3000000000
    assert changes["transaction_types_json"] == ["control", "minority"]
    assert changes["max_debt_ratio"] == 65
    assert changes["major_risk_tolerance_summary"] == "不接受重大诉讼、冻结、执行"
    assert changes["buyer_industry_advantage_summary"] == "浙江本地国资有医药产业资源"
    assert changes["equity_requirement_type"] == "consolidation_required"
    assert changes["region_constraints_json"][0]["province"] == "浙江省"
    assert notes == ["ignored_unsupported_field:unsupported_field"]


def test_buyer_intent_parser_enum_helpers_are_tolerant() -> None:
    assert _normalize_yes_no_like("否") == "no"
    assert _normalize_yes_no_like("可接受") == "yes"
    assert _normalize_yes_no_like("不接受") == "no"
    assert _normalize_yes_no_like("可能") == "unknown"
    assert _normalize_listed_status("不限") == "any"
    assert _normalize_listed_status("准备上市") == "preparing_listing"
    assert _normalize_listed_status("pre IPO") == "pre_ipo"
    assert _normalize_equity_requirement_type("参股也可以") == "minority_acceptable"


def test_buyer_party_parse_changes_normalize_model_buyer_type_aliases() -> None:
    changes = _normalize_buyer_party_parse_changes(
        {
            "buyer_party": {
                "buyer_type": "strategic",
                "listed_status": "不限",
                "group_name": "华源",
                "main_business": "冶炼及关键金属供应链",
            }
        }
    )

    assert changes["buyer_type"] == "industrial_buyer"
    assert changes["listed_status"] == "unknown"
    assert changes["group_name"] == "华源"


def test_buyer_profile_context_loads_linked_buyer_party() -> None:
    buyer_party_id = UUID("00000000-0000-0000-0000-000000000123")
    db = _FakeDb(
        {
            "id": buyer_party_id,
            "buyer_name": "中大咨询",
            "legal_name": "中大咨询有限公司",
            "aliases_json": [],
            "buyer_type": "industrial_buyer",
            "group_name": None,
            "listed_status": "unlisted",
            "region_province": "广东省",
            "region_city": "广州市",
            "main_business": "咨询服务",
            "capital_strength_summary": None,
            "profile_summary": None,
            "status": "active",
        }
    )

    context = _build_buyer_profile_context(
        db,
        {
            "id": "00000000-0000-0000-0000-000000000456",
            "buyer_party_id": str(buyer_party_id),
            "intent_name": "交通行业收购",
        },
    )

    assert context["buyer_party"]["id"] == str(buyer_party_id)
    assert context["buyer_party"]["buyer_name"] == "中大咨询"
    assert db.params["buyer_party_id"] == buyer_party_id
    assert "from buyer_party" in db.statement


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
