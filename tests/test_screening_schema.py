"""初筛 schema 的结构与闭集契约（施工单 0817 · 阶段一，0828 随行业下线改写）。

改造前的 schema 是手写的：只开放了 12 个字段（引擎实际支持 26 个），行业名没有
闭集约束，模型写错一个行业名会静默清空整个候选池。这些用例钉住的第一条仍然有效：
**字段清单必须来自注册表，这里不留第二处判断。**

第二条（行业取值必须来自字典）2026-08-28 随判决一作废：买家需求侧的行业字典
下线，行业条件整组退出初筛，业务匹配交给 LLM 读业务摘要。所以本文件里原来那批
行业用例换成了地区两列的用例 —— 地区是现在唯一带运行时形状的条件。
"""

import pytest

from backend.app.registry.indicators import indicator_by_column, indicators_for
from backend.app.services.screening_schema import (
    SCREENING_FIELDS,
    SCREENING_FIELDS_BY_COLUMN,
    build_conditions_properties,
    normalize_conditions,
)

def _properties() -> dict:
    return build_conditions_properties()


def _screening_columns() -> set[str]:
    return {
        indicator.column
        for indicator in indicators_for("buyer_intent")
        if indicator.screening and indicator.operator and indicator.target_column
    }


# -- 字段清单来自注册表 ---------------------------------------------------


def test_schema_covers_exactly_what_the_registry_marks_screening() -> None:
    """一个字段进不进初筛，只有注册表说了算 —— 这里不留第二处判断。"""
    assert set(SCREENING_FIELDS_BY_COLUMN) == _screening_columns()
    # 数量不写死成一个魔数：0828 退役了 8 个条件、新建了 2 个地区条件，这类进出
    # 会继续发生。要守的是「schema 与注册表逐字段一致」，不是「一共几个」。
    assert len(SCREENING_FIELDS) == len(_screening_columns())


def test_the_two_broken_conditions_stay_out() -> None:
    """净利率两侧口径不同（买家百分数、标的现算是分数），不 ×100 就恒为空集；
    PS 的分子是市值，非上市标的没有，一带上就把候选池打空。

    两个都由注册表 screening=False 表达，理由写在注册表那两行的注释里。
    """
    for column in ("min_net_margin", "max_ps"):
        assert column not in _properties()
        assert not indicator_by_column("buyer_intent", column).screening


def test_every_property_declares_a_type_and_a_description() -> None:
    for column, spec in _properties().items():
        assert spec.get("type"), column
        assert spec.get("description"), column


# -- 行业条件已整组退役，地区是唯一带形状的条件 ---------------------------


def test_industry_conditions_are_gone_from_the_schema() -> None:
    """判决一的落点：需求侧行业字典下线 = 正向初筛不再有行业条件。

    这不是副作用，是同一个判断的必然结果 —— 跨侧匹配需要共享词表，
    而共享词表正是行业字典存在的唯一理由。补偿在 search_targets 的
    business_scan：一次把命中集的业务摘要全量吐给主 Agent 做首轮语义筛。
    """
    properties = _properties()
    for column in ("industries_json", "industry_l2_json", "excluded_industries_json"):
        assert column not in properties
        assert column not in SCREENING_FIELDS_BY_COLUMN
    # 标的侧那一列也不再挂「筛」角标：没有任何买家条件能打在它上面了。
    # 角标撒谎的代价是顾问按它决定先补哪个字段，补错方向。
    assert not indicator_by_column("seller_target", "industry_pairs_json").screening


@pytest.mark.parametrize("column", ["acceptable_regions_json", "excluded_regions_json"])
def test_region_takes_three_optional_levels(column: str) -> None:
    spec = _properties()[column]

    assert spec["type"] == "array"
    assert set(spec["items"]["properties"]) == {"province", "city", "district"}
    assert spec["items"]["additionalProperties"] is False


def test_the_two_region_conditions_say_opposite_things() -> None:
    """同一个形状（省市区数组）在 region_none 下方向相反。

    照 region_any 那句写，模型会把「不要新疆」理解成「只要新疆」，
    而 SQL 那边照做且不报错。
    """
    properties = _properties()

    assert "即通过" in properties["acceptable_regions_json"]["description"]
    assert "即出局" in properties["excluded_regions_json"]["description"]
    assert "即出局" not in properties["acceptable_regions_json"]["description"]


# -- 五个能力要求统一是布尔 -----------------------------------------------


def test_requirement_capability_fields_are_plain_booleans() -> None:
    """买家侧值域有两套（yes/no/unknown/likely 与 required/preferred/...），
    skill 不认强度 —— 强度由 agent 决定这次调用带不带这个条件。"""
    capability_columns = [
        field.column for field in SCREENING_FIELDS if field.operator == "requirement_capability"
    ]
    # 数量不写死：0817 把迁址/返投/团队留任移出初筛（标的侧全库 unknown，
    # 从未筛掉任何一家），这类进出会继续发生。要守的是「凡是这个算子的字段，
    # 在 schema 里都必须是 boolean」，不是「一共几个」。
    assert capability_columns
    for column in capability_columns:
        assert _properties()[column]["type"] == "boolean"


