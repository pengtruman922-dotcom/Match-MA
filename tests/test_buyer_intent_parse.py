import json
from uuid import UUID

from backend.app.api.routes.buyer_intents import _compact_parse_trace
from backend.app.api.routes.extracted_actions import _allowed_buyer_intent_changes
from backend.app.services.extracted_action_apply import _allowed_scenario_changes
from backend.app.jobs.handlers import (
    _build_buyer_profile_context,
    _business_update_parser_node_name,
    _normalize_actions,
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
    _repair_explicit_yuan_amounts,
    _scenario_fields_with_common_fields,
    _set_buyer_intent_parse_stage,
)

JOB_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_legacy_common_fields_are_carried_into_each_scenario() -> None:
    common = {
        "scenario_summary": "食品饮料标的，净利润 2000 万以上",
        "min_net_profit_yuan": 20_000_000,
        "acceptable_listed_status_json": ["listed", "unlisted"],
    }
    scenario = {
        "fields": {
            "acceptable_listed_status_json": ["listed"],
        }
    }

    merged = _scenario_fields_with_common_fields(scenario, common)

    assert merged == {
        "scenario_summary": "食品饮料标的，净利润 2000 万以上",
        "min_net_profit_yuan": 20_000_000,
        "acceptable_listed_status_json": ["listed"],
    }


def test_scenario_fields_win_over_legacy_common_fields() -> None:
    merged = _scenario_fields_with_common_fields(
        {"fields": {"max_pe": 15}},
        {"max_pe": 50},
    )

    assert merged["max_pe"] == 15


def test_explicit_ocr_yuan_threshold_repairs_model_scale_error() -> None:
    changes = {"max_market_cap_yuan": 1_500_000_000, "min_net_profit_yuan": 2_000_000}
    notes: list[str] = []
    _repair_explicit_yuan_amounts(
        changes,
        "市值范围：15\n0亿元以内；经营情况（净利润要求）：0.2\n亿元以上",
        notes,
    )

    assert changes["max_market_cap_yuan"] == 15_000_000_000
    assert changes["min_net_profit_yuan"] == 20_000_000
    assert len(notes) == 2


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
                "business_tags_json": ["医药与健康"],
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
        scope="scenario",
    )

    assert changes["business_tags_json"] == ["医药与健康"]
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
        scope="scenario",
    )

    reconciled = _reconcile_buyer_intent_scope(
        None,
        current_fields={"max_pe": None},
        candidate_changes=changes,
        normalization_notes=notes,
        scope_label="方案 2",
    )

    assert reconciled["max_pe"] == 13
    assert reconciled["needs_confirmation_json"] == []
    assert "auto_filled_empty:方案 2:max_pe" in notes
    assert "dropped_equal_confirmation:方案 2:max_pe" in notes


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
        current_fields={"other_requirements_text": "风险容忍具体口径"},
        candidate_changes={
            "other_requirements_text": "可接受轻微涉诉，具体视标的情况确定",
            "needs_confirmation_json": [
                {
                    "field": "other_requirements_text",
                    "proposed_value": "风险容忍具体口径",
                    "reason": "可接受的风险程度未明确",
                }
            ],
        },
        normalization_notes=[],
        scope_label="方案 1",
    )

    assert "other_requirements_text" not in reconciled
    assert reconciled["needs_confirmation_json"][0]["proposed_value"] == "可接受轻微涉诉，具体视标的情况确定"


def test_scoped_confirmation_is_routed_out_of_common_layer() -> None:
    routed = _route_scoped_confirmation_items(
        {
            "fields": {"intent_business_tags_json": ["医疗健康"]},
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
                "content_text": "浙江本地医药健康标的；关注业务稳定性；找新式茶饮与精品咖啡",
            }
        ],
        # 0901 起门槛住在方案里，所以去重比对的对象也是方案的文本列。
        # 只比**非条件**字段：条件字段的值是数字，拿去做子串比对会误删
        # 「营收 5 亿」这类句子里的数字部分。
        structured_fields={
            "scenario_summary": "浙江本地医药健康标的",
            "other_requirements_text": "找新式茶饮与精品咖啡",
        },
        normalization_notes=notes,
    )

    assert sections[0]["content_text"] == "关注业务稳定性"
    assert notes == ["profile_section_removed_structured_duplicates:intent_financial:2"]


