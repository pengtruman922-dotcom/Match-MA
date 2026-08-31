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

# 业务扫描（business_scan）的上限。**它不是把 limit 调大**，是另一种返回形状：
# 每条只有名称、级别、地区、业务摘要，没有财务数字、没有淘汰拆分。
#
# 为什么需要它：0828 判决一之后正向初筛不再有行业条件，一条只写了
# 「最低营收 1 亿」的需求会召回接近全库。这不是 bug，是判决一的设计意图 ——
# 业务匹配整段交给 LLM 读文本。但 20 条的上限会把「接近全库」截成任意 20 家，
# 于是**该推的标的连被看见的机会都没有**。所以补一条全量薄返回的路径：
#     SQL 收窄（收不窄也没关系）→ 全量业务摘要给 LLM 首轮筛 → 选出 10-20 家 → 深评
#
# 300 是按库规模定的：标的库约 300 家，业务摘要平均 49 字，全量约 1.5 万字，
# 一次调用装得下。库长到这个数以上时要么收窄条件，要么这条路要重新设计 ——
# 所以超出时如实报数并提示收窄，不静默截断。
#
# ⚠️ 标的侧业务摘要平均只有 49 字，**远薄于买家侧的 259 字**。同一手法在买家侧
# （skills/buyer-search 接口一）验过好用，不等于在标的侧也够 —— 这一段的效果
# 必须实测，见方案 0828 §十。
MAX_BUSINESS_SCAN_LIMIT = 300

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
    # 业务扫描（business_scan）读这两列。普通初筛的摘要刻意不带它们
    # （主 Agent 在那一步只判「够不够、要不要再筛」），但列要在投影里，
    # 否则 business_scan 拿不到 —— 两种返回形状共用同一条 SQL。
    "business_summary",
    "main_products_text",
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
    business_scan: bool = False

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
            digest = _business_digest if self.business_scan else _row_digest
            payload["returned"] = [digest(row, self.conditions) for row in self.rows]
            remaining = self.matched - self.offset - self.returned_count
            if remaining > 0:
                # 不做字符截断：截断一个 JSON 只会得到半个 JSON，模型解析失败
                # 还不知道为什么。
                payload["note"] = f"另有 {remaining} 家未返回，请收窄条件或使用 offset 翻页。"
        if self.business_scan:
            payload["scan_note"] = (
                "这是业务扫描：每条只有业务摘要，没有财务数字，也没有逐条件淘汰拆分。"
                "请逐条读「业务摘要」判断业务是否真的对口，选出 10-20 家之后再做深评。"
                "**业务摘要为空的不要从公司名猜业务**，如实说信息不足。"
            )
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
#
# 行业的 exists/missing 两个构造器 2026-08-28 随需求侧行业条件一起删除。
# 它们打在 seller_target.industry_pairs_json 上，而现在没有任何买家条件指向那一列
# （注册表里它的 screening 也一并置 False）。留着一个没人调的 SQL 构造器，
# 下一个人会以为行业还能筛。


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
    if operator in {"region_any", "region_none"}:
        return _region_clause(field, value, index)
    raise ValueError(f"unsupported screening operator {operator!r} on {field.column}")


def _array_clause(field: ScreeningField, value: Any, index: int, param: str) -> Clause:
    """overlap / not_overlap 打在标的侧的**扁平字符串数组**上。

    以前这里还有一条行业分支（industry_pairs_json 是 {l1, l2} 对象数组），
    0828 随需求侧行业条件一起删掉了。当时那条分支写死了行业路径，于是
    **扁平数组的字段会静默生成打在 industry_pairs_json 上的 SQL** ——
    overlap 恒不命中（候选池恒空）、not_overlap 恒命中（条件恒真）。
    两种都不报错，正是最难查的那一类，所以这里保留一句提醒：
    新增 overlap 类条件时，先确认对手方列的形状。
    """
    base = field.target_column.split(".")[0]
    values = {param: list(value)}
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

    两个算子共用这段构造，只在最后取反：
      region_any（acceptable_regions_json）  命中即通过
      region_none（excluded_regions_json）   命中即出局

    0828 之前买家侧只有一列 region_constraints_json，靠元素里的 effect 三态区分
    可接受/优先/排除，而 SQL 只实现了 required 那一档 —— 也就是说**排除地区
    从来没有真的排除过任何标的**。现在拆成两列之后，方向写在列名里，
    SQL 两条都实现，不再有「存了但不生效」的那一半。
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
    hit = "(" + " or ".join(parts) + ")" if parts else "false"
    missing = "(" + " or ".join(missing_parts) + ")" if missing_parts else "false"
    if field.operator == "region_none":
        # 排除地区不把「地区没录全」算成缺失：买家说「不要新疆」，一个连省份都
        # 没录的标的**不该**因此出局 —— 那是数据缺口，不是它在新疆。
        # 所以命中取反、缺失恒 false（这一条从不贡献缺失统计）。
        return Clause(field, constraints, f"not {_boolean(hit)}", "false", params)
    return Clause(field, constraints, hit, missing, params)


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
    business_scan: bool = False,
) -> ScreeningResult:
    """一组 AND 条件 → 命中数、逐条件淘汰拆分、按级别排序的前 N 条。

    `business_scan=True` 换一种返回形状：上限抬到 300，每条只回业务摘要，
    供主 Agent 做首轮语义筛。0828 判决一之后正向初筛没有行业条件了，
    这条路是它的补偿 —— 详见 MAX_BUSINESS_SCAN_LIMIT 的注释。
    """
    ceiling = MAX_BUSINESS_SCAN_LIMIT if business_scan else MAX_SCREENING_LIMIT
    if business_scan:
        limit = ceiling if limit == DEFAULT_SCREENING_LIMIT else limit
    limit = max(1, min(int(limit), ceiling))
    offset = max(0, int(offset))
    conditions, ignored = normalize_conditions(raw_conditions)
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
        business_scan=business_scan,
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


def _business_digest(row: dict[str, Any], conditions: dict[str, Any]) -> dict[str, Any]:
    """业务扫描的一条：只回答「这家是做什么的」。

    刻意不带财务数字与条件取值 —— 首轮筛判的是业务匹配，数字那一步已经由 SQL
    做过了。带上它们只会把 300 条撑成读不完的体积，而模型在这一步也用不上。

    行业**保留**：它不再是筛选维，但仍是判业务方向的辅助信息（总纲 §2.3
    仍然承认它是唯一的标的行业事实源）。退役的是「能不能筛」，不是「看不看得见」。
    """
    province, city = row.get("location_province"), row.get("location_city")
    # 直辖市的省与市同名，直接拼会变成「北京市北京市」。
    region = "".join(dict.fromkeys(filter(None, [province, city]))) or None
    digest: dict[str, Any] = {
        "id": str(row.get("id") or ""),
        "name": row.get("target_name"),
        "grade": row.get("target_grade"),
    }
    industry = _industry_text(row.get("industry_pairs_json"))
    if industry:
        digest["industry"] = industry
    if region:
        digest["region"] = region
    summary = (row.get("business_summary") or "").strip()
    if summary:
        digest["business_summary"] = summary
    products = (row.get("main_products_text") or "").strip()
    if products:
        digest["main_products"] = products
    return digest


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
