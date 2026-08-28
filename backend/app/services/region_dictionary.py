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


# 城市群与大区 → 省份。
#
# 顾问说地域时用的几乎都是这套词，而不是省名：生产 50 条需求里只有文本、没能结构化的
# 那 26 条，提到长三角 7 次、华东/华中/西南各 2 次、大湾区/粤港澳/珠三角/成渝/华北
# 各 1 次。契约只收省/市/区，于是 agent 要么放弃（那 26 条），要么硬猜一个省
# —— 后者更糟：「优选长三角」被写成「广东省」，初筛会把长三角的标的全挡掉。
#
# 展开成省份而不是新增一层：初筛闸门按省比对（`region_any`），多一层就要改闸门，
# 而闸门有五处独立实现。展开之后「长三角」和「上海市、江苏省、浙江省、安徽省」
# 在筛选里是同一件事。
#
# 口径按国家统计局的六大区 + 通行的城市群定义；成渝、京津冀这类跨省城市群按其
# 覆盖的省级行政区给全，不做地市级细分 —— 细分要靠 city 字段，那一层不做校验。
REGION_GROUPS: dict[str, tuple[str, ...]] = {
    "长三角": ("上海市", "江苏省", "浙江省", "安徽省"),
    "长江三角洲": ("上海市", "江苏省", "浙江省", "安徽省"),
    "珠三角": ("广东省",),
    "珠江三角洲": ("广东省",),
    "大湾区": ("广东省", "香港特别行政区", "澳门特别行政区"),
    "粤港澳": ("广东省", "香港特别行政区", "澳门特别行政区"),
    "粤港澳大湾区": ("广东省", "香港特别行政区", "澳门特别行政区"),
    "京津冀": ("北京市", "天津市", "河北省"),
    "成渝": ("四川省", "重庆市"),
    "成渝双城经济圈": ("四川省", "重庆市"),
    "环渤海": ("北京市", "天津市", "河北省", "辽宁省", "山东省"),
    "华东": ("上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省"),
    "华南": ("广东省", "广西壮族自治区", "海南省"),
    "华北": ("北京市", "天津市", "河北省", "山西省", "内蒙古自治区"),
    "华中": ("河南省", "湖北省", "湖南省"),
    "西南": ("重庆市", "四川省", "贵州省", "云南省", "西藏自治区"),
    "西北": ("陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区"),
    "东北": ("辽宁省", "吉林省", "黑龙江省"),
}

# 「哪儿都行」的各种说法。它们不是一个地域约束，而是**没有**地域约束 ——
# 初筛里两者行为相同（不加省份条件），所以这里丢掉是对的，不是信息损失：
# 原话仍然留在 `region_scope_summary` 里给人看。
UNRESTRICTED_TERMS: frozenset[str] = frozenset(
    {"全国", "全国范围", "不限", "不限地域", "无地域限制", "无限制", "不限注册地", "国内", "境内", "全球", "不限区域"}
)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def expand_region_group(value: Any) -> tuple[str, ...]:
    """城市群/大区 → 它覆盖的省份；不是这类说法就返回空。

    **扫整串而不是只看开头**：真实数据里一格常常写着「长三角、珠三角区域」
    （生产里就有），只按前缀匹配会把珠三角整个丢掉，而丢掉的地区在筛选里
    表现为「这些标的进不来」，界面上看不出来。

    最长优先并吃掉已匹配的片段：「粤港澳大湾区」要先于「粤港澳」和「大湾区」命中，
    否则同一段文字会被拆着算两次（结果虽然相同，但换个词典就不一定了）。
    """
    text_value = _clean(value)
    if not text_value:
        return ()
    if text_value in REGION_GROUPS:
        return REGION_GROUPS[text_value]
    provinces: list[str] = []
    remaining = text_value
    for name in sorted(REGION_GROUPS, key=len, reverse=True):
        if name not in remaining:
            continue
        remaining = remaining.replace(name, "、")
        for province in REGION_GROUPS[name]:
            if province not in provinces:
                provinces.append(province)
    return tuple(provinces)


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


def normalize_buyer_region_constraints(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate normalized buyer regions against the shared province vocabulary.

    LLM expansion happens before this boundary. Code accepts canonical provinces
    and isolates an unrecognised item for review without disabling valid items.
    """
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    constraints: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    effect_aliases = {
        "hard": "required",
        "required": "required",
        "must": "required",
        "soft": "preferred",
        "preferred": "preferred",
        "prefer": "preferred",
        "exclude": "excluded",
        "excluded": "excluded",
    }
    for item in values:
        # 裸字符串数组（`["四川省","云南省"]`）也认：生产里躺着这种形状，
        # 直接 continue 会把整条地域要求静默丢掉，而它本来是能救的。
        if isinstance(item, str):
            item = {"province": item}
        if not isinstance(item, dict):
            continue
        raw_province = _clean(item.get("province") or item.get("province_name"))
        # `raw_text` 是模型偶尔用的另一个键名。省份为空时拿它兜一下，
        # 否则「长三角、珠三角区域」这种整条要求会连同它的城市群一起丢掉。
        if not raw_province:
            raw_province = _clean(item.get("raw_text") or item.get("region") or item.get("area"))
        if raw_province in UNRESTRICTED_TERMS:
            # 「全国/不限」不是一个约束，是没有约束 —— 初筛里两者行为相同。
            # 原话留在 region_scope_summary 里，这里丢掉不算信息损失。
            continue
        # 城市群先展开：顾问说的几乎都是「长三角」而不是四个省名，
        # 不展开的话它要么进 pending、要么被硬猜成一个省。
        group = expand_region_group(raw_province)
        if group:
            effect = effect_aliases.get(
                str(item.get("effect") or item.get("constraint_type") or "preferred").strip().lower(),
                "preferred",
            )
            for member in group:
                key = (member, "", "", effect)
                if key not in seen:
                    seen.add(key)
                    constraints.append({"province": member, "effect": effect})
            continue
        province = normalize_province(raw_province)
        city = normalize_city(item.get("city") or item.get("city_name"))
        district = normalize_district(item.get("district") or item.get("county") or item.get("district_name"))
        effect = effect_aliases.get(
            str(item.get("effect") or item.get("constraint_type") or "preferred").strip().lower(),
            "preferred",
        )
        proposed = {
            "province": province,
            **({"city": city} if city else {}),
            **({"district": district} if district else {}),
            "effect": effect,
        }
        if not province or province not in PROVINCES:
            pending.append(
                {
                    "field": "region_constraints_json",
                    "uncertain_part": "taxonomy_mapping",
                    "proposed_value": proposed,
                    "reason": f"地区“{raw_province or city or district or '空值'}”未规范化到标准省份",
                    **({"evidence": str(item.get("evidence"))[:1000]} if item.get("evidence") else {}),
                }
            )
            continue
        key = (province, city or "", district or "", effect)
        if key not in seen:
            seen.add(key)
            constraints.append(proposed)
    return constraints, pending


NORMALIZERS = {
    "location_province": normalize_province,
    "location_city": normalize_city,
    "location_district": normalize_district,
}