def test_pending_multi_value_items_are_isolated_individually() -> None:
    """多值列的待确认项逐条隔离，不是整列一起挂起。

    0828 起这条测的是业务标签而不是 industries_json：行业字典在需求侧已下线，
    标签是自由标签、不过字典，但「模型自己拿不准的那两个」仍然要单独挂起，
    确定的那个照常落库。
    """
    changes, _ = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "business_tags_json": ["医药与健康", "不确定方向A", "不确定方向B"],
            },
            "needs_confirmation": [
                {
                    "field": "business_tags_json",
                    "item_key": "direction-a",
                    "proposed_value": "不确定方向A",
                    "reason": "无法确认方向A",
                    "evidence": "关注不确定方向",
                },
                {
                    "field": "business_tags_json",
                    "item_key": "direction-b",
                    "proposed_value": "不确定方向B",
                    "reason": "无法确认方向B",
                    "evidence": "关注不确定方向",
                },
            ],
        },
        "关注医药与健康及两个不确定方向",
        scope="scenario",
    )

    assert changes["business_tags_json"] == ["医药与健康"]
    assert [item["item_key"] for item in changes["needs_confirmation_json"]] == [
        "direction-a",
        "direction-b",
    ]


def test_buyer_intent_parse_changes_normalize_common_enums_and_numbers() -> None:
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "min_net_profit_yuan": "20000000",
                "min_market_cap_yuan": "500000000",
                "max_market_cap_yuan": "3000000000",
                "acceptable_listed_status_json": ["非上市"],
                "scenario_summary": "浙江本地医药健康标的",
                "other_requirements_text": "不接受重大诉讼、冻结、执行；要并表",
                "required_regions_json": [{"province": "浙江省"}],
                # 0901 退役：控股/并表要求（实测真淘汰 0 次）、可接受交易结构
                # （标的侧录入率 1%）、不接受的重大风险（4%）、风险容忍、产业优势。
                # 旧版提示词仍会吐它们，写入侧必须当成 unsupported 丢掉 ——
                # 「退役」的落点就在这里。
                "requires_consolidation": "需要",
                "transaction_types_json": ["equity_transfer"],
                "unacceptable_risk_flags_json": "不接受任何重大风险",
                "major_risk_tolerance_summary": "不接受重大诉讼、冻结、执行",
                "buyer_industry_advantage_summary": "浙江本地国资有医药产业资源",
                # 0828 退役的四列
                "listing_board_requirement_summary": "北交所或创业板均可",
                "max_debt_ratio": "65",
                "equity_requirement_type": "可并表即可",
                "unsupported_field": "ignored",
            }
        },
        "浙江医药健康，利润2000万以上，要并表，非上市。",
        scope="scenario",
    )

    assert changes["min_net_profit_yuan"] == 20000000
    assert changes["min_market_cap_yuan"] == 500000000
    assert changes["max_market_cap_yuan"] == 3000000000
    assert changes["acceptable_listed_status_json"] == ["unlisted"]
    assert changes["scenario_summary"] == "浙江本地医药健康标的"
    assert changes["required_regions_json"][0]["province"] == "浙江省"
    # preferred_listed_status 是需求侧的兼容派生列，方案表上没有它 ——
    # 写进去会让 insert 的参数表多出一个不存在的列名。
    assert "preferred_listed_status" not in changes
    for retired in (
        "requires_consolidation",
        "transaction_types_json",
        "unacceptable_risk_flags_json",
        "major_risk_tolerance_summary",
        "buyer_industry_advantage_summary",
        "listing_board_requirement_summary",
        "max_debt_ratio",
        "equity_requirement_type",
    ):
        assert retired not in changes, f"{retired} 已退役，不该再被解析写入"
    assert sorted(notes) == sorted(
        [
            f"ignored_unsupported_field:{field}"
            for field in (
                "requires_consolidation",
                "transaction_types_json",
                "unacceptable_risk_flags_json",
                "major_risk_tolerance_summary",
                "buyer_industry_advantage_summary",
                "listing_board_requirement_summary",
                "max_debt_ratio",
                "equity_requirement_type",
                "unsupported_field",
            )
        ]
    )


