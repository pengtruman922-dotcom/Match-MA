"""The registry is the single source; these guard it against reality.

The parse and research whitelists now derive from the registry (common.py and
research_apply.py read writable_columns/writable_enum_values), so there is no
separate hand-list to reconcile — the registry IS the definition. What still
needs guarding is the registry against the sources it does NOT yet own: the
frontend screening badges (until R3a-2 switches the panel), the columns the
scorer reads, the real DB columns, and the DB enum check constraints.
"""

import re
from pathlib import Path

from backend.app.jobs.handlers.common import (
    BUYER_INTENT_CHANGE_FIELDS,
    BUYER_INTENT_ENUM_FIELDS,
    SELLER_TARGET_CHANGE_FIELDS,
    SELLER_TARGET_ENUM_FIELDS,
    SELLER_TARGET_SYSTEM_FACT_FIELDS,
)
from backend.app.registry.indicators import (
    BUYER_INTENT_INDICATORS,
    SELLER_TARGET_INDICATORS,
    GROUPS,
    indicators_for,
    screening_columns,
    writable_columns,
    writable_enum_values,
)
from backend.app.services.research_apply import RESEARCH_STRUCTURED_FIELDS

REPO = Path(__file__).resolve().parents[1]
RECOMMENDATION_FLOW = REPO / "backend/app/services/recommendation_flow.py"
BASELINE = REPO / "database/migrations/001_baseline.sql"
R4A_MIGRATION = REPO / "database/migrations/002_target_information_model.sql"
R5_MIGRATION = REPO / "database/migrations/004_information_refinement.sql"
RESEARCH_PERIOD_MIGRATION = REPO / "database/migrations/009_research_financial_period_guard.sql"
BUYER_CONTRACT_MIGRATION = REPO / "database/migrations/011_buyer_intent_condition_contract.sql"


def test_consumers_derive_from_the_registry() -> None:
    # 白名单已改为派生，这里确认「派生」这条线没被谁悄悄改回硬列表。
    assert SELLER_TARGET_CHANGE_FIELDS == writable_columns("parse") | SELLER_TARGET_SYSTEM_FACT_FIELDS
    assert set(RESEARCH_STRUCTURED_FIELDS) == writable_columns("research")
    assert SELLER_TARGET_ENUM_FIELDS == writable_enum_values()
    assert BUYER_INTENT_CHANGE_FIELDS == writable_columns("parse", "buyer_intent")
    assert BUYER_INTENT_ENUM_FIELDS == writable_enum_values("buyer_intent")


def test_buyer_intent_indicators_are_real_columns() -> None:
    sql = BASELINE.read_text(encoding="utf-8")
    body = re.search(r"create table buyer_intent \((.*?)\n\);", sql, re.S)
    assert body, "baseline 未找到 buyer_intent 建表块"
    columns = set(re.findall(r"^\s+([a-z_0-9]+)\s", body.group(1), re.M))
    missing = {ind.column for ind in BUYER_INTENT_INDICATORS} - columns
    assert missing <= {"acceptable_listed_status_json", "condition_effects_json"}, (
        f"注册表引用了 buyer_intent 不存在的列：{sorted(missing)}"
    )
    migration_sql = BUYER_CONTRACT_MIGRATION.read_text(encoding="utf-8")
    for column in missing:
        assert f"add column if not exists {column} jsonb" in migration_sql
    assert indicators_for("buyer_intent") is BUYER_INTENT_INDICATORS


def _db_accepts(sql: str, column: str, values: set[str]) -> bool | None:
    """Whether some `column = ANY (ARRAY[...])` check constraint accepts `values`.

    Returns None when the column has no such constraint. The column name can
    appear in several tables (status especially), so this accepts the values if
    *any* constraint for that name is a superset — the relevant table's is.
    """
    arrays = re.findall(column + r" = ANY \(ARRAY\[(.*?)\]\)", sql, re.S)
    if not arrays:
        return None
    return any(values <= set(re.findall(r"'([a-z_]+)'", body)) for body in arrays)


def test_registry_enum_values_valid_for_both_entities() -> None:
    # 注册表声明的枚举取值必须能被对应 DB check 约束接受，否则写入会被 DB 拒。
    sql = BASELINE.read_text(encoding="utf-8")
    for entity in ("seller_target", "buyer_intent"):
        for column, values in writable_enum_values(entity).items():
            accepted = _db_accepts(sql, column, values)
            if accepted is None:
                continue  # 无 DB check 约束的列
            assert accepted, f"{entity}.{column} 注册表枚举含 DB 不接受的值"


def _scorer_reads() -> set[str]:
    source = RECOMMENDATION_FLOW.read_text(encoding="utf-8")
    fields = set(re.findall(r"target\.get\(\"([a-z_0-9]+)\"", source))
    fields |= set(re.findall(r"\(\s*\"[a-z_]+\",\s*\"([a-z_0-9]+)\",\s*[\d.]+,", source))
    return fields


def test_registry_screening_covers_everything_the_scorer_reads() -> None:
    # 打分器读取的每个标的列都必须被注册表标为 screening；
    # 折叠列（如 headquarter_city）由其父列的 screening 覆盖；
    # 定性摘要与行业原文进画像/归一化，不作为独立筛选列。
    not_screening_columns = {
        "risk_summary", "gap_summary", "industry_primary", "industry_secondary",
    }
    screening = screening_columns()
    covered = set(screening)
    for ind in SELLER_TARGET_INDICATORS:
        if ind.fold_into is not None and ind.fold_into in screening:
            covered.add(ind.column)

    reads = _scorer_reads()
    known_columns = {ind.column for ind in SELLER_TARGET_INDICATORS}
    unscreened = (reads & known_columns) - covered - not_screening_columns
    assert not unscreened, f"打分器读取但注册表未标 screening：{sorted(unscreened)}"


def test_every_indicator_is_a_real_seller_target_column() -> None:
    sql = BASELINE.read_text(encoding="utf-8")
    body = re.search(r"create table seller_target \((.*?)\n\);", sql, re.S)
    assert body, "baseline 未找到 seller_target 建表块"
    columns = set(re.findall(r"^\s+([a-z_0-9]+)\s", body.group(1), re.M))
    missing = {ind.column for ind in SELLER_TARGET_INDICATORS} - columns
    migration_sql = R4A_MIGRATION.read_text(encoding="utf-8")
    refinement_sql = R5_MIGRATION.read_text(encoding="utf-8")
    assert missing <= {"location_province", "location_city", "location_district", "industry_pairs_json", "financial_period_end_date"}, (
        f"注册表引用了 seller_target 不存在的列：{sorted(missing)}"
    )
    for column in missing:
        if column == "industry_pairs_json":
            assert f"add column {column} jsonb" in refinement_sql
        elif column == "financial_period_end_date":
            assert f"add column if not exists {column} date" in RESEARCH_PERIOD_MIGRATION.read_text(encoding="utf-8")
        else:
            assert f"add column {column} text" in migration_sql
    for retired in ("industry_primary", "industry_secondary", "registered_province", "registered_city", "headquarter_province", "headquarter_city", "raw_region_text", "region_granularity"):
        assert f"drop column {retired}" in migration_sql


def test_every_indicator_group_key_is_declared() -> None:
    group_keys = {group.key for group in GROUPS}
    used = {ind.group for ind in SELLER_TARGET_INDICATORS if ind.group is not None}
    assert used <= group_keys, f"指标引用了未声明的分组：{sorted(used - group_keys)}"
