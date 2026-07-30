import json
from uuid import UUID

from backend.app.api.routes.buyer_intents import _compact_parse_trace
from backend.app.api.routes.extracted_actions import _allowed_buyer_intent_changes
from backend.app.jobs.handlers import (
    _build_buyer_profile_context,
    _business_update_parser_node_name,
    _normalize_actions,
    _normalize_buyer_intent_industry_changes,
    _normalize_buyer_intent_parse_changes,
    _normalize_buyer_party_parse_changes,
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_yes_no_like,
    _validate_buyer_intent_parse_output,
)
from backend.app.jobs.handlers.buyer_intent_parse import _set_buyer_intent_parse_stage

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
        self.committed = False

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _FakeMappingResult(self.row)

    def commit(self):
        self.committed = True


def test_buyer_intent_stage_metadata_uses_typed_jsonb_patch() -> None:
    db = _FakeDb(None)

    _set_buyer_intent_parse_stage(db, JOB_ID, "semantic_parsing")

    assert "metadata_json = metadata_json || :metadata_patch" in db.statement
    assert "jsonb_build_object" not in db.statement
    assert db.params["metadata_patch"]["processing_stage"] == "semantic_parsing"
    json.dumps(db.params["metadata_patch"])
    assert db.committed is True


def test_buyer_intent_parse_output_validation_requires_supported_fields() -> None:
    valid = _validate_buyer_intent_parse_output({"fields": {"min_net_profit_yuan": 20000000}})
    invalid = _validate_buyer_intent_parse_output({"fields": {"unsupported": "x"}})

    assert valid["valid"] is True
    assert valid["field_count"] == 1
    assert invalid["valid"] is False


def test_pending_confirmation_field_is_stored_but_not_applied() -> None:
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "industries_json": ["医药与健康"],
                "min_revenue_yuan": 5_000_000,
            },
            "needs_confirmation": [
                {
                    "field": "min_revenue_yuan",
                    "proposed_value": 5_000_000,
                    "reason": "原文单位不明确",
                    "evidence": "营收至少500",
                    "confidence": 0.4,
                }
            ],
        },
        "医药与健康，营收至少500",
    )

    assert changes["industries_json"] == ["医药与健康"]
    assert "min_revenue_yuan" not in changes
    assert changes["needs_confirmation_json"] == [
        {
            "field": "min_revenue_yuan",
            "proposed_value": 5_000_000,
            "reason": "原文单位不明确",
            "evidence": "营收至少500",
        }
    ]
    assert "held_for_confirmation:min_revenue_yuan" in notes


def test_pending_multi_value_items_are_isolated_individually() -> None:
    changes, _ = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "industries_json": ["医药与健康", "不确定行业A", "不确定行业B"],
            },
            "needs_confirmation": [
                {
                    "field": "industries_json",
                    "item_key": "industry-a",
                    "proposed_value": "不确定行业A",
                    "reason": "无法映射行业A",
                    "evidence": "关注不确定行业",
                },
                {
                    "field": "industries_json",
                    "item_key": "industry-b",
                    "proposed_value": "不确定行业B",
                    "reason": "无法映射行业B",
                    "evidence": "关注不确定行业",
                },
            ],
        },
        "关注医药与健康及两个不确定行业",
    )

    assert changes["industries_json"] == ["医药与健康"]
    assert [item["item_key"] for item in changes["needs_confirmation_json"]] == [
        "industry-a",
        "industry-b",
    ]


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


def test_buyer_intent_parse_separates_valuation_from_market_cap_and_keeps_focus_fields() -> None:
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "min_valuation_yuan": "1500000000",
                "max_valuation_yuan": "2500000000",
                "min_market_cap_yuan": "1500000000",
                "market_cap_range_summary": "15亿至25亿元",
                "max_ps": "3",
                "min_net_margin": "8",
                "min_gross_margin": "35",
                "industry_focus_tags_json": ["新式茶饮", "精品咖啡", "新式茶饮", ""],
            }
        },
        "关注新式茶饮和精品咖啡，估值15亿至25亿元，PS不高于3倍，净利率不低于8%。",
    )
    industry_notes = _normalize_buyer_intent_industry_changes(None, changes)

    assert changes["min_valuation_yuan"] == 1_500_000_000
    assert changes["max_valuation_yuan"] == 2_500_000_000
    assert changes["max_ps"] == 3
    assert changes["min_net_margin"] == 8
    assert changes["min_gross_margin"] == 35
    assert changes["industry_focus_tags_json"] == ["新式茶饮", "精品咖啡"]
    assert "min_market_cap_yuan" not in changes
    assert "market_cap_range_summary" not in changes
    assert industry_notes == []
    assert any(note.startswith("dropped_min_market_cap_yuan") for note in notes)


def test_business_update_uses_entity_specific_parser_nodes() -> None:
    assert _business_update_parser_node_name(
        {"bound_seller_target_ids_json": [], "bound_buyer_intent_ids_json": [str(JOB_ID)]}
    ) == "buyer_intent_update_parser"
    assert _business_update_parser_node_name(
        {"bound_seller_target_ids_json": [str(JOB_ID)], "bound_buyer_intent_ids_json": []}
    ) == "seller_target_update_parser"
    assert _business_update_parser_node_name(
        {"bound_seller_target_ids_json": [str(JOB_ID)], "bound_buyer_intent_ids_json": [str(JOB_ID)]}
    ) == "business_update_extractor"


def test_buyer_intent_update_apply_keeps_new_structured_fields() -> None:
    changes = _allowed_buyer_intent_changes(
        {
            "industries_json": ["商贸与消费"],
            "excluded_industries_json": ["酒类"],
            "industry_focus_tags_json": ["新式茶饮"],
            "min_valuation_yuan": 1_500_000_000,
            "max_ps": 3,
            "min_net_margin": 8,
            "min_gross_margin": 35,
            "unsupported": "drop",
        }
    )

    assert changes == {
        "industries_json": ["商贸与消费"],
        "excluded_industries_json": ["酒类"],
        "industry_focus_tags_json": ["新式茶饮"],
        "min_valuation_yuan": 1_500_000_000,
        "max_ps": 3,
        "min_net_margin": 8,
        "min_gross_margin": 35,
    }


def test_buyer_intent_update_action_normalizes_numbers_and_valuation_semantics() -> None:
    intent_id = UUID("00000000-0000-0000-0000-000000000322")
    actions = _normalize_actions(
        {
            "actions": [
                {
                    "action_type": "buyer_intent_update",
                    "target_entity_type": "buyer_intent",
                    "proposed_changes_json": {
                        "min_valuation_yuan": "1500000000",
                        "min_market_cap_yuan": "1500000000",
                        "max_ps": "3",
                        "industry_focus_tags_json": ["新式茶饮", "新式茶饮"],
                    },
                    "raw_evidence_text": "估值15亿元以上，PS不高于3倍，关注新式茶饮",
                }
            ]
        },
        {
            "raw_text": "估值15亿元以上",
            "bound_seller_target_ids_json": [],
            "bound_buyer_intent_ids_json": [str(intent_id)],
            "bound_buyer_party_ids_json": [],
            "attachment_evidence_ids": [],
            "image_evidence_attachment_ids": [],
        },
    )

    changes = actions[0]["proposed_changes_json"]
    assert changes["min_valuation_yuan"] == 1_500_000_000
    assert changes["max_ps"] == 3
    assert changes["industry_focus_tags_json"] == ["新式茶饮"]
    assert "min_market_cap_yuan" not in changes


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
