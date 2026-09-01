"""初筛条件的字段清单与 JSON Schema —— 全部由指标注册表生成，一行都不手写。

手写的 schema 与注册表脱钩之后必然漂移：改造前的 `_FILTER_PROPERTIES` 只开放了
12 个字段（引擎实际支持 26 个），行业名又没有闭集约束，模型写错一个行业名会静默
清空整个候选池。这里的每个 property 都从 `indicators_for("buyer_intent_scenario")` 里
`screening=True` 的指标派生，行业闭集在运行时从 `industry_taxonomy` 注入 —— 模型
填不出字典外的行业名，那条失败路径从根上消失。

SQL 生成（`screening_sql.py`）与这里共用同一份 `ScreeningField`，所以「schema 里
有、SQL 不认」这种半截接线不可能发生。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.registry.indicators import indicator_by_column, indicators_for
from backend.app.services.region_dictionary import (
    normalize_city,
    normalize_district,
    normalize_province,
)

# 「哪些条件进初筛」**只由注册表的 screening 决定**，这里不另开排除名单。
# 曾经有过一份（min_net_margin / max_ps 两个口径坏掉的条件写死在这儿），结果是
# 同一个判断落在两处：注册表哪天把 max_ps 修好并置 screening=True，这份硬编码
# 会静默把它继续挡在门外，而没有任何东西会报错。0817 起两个都由注册表自己
# screening=False，理由写在注册表那两行的注释里。

# 「缺失即出局」是初筛的地基，所以 unknown 不能作为可接受取值下发：买家勾了
# 「可接受未知」等于把缺失又放回来，与 excluded_by_condition 的缺失统计直接打架。
UNKNOWN_CODE = "unknown"

# requirement_capability 的通过取值。买家侧的强度（required / preferred）由
# agent 用「这次调用带不带这个条件」表达，skill 不认强度。
CAPABILITY_VALUES: tuple[str, ...] = ("yes", "likely")

# 行业三件套（industries_json / industry_l2_json / excluded_industries_json）
# 2026-08-28 退出初筛：买家需求侧的行业字典下线，业务匹配整段交给 LLM 读文本。
# 跨侧匹配需要共享词表，那是行业字典存在的唯一理由 —— 需求侧放弃字典，
# 就等于放弃行业这一维的 SQL 硬筛。所以这里连 `industry_*` 的取值类型
# 一起删掉了：留着一个没有字段会走到的分支，只会让下一个人以为它还能用。
#
# 代价是**正向初筛不再有行业条件**，一条只写了「最低营收 1 亿」的需求会召回
# 接近全库。补偿在 `screen_targets(business_scan=True)`：一次把命中集的业务摘要
# 全量吐给主 Agent 做首轮语义筛。见方案 0828 §十。
_REGION_COLUMNS: frozenset[str] = frozenset({"required_regions_json"})

# kind=ratio 混着两种量纲，而注册表这一层表达不了单位：负债率与股比**两侧都存
# 百分数**（60% 存 60 —— 标的侧实测 current_debt_ratio 9.55~75、transfer_ratio
# 60/80，买家侧同口径，见方案 0817 §3.3），PE 是倍数。
#
# description 是模型填对值的唯一依据，按 kind 一刀切写「0-1 小数」的后果是模型
# 把 60% 写成 0.6，而库里存的是 60：条件一家也筛不到，不报错，agent 只会看到
# 「这批标的负债率普遍偏高」——错得最难查的那个方向。
#
# 因此每个 ratio 字段都必须在这里显式声明单位，漏一个就在构建 schema 时报错。
_RATIO_UNIT_HINTS: dict[str, str] = {
    "max_pe": "倍数，15 倍写 15",
    "max_debt_ratio": "百分数，60% 写 60（不是 0.6）",
    "desired_equity_ratio_min": "百分数，51% 写 51（不是 0.51）",
    "desired_equity_ratio_max": "百分数，51% 写 51（不是 0.51）",
}
_YUAN_HINT = "单位元，2000 万写 20000000"


@dataclass(frozen=True)
class ScreeningField:
    """一个可筛条件：模型看到的形状 + SQL 需要的对手方。"""

    column: str  # buyer_intent_scenario 列名 = 条件的键
    label: str
    operator: str  # gte | lte | in | eq | overlap | not_overlap | region_any | requirement_capability
    target_column: str  # 注册表原样声明的标的侧对手方
    value_type: str  # number | boolean | enum | enum_list | industry_l1 | industry_l2 | industry_any | region_list
    enum_values: tuple[str, ...] = ()
    unit_hint: str = ""
    # 标的没录这个数时出局还是通过。见注册表 Indicator.missing_policy ——
    # 这不是「必须/优先」的替代品，那个东西 2026-09-01 删掉了。
    missing_policy: str = "exclude"


def _value_type(column: str, kind: str, operator: str) -> str:
    if column in _REGION_COLUMNS:
        return "region_list"
    if operator == "requirement_capability":
        return "boolean"
    if kind in {"yuan", "ratio"}:
        return "number"
    if kind == "json":
        return "enum_list"
    if kind == "enum":
        return "enum"
    # 注册表加了新形状而这里没接：宁可启动即炸，也不要生成一个模型能填、
    # SQL 不认的字段。
    raise ValueError(f"screening field {column!r} has no schema mapping (kind={kind}, operator={operator})")


def _build_fields() -> tuple[ScreeningField, ...]:
    fields: list[ScreeningField] = []
    for indicator in indicators_for("buyer_intent_scenario"):
        if not indicator.screening:
            continue
        if not indicator.operator or not indicator.target_column:
            # screening=True 却没声明比较契约的字段进不来：没有对手方就生成不出 SQL。
            continue
        value_type = _value_type(indicator.column, indicator.kind, indicator.operator)
        enum_values: tuple[str, ...] = ()
        if value_type in {"enum", "enum_list"}:
            enum_values = tuple(
                code for code, _ in (indicator.enum_options or ()) if code != UNKNOWN_CODE
            )
        unit_hint = ""
        if indicator.kind == "yuan":
            unit_hint = _YUAN_HINT
        elif indicator.kind == "ratio":
            try:
                unit_hint = _RATIO_UNIT_HINTS[indicator.column]
            except KeyError:
                raise ValueError(
                    f"ratio 条件 {indicator.column!r} 没有声明单位。"
                    "百分数与分数在 SQL 里都不报错，只会让条件恒空或恒真，"
                    "所以必须在 _RATIO_UNIT_HINTS 里写清楚。"
                ) from None
        fields.append(
            ScreeningField(
                column=indicator.column,
                label=indicator.label,
                operator=indicator.operator,
                target_column=indicator.target_column,
                value_type=value_type,
                missing_policy=indicator.missing_policy,
                enum_values=enum_values,
                unit_hint=unit_hint,
            )
        )
    return tuple(fields)


SCREENING_FIELDS: tuple[ScreeningField, ...] = _build_fields()
SCREENING_FIELDS_BY_COLUMN: dict[str, ScreeningField] = {
    field.column: field for field in SCREENING_FIELDS
}


# -- JSON Schema ---------------------------------------------------------

_DIRECTION_TEXT = {"gte": "不低于该值", "lte": "不高于该值"}


def _property_for(field: ScreeningField) -> dict[str, Any]:
    if field.value_type == "number":
        direction = _DIRECTION_TEXT.get(field.operator, "")
        parts = [f"{field.label}：标的的{_target_label(field)}{direction}。"]
        if field.unit_hint:
            parts.append(field.unit_hint + "。")
        return {"type": "number", "description": "".join(parts)}
    if field.value_type == "boolean":
        return {
            "type": "boolean",
            "description": (
                f"{field.label}：填 true 表示本次要求标的具备该能力"
                f"（标的侧{_target_label(field)}为「是」或「可能」才通过）。"
                "不作要求就不要填这个字段，填 false 等同不填。"
            ),
        }
    if field.value_type == "enum":
        return {
            "type": "string",
            "enum": list(field.enum_values),
            "description": f"{field.label}：标的的{_target_label(field)}必须等于该值。",
        }
    if field.value_type == "enum_list":
        if field.operator == "not_overlap":
            # 方向必须写反过来：同一个形状（闭集多选）在 not_overlap 下是「命中即
            # 出局」。照 overlap 那句写会让模型把「不接受涉诉」理解成「要涉诉的」。
            return {
                "type": "array",
                "items": {"type": "string", "enum": list(field.enum_values)},
                "description": (
                    f"{field.label}：标的的{_target_label(field)}命中其中任一项即出局。"
                    f"本条同时要求标的**已核查过**{_target_label(field)}——没查过的一并出局，"
                    "因为「没查出风险」和「查过没有风险」不是一回事。"
                ),
            }
        return {
            "type": "array",
            "items": {"type": "string", "enum": list(field.enum_values)},
            "description": f"{field.label}：标的的{_target_label(field)}命中其中之一即通过。",
        }
    if field.value_type == "region_list":
        # 方向由算子决定，描述必须跟着反过来 —— 同一个形状（省市区数组）在
        # region_none 下是「命中即出局」。照 region_any 那句写会让模型把
        # 「不要新疆」理解成「只要新疆」，而 SQL 那边照做且不报错。
        tail = (
            f"{field.label}：数组，每项只填到你确定的层级，任一项命中即出局。"
            if field.operator == "region_none"
            else f"{field.label}：数组，每项只填到你确定的层级，任一项命中即通过。"
        )
        return {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "province": {"type": "string", "description": "省份全称，如 江苏省 / 上海市。"},
                    "city": {"type": "string", "description": "地级市，如 苏州市。不确定就不填。"},
                    "district": {"type": "string", "description": "区县，如 吴中区。不确定就不填。"},
                },
                "additionalProperties": False,
            },
            "description": tail + "例如只说「江苏」就填 [{\"province\": \"江苏省\"}]。",
        }
    raise ValueError(f"unmapped value_type {field.value_type!r}")


def _target_label(field: ScreeningField) -> str:
    """标的侧对手方的中文名，让 description 说清楚比的是标的的哪个字段。"""
    column = field.target_column.split(".")[0].split(",")[0]
    try:
        return indicator_by_column("seller_target", column).label
    except KeyError:
        return column


def build_conditions_properties() -> dict[str, dict[str, Any]]:
    """可筛字段的 JSON Schema properties，全部由注册表的 screening 派生。

    0828 起不再需要注入行业闭集：需求侧的行业条件退役之后，这里已经没有任何
    运行时词表要拼进来，闭集全都在注册表的 enum_options 里。
    """
    return {field.column: _property_for(field) for field in SCREENING_FIELDS}


# -- 取值归一化 -----------------------------------------------------------

_TRUE_TOKENS = {"true", "yes", "1", "是", "required", "preferred"}
_FALSE_TOKENS = {"false", "no", "0", "否", "not_required"}


def _clean_terms(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        term = str(value).strip() if value is not None else ""
        if term and term not in cleaned:
            cleaned.append(term)
    return cleaned


def _normalize_region(values: Any) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(values, list):
        return [], []
    constraints: list[dict[str, str]] = []
    problems: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            problems.append(f"地区条件不是对象：{str(value)[:30]}")
            continue
        constraint: dict[str, str] = {}
        province = normalize_province(value.get("province"))
        city = normalize_city(value.get("city"))
        district = normalize_district(value.get("district"))
        if province:
            constraint["province"] = province
        if city:
            constraint["city"] = city
        if district:
            constraint["district"] = district
        if not constraint:
            problems.append("地区条件三个层级都为空，已忽略")
            continue
        if constraint not in constraints:
            constraints.append(constraint)
    return constraints, problems


def normalize_conditions(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """把模型给的条件收敛成 SQL 能直接用的取值。

    第二个返回值是「被忽略了什么」，会原样回给模型 —— 静默丢弃一个条件比报错更
    危险：模型以为筛过了，实际上那一条从来没生效。
    """
    if not isinstance(raw, dict):
        return {}, [] if raw in (None, {}) else ["conditions 不是对象，已按无条件处理"]

    conditions: dict[str, Any] = {}
    ignored: list[str] = []
    for key, value in raw.items():
        field = SCREENING_FIELDS_BY_COLUMN.get(str(key))
        if field is None:
            ignored.append(f"{key}：不是可筛字段，已忽略")
            continue
        if value is None:
            continue
        coerced, problem = _coerce(field, value)
        if problem:
            ignored.append(problem)
        if coerced is not None:
            conditions[field.column] = coerced
    return conditions, ignored


def _coerce(field: ScreeningField, value: Any) -> tuple[Any, str | None]:
    if field.value_type == "number":
        if isinstance(value, bool):
            return None, f"{field.label}：期望数字，收到布尔值，已忽略"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None, f"{field.label}：{value!r} 不是数字，已忽略"
        if number != number or number in (float("inf"), float("-inf")):
            return None, f"{field.label}：数值非法，已忽略"
        return number, None
    if field.value_type == "boolean":
        if isinstance(value, bool):
            flag = value
        else:
            token = str(value).strip().lower()
            if token in _TRUE_TOKENS:
                flag = True
            elif token in _FALSE_TOKENS:
                flag = False
            else:
                return None, f"{field.label}：{value!r} 不是布尔值，已忽略"
        if not flag:
            # false = 不作要求。翻成 SQL 会变成「要求标的不具备该能力」，与用户
            # 的意思正好相反，所以直接不生成条件。
            return None, None
        return True, None
    if field.value_type == "enum":
        token = str(value).strip().lower()
        if token not in field.enum_values:
            return None, f"{field.label}：{value!r} 不在取值范围 {list(field.enum_values)}，已忽略"
        return token, None
    if field.value_type == "enum_list":
        terms = [term.lower() for term in _clean_terms(value)]
        kept = [term for term in terms if term in field.enum_values]
        dropped = [term for term in terms if term not in field.enum_values]
        if not kept:
            return None, f"{field.label}：没有一个取值在范围 {list(field.enum_values)} 内，整条已忽略"
        if dropped:
            return kept, f"{field.label}：{dropped} 不在取值范围内，已剔除"
        return kept, None
    if field.value_type == "region_list":
        constraints, problems = _normalize_region(value)
        if not constraints:
            return None, f"{field.label}：没有解析出有效地区，整条已忽略"
        return constraints, "；".join(problems) if problems else None
    return None, f"{field.label}：无法处理的取值类型"
