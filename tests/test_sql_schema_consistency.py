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

CHECKED_SOURCES = (
    "backend/app/services/recommendation_flow.py",
    "backend/app/services/search_docs.py",
    "backend/app/jobs/handlers/recommendation.py",
    "backend/app/services/screening_sql.py",
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
    missing: list[str] = []
    for alias, table in TABLE_ALIASES.items():
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


def test_buyer_intent_json_columns_are_bound_as_jsonb() -> None:
    """A list bound without type_=JSONB fails at write time, not at import."""
    from backend.app.jobs.handlers.buyer_intent_parse import (
        BUYER_INTENT_PARSE_FIELDS,
        BUYER_INTENT_PARSE_JSON_FIELDS,
    )

    parse_json_fields = {field for field in BUYER_INTENT_PARSE_FIELDS if field.endswith("_json")}
    unbound = parse_json_fields - BUYER_INTENT_PARSE_JSON_FIELDS
    assert not unbound, f"parser writes these json columns without a JSONB bind: {sorted(unbound)}"

    apply_source = (PROJECT_ROOT / "backend/app/services/extracted_action_apply.py").read_text(encoding="utf-8")
    apply_json_block = re.search(r"json_fields = \{(.*?)\}", apply_source, re.S)
    assert apply_json_block is not None
    apply_bound = set(re.findall(r'"(\w+_json)"', apply_json_block.group(1)))
    assert parse_json_fields <= apply_bound | {"parsed_requirement_json"}, (
        "extracted_action_apply must bind the same json columns the parser writes: "
        f"{sorted(parse_json_fields - apply_bound)}"
    )
