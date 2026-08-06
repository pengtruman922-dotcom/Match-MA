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
    multi_value_enum_values,
    screening_columns,
    seller_target_fact_columns,
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
TARGET_FACTS_MIGRATION = REPO / "database/migrations/015_target_risk_and_structure_facts.sql"


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


def test_closed_list_columns_match_their_db_check() -> None:
    """多值枚举列的 check 约束写的是 `not in (...)`，_db_accepts 认不出这种形状。

    这类列的漂移方式很隐蔽：注册表加一个取值、忘了改迁移，结果是解析归一化放行、
    DB 在写入的最后一刻整条打回。所以单独比对一次。
    """
    sql = TARGET_FACTS_MIGRATION.read_text(encoding="utf-8")
    for column, values in multi_value_enum_values().items():
        block = re.search(rf"constraint chk_seller_target_{column}\b.*?not in \((.*?)\)", sql, re.S)
        assert block, f"{column} 在迁移里没有元素级 check 约束"
        assert values == set(re.findall(r"'([a-z_]+)'", block.group(1))), (
            f"{column} 注册表枚举与 DB check 约束不一致"
        )


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
    target_facts_sql = TARGET_FACTS_MIGRATION.read_text(encoding="utf-8")
    post_baseline_columns = {
        "location_province": (migration_sql, "add column location_province text"),
        "location_city": (migration_sql, "add column location_city text"),
        "location_district": (migration_sql, "add column location_district text"),
        "industry_pairs_json": (refinement_sql, "add column industry_pairs_json jsonb"),
        "financial_period_end_date": (
            RESEARCH_PERIOD_MIGRATION.read_text(encoding="utf-8"),
            "add column if not exists financial_period_end_date date",
        ),
        "major_risk_flags_json": (target_facts_sql, "add column if not exists major_risk_flags_json jsonb"),
        "acceptable_transaction_structures_json": (
            target_facts_sql,
            "add column if not exists acceptable_transaction_structures_json jsonb",
        ),
        "main_products_text": (target_facts_sql, "add column if not exists main_products_text text"),
        "stock_code": (target_facts_sql, "add column if not exists stock_code text"),
    }
    assert missing <= set(post_baseline_columns), (
        f"注册表引用了 seller_target 不存在的列：{sorted(missing - set(post_baseline_columns))}"
    )
    for column in missing:
        sql, expected = post_baseline_columns[column]
        assert expected in sql, f"{column} 没有对应的建列迁移"
    for retired in ("industry_primary", "industry_secondary", "registered_province", "registered_city", "headquarter_province", "headquarter_city", "raw_region_text", "region_granularity"):
        assert f"drop column {retired}" in migration_sql
    # 判死的列不能还留在注册表里——注册表是写入白名单的事实源，留着等于允许写。
    assert "drop column if exists operation_stability_status" in target_facts_sql
    assert "operation_stability_status" not in {ind.column for ind in SELLER_TARGET_INDICATORS}


def test_fact_projection_is_derived_everywhere_it_is_read() -> None:
    """标的事实列的 SELECT 投影只能有一份。

    以前信息页 / 解析 / 采纳 / 业务更新各手写一份，加一列漏改一处的表现是
    「字段存进去了但某个页面看不见」，最难查。推荐域的两处（recommendation_flow、
    recommendation_agent_tools）仍是手写，是有意的：它们只取打分需要的子集，
    收敛它们要动打分文件。
    """
    projection = seller_target_fact_columns()
    assert set(projection) >= {ind.column for ind in SELLER_TARGET_INDICATORS}
    assert len(projection) == len(set(projection)), "投影里有重复列名"
    for relative in (
        "backend/app/api/routes/seller_targets.py",
        "backend/app/api/routes/update_logs.py",
        "backend/app/jobs/handlers/seller_target_parse.py",
        "backend/app/services/extracted_action_apply.py",
        "backend/app/services/business_update_flow.py",
    ):
        source = (REPO / relative).read_text(encoding="utf-8")
        assert "seller_target_fact_columns" in source, f"{relative} 没有走派生投影"


def test_every_indicator_group_key_is_declared() -> None:
    group_keys = {group.key for group in GROUPS}
    used = {ind.group for ind in SELLER_TARGET_INDICATORS if ind.group is not None}
    assert used <= group_keys, f"指标引用了未声明的分组：{sorted(used - group_keys)}"
