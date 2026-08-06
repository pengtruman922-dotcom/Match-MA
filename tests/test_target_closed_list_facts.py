"""标的侧闭集多值列（重大风险 / 可接受交易结构）的归一化与写入边界。

这两列是问卷第 6、7 项的对手方。它们与既有枚举列的区别是**值是数组**，而三条
写入路径（新建解析、更新解析、业务更新兜底）原来只认标量枚举：整体做标量归一
会得到 "['litigation']" 这种字符串，一律落进 dropped_invalid_enum，字段看起来
建了却永远为空。

「未核查」与「已核查无风险」必须能分开表达——推荐一个股权已被冻结的标的和推荐
一个查过没问题的标的，对顾问是两件事。本轮不动打分器，但字段本身要先能表达。
"""

from __future__ import annotations

import pytest

from backend.app.jobs.handlers.common import (
    CLOSED_LIST_FIELD_VALUES,
    _SKIP_FIELD,
    _normalize_field_value,
)
from backend.app.jobs.handlers.seller_target_parse import (
    _normalize_seller_target_parse_changes,
)
from backend.app.registry.indicators import indicator_by_column, multi_value_enum_values
from backend.app.services.field_writer import FieldWriteError, _normalize_value

RISK = "major_risk_flags_json"
STRUCTURES = "acceptable_transaction_structures_json"


def _parse(fields: dict[str, object]) -> dict[str, object]:
    changes, _ = _normalize_seller_target_parse_changes({"fields": fields})
    return changes


def test_parse_keeps_recognised_risk_flags() -> None:
    assert _parse({RISK: ["litigation", "equity_frozen"]})[RISK] == ["litigation", "equity_frozen"]


def test_parse_drops_values_outside_the_dictionary() -> None:
    # 模型自创的风险类型不能落库：DB 的元素级 check 会把整条更新打回。
    changes = _parse({RISK: ["litigation", "环保处罚"]})
    assert changes[RISK] == ["litigation"]


def test_parse_skips_the_field_when_nothing_is_recognised() -> None:
    # 全部取值都不认识时不能写成空数组——空数组的含义是「未核查」，
    # 那是一个结论，不能由一次失败的解析凭空得出。
    changes, notes = _normalize_seller_target_parse_changes({"fields": {RISK: ["查无此项"]}})
    assert RISK not in changes
    assert f"dropped_{RISK}:no_recognised_values" in notes


def test_parse_accepts_the_checked_clean_state() -> None:
    assert _parse({RISK: ["none"]})[RISK] == ["none"]


def test_parse_normalises_transaction_structures() -> None:
    changes = _parse({STRUCTURES: ["equity_transfer", "capital_increase", "换股"]})
    assert changes[STRUCTURES] == ["equity_transfer", "capital_increase"]


def test_business_update_path_shares_the_same_normalisation() -> None:
    # 混合更新兜底节点走的是另一条归一化函数。两条路都要认数组，
    # 否则「走哪个节点决定字段能不能填上」。
    notes: list[str] = []
    value = _normalize_field_value(RISK, ["enforcement", "无此项"], CLOSED_LIST_FIELD_VALUES, notes)
    assert value == ["enforcement"]

    skipped = _normalize_field_value(RISK, ["无此项"], CLOSED_LIST_FIELD_VALUES, notes)
    assert skipped is _SKIP_FIELD


def test_closed_list_table_is_derived_from_the_registry() -> None:
    # 手写过一次就会漂移：加一个闭集列，没人会想起来去补那张表。
    assert set(multi_value_enum_values()) <= set(CLOSED_LIST_FIELD_VALUES)
    assert CLOSED_LIST_FIELD_VALUES[RISK] == {
        "litigation", "equity_frozen", "enforcement", "violation", "none",
    }


def test_writer_rejects_values_outside_the_dictionary() -> None:
    # 手动 PATCH 绕过了解析归一化，写入边界是最后一道。
    indicator = indicator_by_column("seller_target", RISK)
    with pytest.raises(FieldWriteError):
        _normalize_value(None, indicator, ["litigation", "bogus"])


def test_writer_deduplicates() -> None:
    indicator = indicator_by_column("seller_target", RISK)
    assert _normalize_value(None, indicator, ["litigation", "litigation"]) == ["litigation"]


def test_writer_keeps_the_unchecked_state_distinct_from_clean() -> None:
    indicator = indicator_by_column("seller_target", RISK)
    assert _normalize_value(None, indicator, []) == []
    assert _normalize_value(None, indicator, ["none"]) == ["none"]
