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
    _normalize_equity_requirement_type,
    _normalize_listed_status,
    _normalize_yes_no_like,
    _validate_buyer_intent_parse_output,
)
from backend.app.jobs.handlers.buyer_intent_parse import (
    _reconcile_buyer_intent_scope,
    _remove_structured_profile_duplicates,
    _route_scoped_confirmation_items,
    _set_buyer_intent_parse_stage,
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


def test_pending_confirmation_keeps_typed_candidate_for_final_reconciliation() -> None:
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
    assert changes["min_revenue_yuan"] == 5_000_000
    assert changes["needs_confirmation_json"] == [
        {
            "field": "min_revenue_yuan",
            "proposed_value": 5_000_000,
            "reason": "原文单位不明确",
            "evidence": "营收至少500",
        }
    ]
    assert "held_for_confirmation:min_revenue_yuan" in notes


def test_confirmation_reconciliation_auto_fills_empty_and_drops_equal_pending() -> None:
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {"max_pe": 13},
            "needs_confirmation": [
                {
                    "field": "max_pe",
                    "proposed_value": "13倍原则性上限",
                    "reason": "原则性上限",
                }
            ],
        },
        "PE原则上不超过13倍",
    )

    reconciled = _reconcile_buyer_intent_scope(
        None,
        current_fields={"max_pe": None},
        candidate_changes=changes,
        normalization_notes=notes,
        scope_label="非上市公司方案",
    )

    assert reconciled["max_pe"] == 13
    assert reconciled["needs_confirmation_json"] == []
    assert "auto_filled_empty:非上市公司方案:max_pe" in notes
    assert "dropped_equal_confirmation:非上市公司方案:max_pe" in notes


def test_confirmation_reconciliation_only_holds_nonempty_different_value() -> None:
    reconciled = _reconcile_buyer_intent_scope(
        None,
        current_fields={"max_pe": 13},
        candidate_changes={"max_pe": 15, "needs_confirmation_json": []},
        normalization_notes=[],
        scope_label="公共条件",
    )

    assert "max_pe" not in reconciled
    assert reconciled["needs_confirmation_json"] == [
        {
            "field": "max_pe",
            "proposed_value": 15,
            "reason": "新解析值与当前值不一致，请确认是否覆盖",
            "uncertain_part": "value",
            "scope": "公共条件",
            "item_key": "conflict:公共条件:max_pe",
        }
    ]


def test_confirmation_reconciliation_marks_invalid_value_non_actionable() -> None:
    reconciled = _reconcile_buyer_intent_scope(
        None,
        current_fields={"max_market_cap_yuan": None},
        candidate_changes={
            "needs_confirmation_json": [
                {
                    "field": "max_market_cap_yuan",
                    "proposed_value": "50亿至100亿区间放宽标准",
                    "reason": "区间含义不明确",
                }
            ]
        },
        normalization_notes=[],
        scope_label="上市公司方案",
    )

    assert "max_market_cap_yuan" not in reconciled
    assert reconciled["needs_confirmation_json"][0]["proposed_value_status"] == "invalid"
    assert reconciled["needs_confirmation_json"][0]["scope"] == "上市公司方案"


def test_confirmation_reconciliation_prefers_typed_field_over_text_placeholder() -> None:
    reconciled = _reconcile_buyer_intent_scope(
        None,
        current_fields={"premium_tolerance_summary": "适当溢价具体比例"},
        candidate_changes={
            "premium_tolerance_summary": "可接受适当溢价，具体视标的情况确定",
            "needs_confirmation_json": [
                {
                    "field": "premium_tolerance_summary",
                    "proposed_value": "适当溢价具体比例",
                    "reason": "溢价适当的具体范围未明确",
                }
            ],
        },
        normalization_notes=[],
        scope_label="公共条件",
    )

    assert "premium_tolerance_summary" not in reconciled
    assert reconciled["needs_confirmation_json"][0]["proposed_value"] == "可接受适当溢价，具体视标的情况确定"


def test_scoped_confirmation_is_routed_out_of_common_layer() -> None:
    routed = _route_scoped_confirmation_items(
        {
            "fields": {"industries_json": ["医疗健康"]},
            "needs_confirmation": [
                {"field": "max_pe", "proposed_value": 13, "reason": "需确认"}
            ],
            "scenarios": [
                {"label": "上市公司方案", "fields": {"max_market_cap_yuan": 5_000_000_000}},
                {"label": "非上市公司方案", "fields": {"max_pe": 13}},
            ],
        }
    )

    assert routed["needs_confirmation"] == []
    assert routed["scenarios"][1]["needs_confirmation"][0]["scope"] == "非上市公司方案"


def test_profile_other_removes_structured_field_duplicates() -> None:
    notes: list[str] = []
    sections = _remove_structured_profile_duplicates(
        [
            {
                "section_code": "intent_financial",
                "content_text": "负债率原则上不超过70%；关注业务稳定性；可接受适当溢价",
            }
        ],
        structured_fields={
            "debt_ratio_requirement_summary": "负债率原则上不超过70%",
            "premium_tolerance_summary": "可接受适当溢价",
        },
        normalization_notes=notes,
    )

    assert sections[0]["content_text"] == "关注业务稳定性"
    assert notes == ["profile_section_removed_structured_duplicates:intent_financial:2"]


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
                # 0817 起这一列是闭集，只认枚举码：结构码留下，另外两个轴
                # （支付方式「全现金收购」、控制权诉求「控股收购」）一律丢弃 ——
                # 它们在标的侧没有对手方列，留着只会筛出错误结果。
                "transaction_types_json": ["equity_transfer", "全现金收购", "控股收购"],
                "unacceptable_risk_flags_json": "不接受任何重大风险",
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
    assert changes["transaction_types_json"] == ["equity_transfer"]
    # 「不接受全部」在写入侧就展开成全集，SQL 那边只剩一条 not_overlap 路径。
    assert changes["unacceptable_risk_flags_json"] == [
        "litigation", "equity_frozen", "enforcement", "violation",
    ]
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


def test_buyer_profile_context_loads_linked_buyer_party() -> None:
    buyer_party_id = UUID("00000000-0000-0000-0000-000000000123")
    db = _FakeDb(
        {
            "id": buyer_party_id,
            "buyer_name": "中大咨询",
            "aliases_json": [],
            "industries_json": ["专业服务"],
            "industry_l2_json": ["咨询服务"],
            "region_province": "广东省",
            "region_city": "广州市",
            "contact_name": "王经理",
            "contact_info_json": {},
            "notes": None,
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
