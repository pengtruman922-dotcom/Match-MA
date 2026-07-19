from backend.app.services.recommendation_conditions import (
    apply_overrides_to_anchor,
    conditions_snapshot,
    derive_route,
    describe_condition_ops,
    fallback_parse_result,
    merge_condition_overrides,
    normalize_parse_result,
)


def test_normalize_filters_unknown_fields_and_ops() -> None:
    result = normalize_parse_result(
        {
            "condition_ops": [
                {"op": "set", "field": "region_scope_summary", "value": "浙江"},
                {"op": "set", "field": "min_net_profit_yuan", "value": "15000000"},
                {"op": "set", "field": "not_a_field", "value": 1},
                {"op": "drop", "field": "max_pe", "value": None},
                {"op": "remove", "field": "max_pe"},
                {"op": "exclude", "field": "excluded_industries_json", "value": "房地产与建筑"},
                {"op": "exclude", "field": "region_scope_summary", "value": "上海"},
                {"op": "set", "field": "requires_consolidation", "value": "YES"},
                {"op": "set", "field": "preferred_listed_status", "value": "ipo-ready"},
            ],
            "semantic_preferences": ["最好有出海业务", "", None],
            "display_ops": [
                {"type": "only_grade", "value": "a"},
                {"type": "top_n", "value": "8"},
                {"type": "top_n", "value": 0},
                {"type": "hide", "value": 1},
            ],
            "question": "  ",
        }
    )

    assert result["condition_ops"] == [
        {"op": "set", "field": "region_scope_summary", "value": "浙江"},
        {"op": "set", "field": "min_net_profit_yuan", "value": 15000000.0},
        {"op": "remove", "field": "max_pe", "value": None},
        {"op": "exclude", "field": "excluded_industries_json", "value": "房地产与建筑"},
        {"op": "set", "field": "requires_consolidation", "value": "yes"},
    ]
    assert result["semantic_preferences"] == ["最好有出海业务"]
    assert result["display_ops"] == [
        {"type": "only_grade", "value": "A"},
        {"type": "top_n", "value": 8},
    ]
    assert result["question"] is None
    assert result["parser_status"] == "ok"


def test_merge_set_remove_exclude_and_preferences() -> None:
    merged = merge_condition_overrides(
        None,
        {
            "condition_ops": [
                {"op": "set", "field": "region_scope_summary", "value": "浙江"},
                {"op": "set", "field": "max_pe", "value": 15.0},
                {"op": "exclude", "field": "excluded_industries_json", "value": "风电"},
            ],
            "semantic_preferences": ["有出海业务"],
        },
    )
    merged = merge_condition_overrides(
        merged,
        {
            "condition_ops": [
                {"op": "remove", "field": "max_pe", "value": None},
                {"op": "set", "field": "region_scope_summary", "value": "长三角"},
                {"op": "exclude", "field": "excluded_industries_json", "value": "风电"},
            ],
            "semantic_preferences": ["有出海业务", "团队留任"],
        },
    )

    assert merged["fields"] == {"region_scope_summary": "长三角"}
    assert merged["removed_fields"] == ["max_pe"]
    assert merged["extra_excluded_industries"] == ["风电"]
    assert merged["semantic_preferences"] == ["有出海业务", "团队留任"]


def test_apply_overrides_to_anchor_overlays_and_clears() -> None:
    anchor = {
        "intent_name": "测试意向",
        "region_scope_summary": "全国",
        "max_pe": 12,
        "min_net_profit_yuan": 20000000,
        "excluded_industries_json": ["房地产与建筑"],
    }
    effective = apply_overrides_to_anchor(
        anchor,
        {
            "fields": {"region_scope_summary": "浙江", "min_net_profit_yuan": 15000000},
            "removed_fields": ["max_pe"],
            "extra_excluded_industries": ["风电"],
            "semantic_preferences": ["有出海业务"],
        },
    )

    assert effective["region_scope_summary"] == "浙江"
    assert effective["min_net_profit_yuan"] == 15000000
    assert effective["max_pe"] is None
    assert effective["excluded_industries_json"] == ["房地产与建筑", "风电"]
    assert anchor["region_scope_summary"] == "全国"  # original untouched


def test_conditions_snapshot_reflects_effective_values() -> None:
    anchor = {"region_scope_summary": "全国", "max_pe": 12}
    snapshot = conditions_snapshot(
        anchor,
        {
            "fields": {"region_scope_summary": "浙江"},
            "removed_fields": ["max_pe"],
            "extra_excluded_industries": [],
            "semantic_preferences": ["有出海业务"],
        },
    )

    assert snapshot["region_scope_summary"] == "浙江"
    assert "max_pe" not in snapshot
    assert snapshot["semantic_preferences"] == ["有出海业务"]


def test_derive_route_priority() -> None:
    assert derive_route(None) == "refilter"
    assert derive_route({"condition_ops": [{"op": "set"}], "semantic_preferences": ["x"], "display_ops": [], "question": "q"}) == "refilter"
    assert derive_route({"condition_ops": [], "semantic_preferences": ["x"], "display_ops": [], "question": None}) == "re_evaluate"
    assert derive_route({"condition_ops": [], "semantic_preferences": [], "display_ops": [{"type": "only_grade", "value": "A"}], "question": None}) == "display"
    assert derive_route({"condition_ops": [], "semantic_preferences": [], "display_ops": [], "question": "对比第1和第3个"}) == "question"
    assert derive_route({"condition_ops": [], "semantic_preferences": [], "display_ops": [], "question": None}) == "noop"


def test_fallback_records_message_as_preference() -> None:
    result = fallback_parse_result("只看浙江的")

    assert result["parser_status"] == "fallback"
    assert result["semantic_preferences"] == ["只看浙江的"]
    assert derive_route(result) == "re_evaluate"


def test_describe_condition_ops_readable() -> None:
    text = describe_condition_ops(
        [
            {"op": "set", "field": "region_scope_summary", "value": "浙江"},
            {"op": "set", "field": "min_net_profit_yuan", "value": 15000000.0},
            {"op": "remove", "field": "max_pe", "value": None},
            {"op": "exclude", "field": "excluded_industries_json", "value": "风电"},
        ]
    )

    assert "地区=浙江" in text
    assert "净利润下限=1500万" in text
    assert "取消PE上限" in text
    assert "排除风电" in text
