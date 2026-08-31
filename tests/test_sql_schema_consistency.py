"""Guards against SQL that references columns the migrations never create.

Raw SQL is only checked by PostgreSQL at request time, so a typo or a column
added to a query but not to a migration surfaces as a production 500 rather
than a test failure. These tests rebuild the schema from the migration files
and check it against the columns the query strings actually reference.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"

TABLE_ALIASES = {
    "bi": "buyer_intent",
    "bp": "buyer_party",
    "st": "seller_target",
    "x": "buyer_intent_target_exclusion",
}

# 别名是约定不是保证：同一个短名在别处可能指向完全不同的东西。
# `buyer_intents.py` 里 `st` 是 `jsonb_array_elements_text(...) as st(value)` 的横向
# 别名，跟 seller_target 无关 —— 不排掉它，这条守卫会拿 `st.value` 去 seller_target
# 里找列然后报一个假阳性。排除写在这里而不是放宽正则：放宽了别处的真错也就漏了。
ALIASES_NOT_APPLICABLE: dict[str, set[str]] = {
    "backend/app/api/routes/buyer_intents.py": {"st"},
}

CHECKED_SOURCES = (
    "backend/app/services/recommendation_flow.py",
    "backend/app/services/search_docs.py",
    "backend/app/jobs/handlers/recommendation.py",
    "backend/app/services/screening_sql.py",
    # 买家列表一行要同时显示两个半边，于是这里多了一串 `bp.` 列。拼错一个的表现是
    # 「买家管理整页 500」—— 裸 SQL 只有请求时才被 Postgres 检查。
    "backend/app/api/routes/buyer_intents.py",
    "backend/app/services/profile_sections.py",
)

# 词边界匹配：`excluded_industries_json` 这类列名以 exclude 开头，
# 裸 startswith 会把它误判成 EXCLUDE 约束行（压平后真实踩过）。
DDL_LEAD_RE = re.compile(r"(?:constraint|primary\s+key|unique|check|foreign|exclude)\b", re.I)


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


def _build_schema() -> dict[str, set[str]]:
    schema: dict[str, set[str]] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"create table (?:if not exists )?(\w+) \((.*?)\n\);", sql, re.S):
            table, body = match.group(1), match.group(2)
            columns = schema.setdefault(table, set())
            for line in body.splitlines():
                line = line.strip()
                if not line or DDL_LEAD_RE.match(line):
                    continue
                columns.add(line.split()[0].strip(","))
        for match in re.finditer(r"alter table (\w+)([^;]*)", sql, re.I | re.S):
            table, body = match.group(1), match.group(2)
            for column in re.findall(r"add column (?:if not exists )?(\w+)", body, re.I):
                schema.setdefault(table, set()).add(column)
    return schema


SCHEMA = _build_schema()


def test_schema_rebuild_finds_the_core_tables() -> None:
    assert "buyer_intent" in SCHEMA
    assert "seller_target" in SCHEMA
    assert "industry_l1" in SCHEMA["seller_target"]


@pytest.mark.parametrize("source_path", CHECKED_SOURCES)
def test_aliased_columns_exist_in_the_schema(source_path: str) -> None:
    source = (PROJECT_ROOT / source_path).read_text(encoding="utf-8")
    skipped = ALIASES_NOT_APPLICABLE.get(source_path, set())
    missing: list[str] = []
    for alias, table in TABLE_ALIASES.items():
        if alias in skipped:
            continue
        columns = SCHEMA.get(table, set())
        if not columns:
            continue
        for column in sorted(set(re.findall(rf"\b{alias}\.([a-z_]+)\b", source))):
            if column not in columns:
                missing.append(f"{source_path}: {alias}.{column} is not a column of {table}")
    assert not missing, "\n".join(missing)


def test_every_screening_condition_has_a_real_target_column() -> None:
    """初筛 SQL 的列名是从注册表的 target_column 拼出来的，不是字面量。

    上面那条按 `st.<列名>` 正则扫源码的用例扫不到它们，而拼错一个列名的表现是
    「这个条件一用整次筛选就 500」——只有真库或这条用例能拦住。
    """
    from backend.app.services.screening_schema import SCREENING_FIELDS

    columns = SCHEMA["seller_target"]
    missing = [
        f"{field.column} -> {part}"
        for field in SCREENING_FIELDS
        for part in (piece.split(".")[0] for piece in field.target_column.split(","))
        if part not in columns
    ]
    assert not missing, f"screening 对手方列不存在于 seller_target：{missing}"


def _seller_target_column_types() -> dict[str, str]:
    """seller_target 每一列的 DDL 类型（baseline + 后续迁移的 add column）。"""
    types: dict[str, str] = {}
    baseline = _strip_sql_comments((MIGRATIONS_DIR / "001_baseline.sql").read_text(encoding="utf-8"))
    pattern = r"create table (?:if not exists )?seller_target \((.*?)\n\);"
    body = re.search(pattern, baseline, re.S | re.I)
    assert body is not None
    for line in body.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or DDL_LEAD_RE.match(line):
            continue
        parts = line.split()
        if len(parts) >= 2:
            types[parts[0]] = " ".join(parts[1:3]).lower()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql"))[1:]:
        sql = _strip_sql_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"alter table seller_target([^;]*)", sql, re.I | re.S):
            for added in re.finditer(r"add column (?:if not exists )?(\w+)\s+([a-z ]+)", match.group(1), re.I):
                types[added.group(1)] = added.group(2).strip().lower()
            for dropped in re.finditer(r"drop column (?:if exists )?(\w+)", match.group(1), re.I):
                types.pop(dropped.group(1), None)
    return types


def test_date_columns_are_not_declared_as_strings_in_the_response_model() -> None:
    """出参模型的类型要容得下列的真实类型，否则整页响应校验失败。

    2026-08-18 的生产事故：`financial_period_end_date` 是本表唯一一个真 date 列
    （valuation_date / asking_price_date 在 DDL 里是 text），被声明成 `str | None`
    出参。psycopg 返回的是 `datetime.date`，于是**只要这一页里有任何一条填了这个
    日期，整页 500** —— 标的列表全空，而分桶接口照常有数，日志之外没有任何提示。

    这一类错误 SQL 不报、类型检查不报、CI 也不报（测试库里那一列全空），所以在
    这里钉住：DDL 里是 date 的列，出参模型必须接受 date。
    """
    from datetime import date
    from typing import Union, get_args, get_origin

    from backend.app.api.routes.seller_targets import SellerTargetOut

    def accepts_date(annotation: object) -> bool:
        if annotation is date:
            return True
        if get_origin(annotation) in (Union, __import__("types").UnionType):
            return any(arg is date for arg in get_args(annotation))
        return False

    types = _seller_target_column_types()
    offenders = [
        column
        for column, field in SellerTargetOut.model_fields.items()
        if types.get(column, "").startswith("date") and not accepts_date(field.annotation)
    ]
    assert not offenders, f"这些列在库里是 date，出参却没声明成 date：{offenders}"


def test_route_inserts_declare_every_json_column_as_jsonb() -> None:
    """路由里手写的 insert 也必须给每个 *_json 列声明 type_=JSONB。

    下面那条只看解析 handler 与 extracted_action_apply 的字段集合，看不到 REST
    路由手写的 insert —— 而 018 给 buyer_intent 加 unacceptable_risk_flags_json
    时，params 与插入列都接上了、``bindparam(..., type_=JSONB)`` 漏了。少了类型
    声明，Python 的 ``[]`` 会被适配成 Postgres 数组而不是 jsonb，写进 jsonb 列
    直接类型不匹配；而它的默认值恒为 ``[]``，于是「新建买家需求」每一次都 500。
    导入时看不出来，写库路径又要真数据库才跑得到，所以这里做成静态断言。
    """
    pattern = re.compile(r"insert into\s+(\w+)\s*\((.*?)\)\s*values", re.S)
    bind_pattern = re.compile(r'bindparam\("(\w+)", type_=JSONB\)')
    problems: list[str] = []
    for path in sorted((PROJECT_ROOT / "backend/app/api/routes").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in pattern.finditer(source):
            columns = [item.strip() for item in match.group(2).split(",") if item.strip()]
            json_columns = [item for item in columns if item.endswith("_json")]
            if not json_columns:
                continue
            # 从这条 insert 起、到下一条 insert 之前，就是它自己的 .bindparams(...)。
            nxt = source.find("insert into", match.end())
            window = source[match.start() : nxt if nxt != -1 else len(source)]
            bound = set(bind_pattern.findall(window))
            problems.extend(
                f"{path.name}: insert into {match.group(1)} -> {column}"
                for column in json_columns
                if column not in bound
            )
    assert not problems, "这些 json 列写库时没声明 type_=JSONB：\n  " + "\n  ".join(problems)


def test_buyer_intent_json_columns_are_bound_as_jsonb() -> None:
    """A list bound without type_=JSONB fails at write time, not at import."""
    from backend.app.jobs.handlers.buyer_intent_parse import (
        BUYER_INTENT_PARSE_FIELDS,
        BUYER_INTENT_PARSE_JSON_FIELDS,
    )

    parse_json_fields = {field for field in BUYER_INTENT_PARSE_FIELDS if field.endswith("_json")}
    unbound = parse_json_fields - BUYER_INTENT_PARSE_JSON_FIELDS
    assert not unbound, f"parser writes these json columns without a JSONB bind: {sorted(unbound)}"

    # 比对运行时取值而不是去源码里扒字面量：两份清单 0828 起都从注册表派生，
    # 正则扒法在派生之后只会扒到空集，于是这条守卫会静默通过。
    from backend.app.services.extracted_action_apply import BUYER_INTENT_JSONB_COLUMNS

    assert parse_json_fields <= BUYER_INTENT_JSONB_COLUMNS, (
        "extracted_action_apply must bind the same json columns the parser writes: "
        f"{sorted(parse_json_fields - BUYER_INTENT_JSONB_COLUMNS)}"
    )