def test_unknown_is_never_an_acceptable_value() -> None:
    """缺失即出局，「可接受未知」会把缺失从后门放回来。"""
    properties = _properties()
    for field in SCREENING_FIELDS:
        if field.value_type == "enum":
            assert "unknown" not in properties[field.column]["enum"]
        elif field.value_type == "enum_list":
            assert "unknown" not in properties[field.column]["items"]["enum"]


def test_money_and_ratio_descriptions_carry_their_unit() -> None:
    properties = _properties()
    assert "20000000" in properties["min_net_profit_yuan"]["description"]
    # 负债率与股比两侧都存百分数（标的侧实测 9.55~75、60/80）。写「0-1 小数」
    # 会让模型把 60% 写成 0.6，条件一家也筛不到且不报错 —— 而 agent 看到的是
    # 「这批标的负债率普遍偏高」。
    assert "51% 写 51" in properties["desired_equity_ratio_min"]["description"]
    assert "51% 写 51" in properties["desired_equity_ratio_max"]["description"]
    # PE 是倍数不是比例：kind=ratio 一刀切会让模型把 15 倍写成 0.15。
    assert "15 倍写 15" in properties["max_pe"]["description"]


def test_a_ratio_field_without_a_declared_unit_fails_loudly(monkeypatch) -> None:
    """漏声明单位不能静默放行 —— 那正是上面三条描述曾经错掉的方式。"""
    import backend.app.services.screening_schema as module

    monkeypatch.setattr(module, "_RATIO_UNIT_HINTS", {})
    with pytest.raises(ValueError, match="没有声明单位"):
        module._build_fields()


def test_an_exclusion_condition_says_out_not_in() -> None:
    """同一个形状（闭集多选）在 not_overlap 下方向相反。

    照 overlap 那句写，模型会把「不接受涉诉」理解成「要涉诉的」。
    """
    description = _properties()["unacceptable_risk_flags_json"]["description"]

    assert "即出局" in description
    assert "已核查" in description
    assert "即通过" not in description


def test_the_two_flat_array_conditions_carry_the_shared_closed_set() -> None:
    """交易结构与重大风险和标的侧共用同一个闭集，不复制一份。"""
    properties = _properties()

    assert properties["transaction_types_json"]["items"]["enum"] == [
        "equity_transfer", "capital_increase", "asset_purchase", "merger", "other",
    ]
    # none 是「核查状态」不是「风险类型」，不进买家侧。
    assert properties["unacceptable_risk_flags_json"]["items"]["enum"] == [
        "litigation", "equity_frozen", "enforcement", "violation",
    ]


# -- 取值归一化 -----------------------------------------------------------


def _normalize(raw):
    return normalize_conditions(raw)


def test_unknown_field_is_reported_not_silently_dropped() -> None:
    conditions, ignored = _normalize({"drop_table": "seller_target", "min_net_profit_yuan": 1e7})

    assert conditions == {"min_net_profit_yuan": 1e7}
    assert any("drop_table" in message for message in ignored)


def test_a_retired_condition_is_reported_not_silently_dropped() -> None:
    """退役字段与从没存在过的字段一样，走「不是可筛字段，已忽略」。

    静默丢弃比报错危险：模型以为筛过了，实际那一条从来没生效。
    旧版提示词还会吐 industries_json，所以这条路必须响。
    """
    conditions, ignored = _normalize({"industries_json": ["制造与工业"], "max_pe": 15})

    assert conditions == {"max_pe": 15}
    assert any("industries_json" in message for message in ignored)


def test_false_capability_is_not_a_condition() -> None:
    """false = 不作要求。翻成 SQL 会变成「要求标的不具备该能力」，正好相反。"""
    conditions, _ = _normalize({"requires_control": False})

    assert conditions == {}


def test_true_capability_survives_in_any_spelling() -> None:
    for value in (True, "true", "yes", "required"):
        conditions, _ = _normalize({"requires_control": value})
        assert conditions == {"requires_control": True}


def test_enum_values_outside_the_closed_set_are_dropped() -> None:
    conditions, ignored = _normalize({"acceptable_listed_status_json": ["listed", "delisted"]})

    assert conditions == {"acceptable_listed_status_json": ["listed"]}
    assert ignored


def test_a_number_written_as_a_string_is_accepted() -> None:
    conditions, _ = _normalize({"min_net_profit_yuan": "10000000"})

    assert conditions == {"min_net_profit_yuan": 10000000.0}


def test_a_number_that_is_not_a_number_is_reported() -> None:
    conditions, ignored = _normalize({"max_pe": "便宜就行"})

    assert conditions == {}
    assert ignored


def test_short_province_names_are_canonicalized() -> None:
    """标的侧存的是 江苏省；模型写 江苏 而不归一化，SQL 一家也筛不到。"""
    conditions, _ = _normalize({"acceptable_regions_json": [{"province": "江苏", "city": "苏州市"}]})

    assert conditions == {"acceptable_regions_json": [{"province": "江苏省", "city": "苏州市"}]}


def test_an_empty_region_constraint_is_dropped() -> None:
    conditions, ignored = _normalize({"acceptable_regions_json": [{"province": ""}]})

    assert conditions == {}
    assert ignored
