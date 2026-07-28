"""Province normalization at the write boundary (施工单 0727 · T1/T3).

The 2026-07-27 production audit found location data already canonical
(江苏省/北京市/上海市…, matching `@vant/area-data`). That is luck, not a
guarantee: the information page uses the cascading picker, but parse and
research write location text with no validation at all. Cascading *filters*
only work if every writer agrees on the same spelling, so the writer — not the
migration — is where this has to hold.
"""

import pytest

from backend.app.services.region_dictionary import (
    PROVINCES,
    normalize_city,
    normalize_district,
    normalize_province,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("广东", "广东省"),
        ("江苏", "江苏省"),
        ("上海", "上海市"),
        ("北京", "北京市"),
        ("重庆", "重庆市"),
        ("新疆", "新疆维吾尔自治区"),
        ("内蒙古", "内蒙古自治区"),
        ("广西", "广西壮族自治区"),
        ("西藏", "西藏自治区"),
        ("宁夏", "宁夏回族自治区"),
        ("香港", "香港特别行政区"),
    ],
)
def test_short_province_name_gains_canonical_suffix(raw: str, expected: str) -> None:
    assert normalize_province(raw) == expected


@pytest.mark.parametrize("name", ["江苏省", "上海市", "新疆维吾尔自治区", "澳门特别行政区"])
def test_canonical_province_is_unchanged(name: str) -> None:
    assert normalize_province(name) == name


def test_whitespace_is_trimmed() -> None:
    assert normalize_province("  广东省 ") == "广东省"
    assert normalize_city(" 深圳市 ") == "深圳市"
    assert normalize_district("\t余杭区\n") == "余杭区"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_becomes_none(value: str | None) -> None:
    assert normalize_province(value) is None
    assert normalize_city(value) is None
    assert normalize_district(value) is None


def test_unknown_province_passes_through_instead_of_being_dropped() -> None:
    """未知省名保留原文：宁可筛不到，也不能静默丢失事实。"""
    assert normalize_province("某个不存在的省") == "某个不存在的省"


def test_city_and_district_are_trim_only() -> None:
    # 市/区不做字典校验：area-data 有 3000+ 区县，且解析常给出园区一类的非行政区名。
    assert normalize_city("苏州工业园区") == "苏州工业园区"
    assert normalize_district("工业园区") == "工业园区"


def test_province_dictionary_is_complete() -> None:
    assert len(PROVINCES) == 34
    for name in ("江苏省", "北京市", "新疆维吾尔自治区", "台湾省", "香港特别行政区"):
        assert name in PROVINCES


def test_field_writer_normalizes_province_on_write() -> None:
    """写入通道是唯一的归一化点——解析、调研、手动编辑都要经过它。"""
    from backend.app.registry.indicators import indicator_by_column
    from backend.app.services.field_writer import _normalize_value

    indicator = indicator_by_column("seller_target", "location_province")
    assert _normalize_value(None, indicator, "广东") == "广东省"
    assert _normalize_value(None, indicator, "江苏省") == "江苏省"
