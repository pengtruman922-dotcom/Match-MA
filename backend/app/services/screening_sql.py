"""初筛 skill 的执行体：条件 → SQL 硬筛 + 逐条件淘汰拆分。

设计的一句话版本：**LLM 只做它擅长的（理解语言、判断定性），比较与匹配全部交给
SQL。** 所以这里没有打分、没有软硬之分、没有 OR —— 一次调用就是一组 AND 条件，
条件字段为空的标的一律出局，剩下的幸存者在条件上完全等价。

三条容易被改回去的规则，写在最前面：

1. **缺失即出局，所以模板不带 `is null or`。** 这是 agent「减一个条件就能多召回」
   这套放宽策略成立的前提；一旦缺失也算通过，去掉条件与不去掉条件的命中数就一样了。
2. **`unknown` 不是 null。** `can_control` / `listed_status` 等列在 DDL 里是
   `not null default 'unknown'`，`col is null` 永远判不到它们。判「字段缺失」时
   两者必须等价，统一走 `_missing_sql`。
3. **`excluded_by_condition` 是 marginal 语义**（去掉这一条能多召回几家），不是
   independent（这一条单独筛掉几家）。后者会重复计数，对放宽决策毫无指导意义。

排序键是标的级别 A-D。原来这里写着「与 `recommendation_flow` 的规则打分链路故意
不同」——那条路有匹配分数，级别不该干扰分数。阶段五 5B 已把整个打分链路删掉，
现在**只剩这一条路**：硬筛之后幸存者等价，没有分数可排，A-D 就是排序键。
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column
from backend.app.services.industry_taxonomy import list_l1_terms, list_l2_terms
from backend.app.services.screening_schema import (
    CAPABILITY_VALUES,
    SCREENING_FIELDS,
    SCREENING_FIELDS_BY_COLUMN,
    UNKNOWN_CODE,
    ScreeningField,
    normalize_conditions,
)

MAX_SCREENING_LIMIT = 20
DEFAULT_SCREENING_LIMIT = 20

# 准入闸门：E 不进推荐，A-D 进。永远生效，不由买家指定，与
# `recommendation_flow` / `search_docs` 的口径必须一字不差。
_GATE_SQL = """st.team_id = :team_id
      and st.workspace_id = :workspace_id
      and st.deleted_at is null
      and st.target_grade <> 'E'"""

# 摘要与 facts 需要的列。条件涉及的对手方列由字段声明推出来，所以新增一个可筛
# 字段时摘要会自动带上它的值，不需要再改这里。
_BASE_ROW_COLUMNS: tuple[str, ...] = (
    "id",
    "target_name",
    "target_grade",
    "updated_at",
    "industry_pairs_json",
    "industry_l1",
    "industry_l2",
    "location_province",
    "location_city",
    "location_district",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_debt_ratio",
    "pe_ratio",
    "valuation_yuan",
    "market_cap_yuan",
    "asking_price_yuan",
    "transfer_ratio_min",
    "transfer_ratio_max",
    "listed_status",
    "cash_flow_status",
    "profitability_status",
    "can_control",
    "can_consolidate",
    "management_retention_possible",
)

_PLAIN_OPERATORS = frozenset({"gte", "lte", "in", "eq", "requirement_capability"})


def _row_columns() -> tuple[str, ...]:
    columns = list(_BASE_ROW_COLUMNS)
    for field in SCREENING_FIELDS:
        if field.operator in _PLAIN_OPERATORS and field.target_column not in columns:
            columns.append(field.target_column)
    return tuple(columns)


ROW_COLUMNS: tuple[str, ...] = _row_columns()


@dataclass(frozen=True)
class Clause:
    """一个条件编译出来的两段 SQL：命中判定，以及「这个字段是不是没录」。"""

    field: ScreeningField
    value: Any
    sql: str
    missing_sql: str
    params: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass
class ScreeningResult:
    conditions: dict[str, Any]
    matched: int
    excluded_by_condition: dict[str, dict[str, int]]
    rows: list[dict[str, Any]]
    ignored: list[str]
    limit: int
    offset: int
    count_only: bool

    @property
    def returned_count(self) -> int:
        return len(self.rows)

    def as_tool_result(self) -> dict[str, Any]:
        """回给模型的 JSON。字段值一律从库里原样取出，格式化在写作环节统一做。"""
        payload: dict[str, Any] = {
            "conditions": self.conditions,
            "matched": self.matched,
            "returned_count": self.returned_count,
            "excluded_by_condition": self.excluded_by_condition,
        }
        if self.offset:
            payload["offset"] = self.offset
        if not self.count_only:
            payload["returned"] = [_row_digest(row, self.conditions) for row in self.rows]
            remaining = self.matched - self.offset - self.returned_count
            if remaining > 0:
                # 不做字符截断：截断一个 JSON 只会得到半个 JSON，模型解析失败
                # 还不知道为什么。
                payload["note"] = f"另有 {remaining} 家未返回，请收窄条件或使用 offset 翻页。"
        if self.ignored:
            payload["ignored_conditions"] = self.ignored
        return payload


# -- 算子 → SQL ----------------------------------------------------------


def _missing_sql(column: str) -> str:
    """「这个字段没录」的判定。

    带 unknown 档的枚举列必须与 null 等价 —— 这些列在 DDL 里是
    `not null default 'unknown'`，只判 is null 会把整批未录入的标的算成
    「确实不达标」，agent 就会去放宽一个根本不该放宽的条件。
    """
    try:
        indicator = indicator_by_column("seller_target", column)
    except KeyError:
        return f"st.{column} is null"
    codes = {code for code, _ in (indicator.enum_options or ())}
    if UNKNOWN_CODE in codes and not indicator.multi_value:
        return f"(st.{column} is null or st.{column} = '{UNKNOWN_CODE}')"
    if indicator.multi_value:
        # 闭集多值列同理：DDL 是 `not null default '[]'`，空数组就是「没录」。
        # major_risk_flags_json 上这一条尤其要紧 —— 空数组表示「未核查」，
        # 而它与 ["none"]（已核查无风险）是两个结论，不能混。
        return f"(st.{column} is null or jsonb_array_length(st.{column}) = 0)"
    if indicator.kind == "text":
        return f"coalesce(st.{column}, '') = ''"
    return f"st.{column} is null"


# jsonb 展开前的防御性收敛：列里存了非数组时 jsonb_array_elements 会在运行时报错，
# 一条脏数据就能把整次筛选打成 500（同 buyer_intents.py 的 _JSONB_ARRAY）。
_INDUSTRY_PAIRS = (
    "case when jsonb_typeof(st.industry_pairs_json) = 'array'"
    " then st.industry_pairs_json else '[]'::jsonb end"
)


def _industry_exists(json_key: str, param: str, index: int) -> str:
    return (
        f"exists(select 1 from jsonb_array_elements({_INDUSTRY_PAIRS}) pair_{index}"
        f" where pair_{index} ->> '{json_key}' = any(:{param}))"
    )


def _flat_array(column: str) -> str:
    return (
        f"case when jsonb_typeof(st.{column}) = 'array'"
        f" then st.{column} else '[]'::jsonb end"
    )


def _flat_array_exists(column: str, param: str, index: int) -> str:
    """扁平字符串数组（重大风险、可接受交易结构）的重合判定。

    与行业那两个函数的区别只在形状：行业存的是 {l1, l2} 对象数组，这里存的是
    字符串数组，所以走 jsonb_array_elements_text 而不是取键。
    """
    return (
        f"exists(select 1 from jsonb_array_elements_text({_flat_array(column)}) flat_{index}"
        f" where flat_{index} = any(:{param}))"
    )


def _industry_missing(index: int, keys: tuple[str, ...]) -> str:
    checks = " or ".join(f"coalesce(pair_m{index} ->> '{key}', '') <> ''" for key in keys)
    return (
        f"not exists(select 1 from jsonb_array_elements({_INDUSTRY_PAIRS}) pair_m{index}"
        f" where {checks})"
    )


def build_clause(field: ScreeningField, value: Any, index: int) -> Clause:
    """一个条件 → (命中 SQL, 缺失 SQL, 绑定参数)。列名来自注册表，取值一律绑参。"""
    param = f"c{index}"
    operator = field.operator
    if operator == "gte":
        return Clause(field, value, f"st.{field.target_column} >= :{param}",
                      _missing_sql(field.target_column), {param: value})
    if operator == "lte":
        return Clause(field, value, f"st.{field.target_column} <= :{param}",
                      _missing_sql(field.target_column), {param: value})
    if operator == "eq":
        return Clause(field, value, f"st.{field.target_column} = :{param}",
                      _missing_sql(field.target_column), {param: value})
    if operator == "in":
        return Clause(field, value, f"st.{field.target_column} = any(:{param})",
                      _missing_sql(field.target_column), {param: list(value)})
    if operator == "requirement_capability":
        return Clause(field, value, f"st.{field.target_column} = any(:{param})",
                      _missing_sql(field.target_column), {param: list(CAPABILITY_VALUES)})
    if operator in {"overlap", "not_overlap"}:
        return _array_clause(field, value, index, param)
    if operator == "region_any":
        return _region_clause(field, value, index)
    raise ValueError(f"unsupported screening operator {operator!r} on {field.column}")


def _array_clause(field: ScreeningField, value: Any, index: int, param: str) -> Clause:
    """overlap / not_overlap 有两种目标形状，不能都当成行业。

    行业（industry_pairs_json）是 {l1, l2} 对象数组，重大风险与交易结构是扁平
    字符串数组。原来这两个算子写死了行业路径，于是**扁平数组的字段会静默生成
    打在 industry_pairs_json 上的 SQL** —— overlap 恒不命中（候选池恒空）、
    not_overlap 恒命中（条件恒真）。两种都不报错，正是最难查的那一类。
    """
    base = field.target_column.split(".")[0]
    values = {param: list(value)}
    if base == "industry_pairs_json":
        # industry_pairs_json 是唯一的行业事实源；industry_l1 / industry_l2 是
        # 派生展示列，筛选不能用它们（总纲 §2.3）。
        if field.operator == "overlap":
            json_key = field.target_column.split(".")[-1]
            return Clause(field, value, _industry_exists(json_key, param, index),
                          _industry_missing(index, (json_key,)), values)
        l1 = _industry_exists("l1", param, index)
        l2 = _industry_exists("l2", param, index)
        return Clause(field, value, f"not ({l1} or {l2})",
                      _industry_missing(index, ("l1", "l2")), values)

    hit = _flat_array_exists(base, param, index)
    missing = _missing_sql(base)
    if field.operator == "overlap":
        return Clause(field, value, hit, missing, values)
    # not_overlap 必须显式排掉缺失：`not exists(...)` 对空数组恒为真，而
    # major_risk_flags_json 的空数组是「**未核查**」。少了前半段，「没查过」
    # 会被当成「干净」通过风险条件 —— 方向恰好是危险的那一边。
    # 行业那条分支保持原样（排除行业不因行业为空而出局），两者语义确实不同。
    return Clause(field, value, f"not {missing} and not {hit}", missing, values)


_REGION_COLUMNS = {
    "province": "location_province",
    "city": "location_city",
    "district": "location_district",
}
_LEVEL_BY_COLUMN = {column: level for level, column in _REGION_COLUMNS.items()}


def _region_clause(field: ScreeningField, constraints: list[dict[str, str]], index: int) -> Clause:
    """每个 constraint 展开成它自己填到的层级的 AND，多个 constraint 之间 OR。

    本阶段只实现 required 语义（命中即通过）。买家侧 region_constraints_json 自带
    的 preferred / excluded 三态属阶段四，由 agent 决定拆成几次调用，不在 SQL 层
    自作主张。
    """
    parts: list[str] = []
    missing_parts: list[str] = []
    params: dict[str, Any] = {}
    for position, constraint in enumerate(constraints):
        levels = [
            (column, f"c{index}_{position}_{level}")
            for level, column in _REGION_COLUMNS.items()
            if constraint.get(level)
        ]
        if not levels:
            continue
        for column, param in levels:
            params[param] = constraint[_LEVEL_BY_COLUMN[column]]
        parts.append("(" + " and ".join(f"st.{column} = :{param}" for column, param in levels) + ")")
        # 缺失 = 「录到的层级都不矛盾，但有一级没录」：买家要苏州市、标的只录到
        # 江苏省，那是数据没录，不是这家不在苏州；而山东省的标的是真不达标。
        # 不区分这两者，agent 会把一个真门槛当成数据缺口去放宽。
        compatible = " and ".join(
            f"(st.{column} = :{param} or coalesce(st.{column}, '') = '')" for column, param in levels
        )
        blank = " or ".join(f"coalesce(st.{column}, '') = ''" for column, _ in levels)
        missing_parts.append(f"(({compatible}) and ({blank}))")
    sql = "(" + " or ".join(parts) + ")" if parts else "false"
    missing = "(" + " or ".join(missing_parts) + ")" if missing_parts else "false"
    return Clause(field, constraints, sql, missing, params)


def _boolean(expression: str) -> str:
    """三值逻辑收敛成两值。

    `not (净利 >= 5)` 在净利为 null 时是 NULL 而不是 TRUE，`count(*) filter`
    会把这行漏掉，淘汰拆分的三个数就对不上。所有条件统一先 coalesce 成 false。
    """
    return f"coalesce({expression}, false)"


def _and(expressions: list[str]) -> str:
    return " and ".join(expressions) if expressions else "true"


# -- 执行 ----------------------------------------------------------------


def screen_targets(
    db: Session,
    raw_conditions: Any,
    *,
    limit: int = DEFAULT_SCREENING_LIMIT,
    offset: int = 0,
    count_only: bool = False,
) -> ScreeningResult:
    """一组 AND 条件 → 命中数、逐条件淘汰拆分、按级别排序的前 N 条。"""
    limit = max(1, min(int(limit), MAX_SCREENING_LIMIT))
    offset = max(0, int(offset))
    conditions, ignored = normalize_conditions(
        raw_conditions,
        industry_l1_terms=list_l1_terms(db),
        industry_l2_terms=list_l2_terms(db),
    )
    clauses = [
        build_clause(SCREENING_FIELDS_BY_COLUMN[column], value, index)
        for index, (column, value) in enumerate(conditions.items())
    ]

    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    for clause in clauses:
        params.update(clause.params)

    hits = [_boolean(clause.sql) for clause in clauses]
    counts = db.execute(text(_count_sql(clauses, hits)), params).mappings().one()

    rows: list[dict[str, Any]] = []
    if not count_only:
        row_params = dict(params, limit=limit, offset=offset)
        rows = [
            dict(row)
            for row in db.execute(text(_rows_sql(hits)), row_params).mappings().all()
        ]

    matched = int(counts["matched"])
    return ScreeningResult(
        conditions=conditions,
        matched=matched,
        excluded_by_condition=_excluded_by_condition(clauses, counts, matched),
        rows=rows,
        ignored=ignored,
        limit=limit,
        offset=offset,
        count_only=count_only,
    )


def _count_sql(clauses: list[Clause], hits: list[str]) -> str:
    """一次扫描算完全部拆分。

    N 个条件跑 N+1 次查询也能得到同样的数，但那是 N+1 次全表扫描，而且随着条件
    变多会越来越慢 —— 这里是 1 次扫描、3N+1 个聚合。
    """
    select_parts = [f"count(*) filter (where {_and(hits)})::int as matched"]
    for index, clause in enumerate(clauses):
        others = _and([hit for position, hit in enumerate(hits) if position != index])
        missed = f"not {hits[index]}"
        missing = _boolean(clause.missing_sql)
        select_parts.append(f"count(*) filter (where {others})::int as without_{index}")
        # 「缺失」与「不达标」都限定在「没通过这一条」的那批里，两者相加恒等于
        # 总计 —— 不加 `not <条件>` 的话，not_overlap（行业为空反而通过）这类
        # 算子会让恒等式当场破掉。
        select_parts.append(
            f"count(*) filter (where {others} and {missed} and {missing})::int as missing_{index}"
        )
        select_parts.append(
            f"count(*) filter (where {others} and {missed} and not {missing})::int as failed_{index}"
        )
    return (
        "select\n  "
        + ",\n  ".join(select_parts)
        + f"\nfrom seller_target st\nwhere {_GATE_SQL}"
    )


def _rows_sql(hits: list[str]) -> str:
    projection = ",\n  ".join(f"st.{column}" for column in ROW_COLUMNS)
    where = _GATE_SQL + ("".join(f"\n      and {hit}" for hit in hits))
    return (
        f"select\n  {projection}\n"
        f"from seller_target st\n"
        f"where {where}\n"
        # 先排完整个命中集再截前 N，不是先截再排。id 只做稳定 tiebreak，
        # 否则同一秒更新的标的翻页时会重复或漏掉。
        "order by st.target_grade asc, st.updated_at desc, st.id asc\n"
        "limit :limit offset :offset"
    )


def _excluded_by_condition(
    clauses: list[Clause],
    counts: Any,
    matched: int,
) -> dict[str, dict[str, int]]:
    """去掉每一条能多召回几家，以及那批人里有多少只是没录数据。

    这是 agent 能否正确放宽的唯一依据：6 家里 5 家只是没录负债率，该去掉的就是
    负债率而不是净利。没有这个拆分，agent 只看得到「加了负债率从 6 掉到 0」，
    分不清「条件太严」与「数据没录」，放宽方向必然靠猜。
    """
    report: dict[str, dict[str, int]] = {}
    for index, clause in enumerate(clauses):
        without = int(counts[f"without_{index}"])
        report[clause.field.column] = {
            "总计": without - matched,
            "字段为空": int(counts[f"missing_{index}"]),
            "确实不达标": int(counts[f"failed_{index}"]),
            "去掉后命中": without,
        }
    return report


# -- 摘要 ----------------------------------------------------------------


def _number(value: Any) -> Any:
    """Decimal → float，仅为了 JSON 里是个数字而不是字符串。不做任何格式化。"""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _industry_text(pairs: Any, limit: int = 3) -> str | None:
    if not isinstance(pairs, list):
        return None
    parts: list[str] = []
    for pair in pairs[:limit]:
        if not isinstance(pair, dict):
            continue
        l1 = str(pair.get("l1") or "").strip()
        l2 = str(pair.get("l2") or "").strip()
        label = "/".join(part for part in (l1, l2) if part)
        if label and label not in parts:
            parts.append(label)
    return "、".join(parts) or None


def _row_digest(row: dict[str, Any], conditions: dict[str, Any]) -> dict[str, Any]:
    """一家标的的极简摘要（约 80 字符）。

    刻意不塞画像正文、业务摘要、风险摘要：主 Agent 不做评估，只判断「够不够、
    要不要再筛」；完整信息在深评那一次调用里一次性给。
    """
    digest: dict[str, Any] = {
        "id": str(row.get("id") or ""),
        "name": row.get("target_name"),
        "grade": row.get("target_grade"),
    }
    industry = _industry_text(row.get("industry_pairs_json"))
    if industry:
        digest["industry"] = industry
    region = "".join(
        str(value)
        for value in (row.get("location_province"), row.get("location_city"), row.get("location_district"))
        if value
    )
    if region:
        digest["region"] = region
    for column in conditions:
        field = SCREENING_FIELDS_BY_COLUMN.get(column)
        if field is None or field.operator not in _PLAIN_OPERATORS:
            # 行业与地区已经在上面了，不重复。
            continue
        value = row.get(field.target_column)
        if value is not None:
            digest[field.target_column] = _number(value)
    return digest
