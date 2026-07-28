"""The canonical province vocabulary shared by writers and filters.

Location is stored as three independent columns so filtering can happen at
whatever level the user filled in. That only works if every writer spells a
province the same way: the cascading picker on the information page emits
`@vant/area-data` names (江苏省 / 上海市 / 新疆维吾尔自治区), but parse and
research write free text from an LLM, which happily produces 江苏 or 广东.

So province is normalized here, at the write boundary, against the same 34
names the frontend picker offers. City and district are deliberately *not*
validated: the county list runs to 3000+ entries and real targets sit in places
like 苏州工业园区 that are not administrative divisions at all. Losing that
detail would be worse than storing it unvalidated.

An unrecognised province is passed through unchanged rather than dropped —
a target that cannot be filtered by region is recoverable, a target whose
location was silently erased is not.
"""

from __future__ import annotations

from typing import Any

# Mirrors `areaList.province_list` in @vant/area-data (frontend picker + filter).
PROVINCES: tuple[str, ...] = (
    "北京市",
    "天津市",
    "河北省",
    "山西省",
    "内蒙古自治区",
    "辽宁省",
    "吉林省",
    "黑龙江省",
    "上海市",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "广西壮族自治区",
    "海南省",
    "重庆市",
    "四川省",
    "贵州省",
    "云南省",
    "西藏自治区",
    "陕西省",
    "甘肃省",
    "青海省",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "台湾省",
    "香港特别行政区",
    "澳门特别行政区",
)

# Longest first so 新疆维吾尔自治区 loses the whole suffix, not just 自治区.
_PROVINCE_SUFFIXES: tuple[str, ...] = (
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "特别行政区",
    "自治区",
    "省",
    "市",
)


def _short_name(province: str) -> str:
    for suffix in _PROVINCE_SUFFIXES:
        if province.endswith(suffix) and len(province) > len(suffix):
            return province[: -len(suffix)]
    return province


_PROVINCE_ALIASES: dict[str, str] = {
    **{province: province for province in PROVINCES},
    **{_short_name(province): province for province in PROVINCES},
}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def normalize_province(value: Any) -> str | None:
    """Canonical province name, or the trimmed original when unrecognised."""
    text_value = _clean(value)
    if text_value is None:
        return None
    return _PROVINCE_ALIASES.get(text_value, text_value)


def normalize_city(value: Any) -> str | None:
    return _clean(value)


def normalize_district(value: Any) -> str | None:
    return _clean(value)


NORMALIZERS = {
    "location_province": normalize_province,
    "location_city": normalize_city,
    "location_district": normalize_district,
}