def test_buyer_intent_parser_enum_helpers_are_tolerant() -> None:
    assert _normalize_yes_no_like("否") == "no"
    assert _normalize_yes_no_like("可接受") == "yes"
    assert _normalize_yes_no_like("不接受") == "no"
    assert _normalize_yes_no_like("可能") == "unknown"
    assert _normalize_listed_status("不限") == "any"
    assert _normalize_listed_status("准备上市") == "preparing_listing"
    assert _normalize_listed_status("pre IPO") == "pre_ipo"
    assert _normalize_equity_requirement_type("参股也可以") == "minority_acceptable"


def test_buyer_intent_parse_separates_valuation_from_market_cap() -> None:
    """估值与市值是两回事，模型把同一个数同时填进两边时市值必须被丢掉。

    0828 起同一个用例还守着第二件事：**退役字段不再被写入**。
    PS 上限、净利率、毛利率、市值范围说明、字典外细分方向这五列在库里还在
    （阶段 A 一列没删），但解析已经看不见它们了 —— 旧版提示词仍会吐出来，
    写入侧必须当成 unsupported 丢掉。
    """
    changes, notes = _normalize_buyer_intent_parse_changes(
        {
            "fields": {
                "min_valuation_yuan": "1500000000",
                "max_valuation_yuan": "2500000000",
                "min_market_cap_yuan": "1500000000",
                "business_tags_json": ["新式茶饮", "精品咖啡", "新式茶饮", ""],
                "scenario_summary": "找新式茶饮与精品咖啡连锁品牌",
                # 以下五列已退役
                "market_cap_range_summary": "15亿至25亿元",
                "max_ps": "3",
                "min_net_margin": "8",
                "min_gross_margin": "35",
                "industry_focus_tags_json": ["新式茶饮"],
            }
        },
        "关注新式茶饮和精品咖啡，估值15亿至25亿元，PS不高于3倍，净利率不低于8%。",
        scope="scenario",
    )

    assert changes["min_valuation_yuan"] == 1_500_000_000
    assert changes["max_valuation_yuan"] == 2_500_000_000
    assert changes["business_tags_json"] == ["新式茶饮", "精品咖啡"]
    assert changes["scenario_summary"] == "找新式茶饮与精品咖啡连锁品牌"
    # 与估值同值的市值被丢掉，理由单独留痕。
    assert "min_market_cap_yuan" not in changes
    assert any(note.startswith("dropped_min_market_cap_yuan") for note in notes)
    for retired in (
        "market_cap_range_summary",
        "max_ps",
        "min_net_margin",
        "min_gross_margin",
        "industry_focus_tags_json",
    ):
        assert retired not in changes, f"{retired} 已退役，不该再被解析写入"


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


def test_buyer_intent_update_apply_whitelist_follows_the_registry() -> None:
    """业务更新采纳白名单与解析白名单是同一个派生。

    两份手抄的表现是「新建解析不写了，但带附件的业务更新还在写」——
    2026-08-01 在行业字段上实测到过一次，0828 退役 32 列会把它放大 32 倍。
    """
    payload = {
        "intent_name": "某某集团-并购需求",
        "business_tags_json": ["商贸与消费"],
        "excluded_business_text": "酒类",
        "scenario_summary": "找新式茶饮连锁",
        "min_valuation_yuan": 1_500_000_000,
        # 退役列与从未存在的列，两者都必须被丢掉
        "industries_json": ["商贸与消费"],
        "max_ps": 3,
        "unsupported": "drop",
    }

    # 0901 起一条业务更新可能同时改容器和方案，所以分流成两份 ——
    # 混用一份的表现是「门槛类改动被当成 unsupported 静默丢掉」，
    # 业务更新照样显示「已采纳」，而库里那个数字一个都没变。
    assert _allowed_buyer_intent_changes(payload) == {"intent_name": "某某集团-并购需求"}
    assert _allowed_scenario_changes(payload) == {
        "business_tags_json": ["商贸与消费"],
        "excluded_business_text": "酒类",
        "scenario_summary": "找新式茶饮连锁",
        "min_valuation_yuan": 1_500_000_000,
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
                        "business_tags_json": ["新式茶饮", "新式茶饮"],
                    },
                    "raw_evidence_text": "估值15亿元以上，关注新式茶饮",
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
    assert changes["business_tags_json"] == ["新式茶饮"]
    assert "min_market_cap_yuan" not in changes


