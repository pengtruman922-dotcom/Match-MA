# -*- coding: utf-8 -*-
"""Compare a live database schema against the committed production snapshot.

CI 的 migrations job 用它验收基线：对全新 PostgreSQL 跑完 alembic 后执行本脚本,
断言得到的 schema 与生产快照（tests/fixtures/schema_snapshot_production.json,
2026-07-22 经 /debug/schema-snapshot 采集）完全一致。

NOT NULL 类型的 pg_constraint 条目在两侧都被排除——PG17 起才把列级 not null
登记进目录，排除后比对对 PG 大版本不敏感，列的非空性仍由 columns 清单覆盖。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "schema_snapshot_production.json"

COLUMNS_SQL = """
select c.relname as table_name,
       a.attname as column_name,
       a.attnum as position,
       format_type(a.atttypid, a.atttypmod) as data_type,
       a.attnotnull as not_null,
       pg_get_expr(d.adbin, d.adrelid) as default_expr
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
left join pg_attrdef d on d.adrelid = c.oid and d.adnum = a.attnum
where n.nspname = 'public'
  and c.relkind = 'r'
  and a.attnum > 0
  and not a.attisdropped
order by c.relname, a.attnum
"""

CONSTRAINTS_SQL = """
select conrelid::regclass::text as table_name,
       conname as constraint_name,
       pg_get_constraintdef(oid) as definition
from pg_constraint
where connamespace = 'public'::regnamespace
order by 1, 2
"""

INDEXES_SQL = """
select tablename as table_name,
       indexname as index_name,
       indexdef as definition
from pg_indexes
where schemaname = 'public'
order by 1, 2
"""


def normalize(snapshot: dict) -> dict[str, set[tuple]]:
    return {
        "columns": {
            (
                c["table_name"],
                c["column_name"],
                c["data_type"],
                bool(c["not_null"]),
                c["default_expr"] or "",
            )
            for c in snapshot["columns"]
        },
        "constraints": {
            (c["table_name"], c["constraint_name"], c["definition"])
            for c in snapshot["constraints"]
            if not c["definition"].startswith("NOT NULL")
        },
        "indexes": {
            (i["table_name"], i["index_name"], i["definition"])
            for i in snapshot["indexes"]
        },
    }


def live_snapshot(database_url: str) -> dict:
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url)
    with engine.connect() as conn:
        return {
            "columns": [dict(r) for r in conn.execute(text(COLUMNS_SQL)).mappings()],
            "constraints": [dict(r) for r in conn.execute(text(CONSTRAINTS_SQL)).mappings()],
            "indexes": [dict(r) for r in conn.execute(text(INDEXES_SQL)).mappings()],
        }


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set")
        return 2

    expected = normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))
    actual = normalize(live_snapshot(database_url))

    failed = False
    for kind in ("columns", "constraints", "indexes"):
        missing = sorted(expected[kind] - actual[kind])
        unexpected = sorted(actual[kind] - expected[kind])
        for item in missing:
            failed = True
            print(f"MISSING {kind[:-1]}: {item}")
        for item in unexpected:
            failed = True
            print(f"UNEXPECTED {kind[:-1]}: {item}")
        print(f"{kind}: expected={len(expected[kind])} actual={len(actual[kind])}")

    if failed:
        print("\nschema does NOT match the production snapshot")
        return 1
    print("\nschema matches the production snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
