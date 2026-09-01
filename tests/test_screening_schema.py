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
        for indicator in indicators_for("buyer_intent_scenario")
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


def test_region_takes_three_optional_levels() -> None:
    spec = _properties()["required_regions_json"]

    assert spec["type"] == "array"
    assert set(spec["items"]["properties"]) == {"province", "city", "district"}
    assert spec["items"]["additionalProperties"] is False


def test_the_region_condition_says_in_not_out() -> None:
    """「要求地区」是命中即通过。

    0901 之前还有一个同形状、方向相反的「排除地区」（region_none），
    照 region_any 那句描述写会让模型把「不要新疆」理解成「只要新疆」，
    而 SQL 那边照做且不报错。排除地区本轮退役（实测真淘汰 0 次），
    这条守的是留下来的这一个方向没写反。
    """
    description = _properties()["required_regions_json"]["description"]

    assert "即通过" in description
    assert "即出局" not in description


# -- 五个能力要求统一是布尔 -----------------------------------------------


def test_the_retired_conditions_are_gone_from_the_schema() -> None:
    """0901 方案化退役的六个条件不能还在模型看得见的 schema 里。

    留一个在 schema 里的后果不是报错，是 agent 填了它、SQL 拿它去筛一个
    没人再写入的列 —— 于是候选池恒空，而错误信息一句都没有。

    控股要求与并表要求是买家侧用得最多的两个字段（21 条和 18 条需求填了），
    实测 48x71 全量对判**真淘汰 0 次**，只在标的 can_control 没录时开火。
    """
    properties = _properties()
    for column in (
        "requires_control",
        "requires_consolidation",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "transaction_types_json",
        "unacceptable_risk_flags_json",
        "excluded_regions_json",
        "acceptable_regions_json",
    ):
        assert column not in properties, column


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
    assert "20000000" in properties["min_revenue_yuan"]["description"]
    # PE 是倍数不是比例：kind=ratio 一刀切会让模型把 15 倍写成 0.15，
    # 条件一家也筛不到且不报错 —— 而 agent 看到的是「这批标的 PE 普遍偏高」。
    # 0901 之后 max_pe 是唯一的 ratio 条件（负债率与股比随本轮退役），
    # 所以单位声明那条守卫比以前更要紧：它现在只剩一个用户。
    assert "15 倍写 15" in properties["max_pe"]["description"]


def test_a_ratio_field_without_a_declared_unit_fails_loudly(monkeypatch) -> None:
    """漏声明单位不能静默放行 —— 那正是上面三条描述曾经错掉的方式。"""
    import backend.app.services.screening_schema as module

    monkeypatch.setattr(module, "_RATIO_UNIT_HINTS", {})
    with pytest.raises(ValueError, match="没有声明单位"):
        module._build_fields()


def test_the_closed_set_conditions_share_the_registry_declaration() -> None:
    """闭集不在这里复制一份 —— 复制的那份会在枚举加值时静默过期。

    0901 之后唯一的闭集条件是上市状态。unknown 不进买家侧：
    「可接受未知上市状态」讲不通，而它一旦混进来就等于这个条件失效。
    """
    assert _properties()["acceptable_listed_status_json"]["items"]["enum"] == [
        "listed", "unlisted", "pre_ipo",
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


def test_a_retired_condition_key_is_reported_not_silently_dropped() -> None:
    """退役条件被塞进来时要如实报告，不能静默吃掉。

    静默吃掉的后果是 agent 以为条件生效了，实际上筛的是另一组 ——
    它接着会去解释一个不存在的召回结果。
    """
    conditions, ignored = _normalize({"requires_control": True, "min_revenue_yuan": 1})

    assert conditions == {"min_revenue_yuan": 1.0}
    assert any("requires_control" in item for item in ignored)


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
    conditions, _ = _normalize({"required_regions_json": [{"province": "江苏", "city": "苏州市"}]})

    assert conditions == {"required_regions_json": [{"province": "江苏省", "city": "苏州市"}]}


def test_an_empty_region_constraint_is_dropped() -> None:
    conditions, ignored = _normalize({"required_regions_json": [{"province": ""}]})

    assert conditions == {}
    assert ignored