def test_buyer_profile_context_loads_linked_buyer_party() -> None:
    buyer_party_id = UUID("00000000-0000-0000-0000-000000000123")
    db = _FakeDb(
        {
            "id": buyer_party_id,
            "buyer_name": "中大咨询",
            "aliases_json": [],
            "business_tags_json": ["管理咨询", "工程咨询"],
            "business_summary": "面向政企的管理与工程咨询服务商。",
            "ownership_type": "private",
            "listed_status": "unlisted",
            "location_province": "广东省",
            "location_city": "广州市",
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


# -- 0828：精简的收益不在数据库，在解析提示词 -----------------------------


def test_the_field_and_enum_contracts_are_filtered_by_the_same_switch() -> None:
    """两份契约都只装「模型能写的」，口径必须一致。

    只过滤字段表、不过滤取值表的后果很隐蔽：字段表变短了，但退役字段的闭集
    还在取值表里 —— 模型看到一张它填不进任何东西的表，每次解析都要为它分一次
    注意力。0828 实测取值表从 17 项 1385 字符降到 7 项 468 字符。

    **每多一个字段，模型每次解析都要判一次「这里有没有这个信息」** ——
    精简换的是解析准确率，不是数据库空间。
    """
    from backend.app.jobs.handlers.buyer_intent_parse import (
        _buyer_intent_enum_contract,
        _buyer_intent_field_contract,
    )
    from backend.app.registry.indicators import writable_columns

    # 0901 起契约的主体是**方案**的字段：需求本身只是容器。
    writable = writable_columns("parse", "buyer_intent") | writable_columns(
        "parse", "buyer_intent_scenario"
    )
    contract_columns = {entry["field"] for entry in _buyer_intent_field_contract()}

    assert contract_columns == writable
    assert set(_buyer_intent_enum_contract()) <= writable

    # 退役字段一个都不许出现在任何一份契约里 —— 那正是本轮改动的落点。
    for retired in (
        "industries_json",
        "max_debt_ratio",
        "listing_market_region",
        "requires_relocation",
        "requires_control",
        "transaction_types_json",
        "excluded_regions_json",
        "desired_equity_ratio_min",
    ):
        assert retired not in contract_columns
        assert retired not in _buyer_intent_enum_contract()


def test_the_contract_tells_the_model_which_fields_are_actually_screened() -> None:
    """`is_condition` 读 `screening`。

    0901 删掉了 default_effect（「这个买家有多想要」）：它从来没进过 SQL，
    却在契约里告诉模型有强弱之分，模型于是花注意力去判一个不存在的维度。
    """
    from backend.app.jobs.handlers.buyer_intent_parse import _buyer_intent_field_contract

    by_field = {entry["field"]: entry for entry in _buyer_intent_field_contract()}

    assert by_field["min_revenue_yuan"]["is_condition"] is True
    assert by_field["required_regions_json"]["is_condition"] is True
    # 【召】类：进首轮召回给 LLM 读，但不参与 SQL 初筛。
    assert by_field["scenario_summary"]["is_condition"] is False
    assert by_field["business_tags_json"]["is_condition"] is False
    assert by_field["other_requirements_text"]["is_condition"] is False
    # 业务列没有对手方 —— 这是判决一的含义，方案化没有改变它。
    assert by_field["business_tags_json"]["target_field"] is None
    assert by_field["scenario_summary"]["operator"] is None
    # 契约必须告诉模型每一条落在哪一层，否则它无从决定写进 fields 还是 scenarios。
    assert by_field["min_revenue_yuan"]["scope"] == "scenario"
    assert by_field["intent_grade"]["scope"] == "intent"
