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
    SELLER_TARGET_CHANGE_FIELDS,
    SELLER_TARGET_ENUM_FIELDS,
)
from backend.app.registry.indicators import (
    SELLER_TARGET_INDICATORS,
    GROUPS,
    screening_columns,
    writable_columns,
    writable_enum_values,
)
from backend.app.services.research_apply import RESEARCH_STRUCTURED_FIELDS

REPO = Path(__file__).resolve().parents[1]
INFO_GROUPS = REPO / "frontend/src/features/targets/infoGroups.ts"
RECOMMENDATION_FLOW = REPO / "backend/app/services/recommendation_flow.py"
BASELINE = REPO / "database/migrations/001_baseline.sql"


def test_consumers_derive_from_the_registry() -> None:
    # 白名单已改为派生，这里确认「派生」这条线没被谁悄悄改回硬列表。
    assert SELLER_TARGET_CHANGE_FIELDS == writable_columns("parse")
    assert set(RESEARCH_STRUCTURED_FIELDS) == writable_columns("research")
    assert SELLER_TARGET_ENUM_FIELDS == writable_enum_values()


def test_registry_enum_values_are_valid_db_values() -> None:
    # 注册表声明的枚举取值必须是 baseline 里对应 check 约束的子集，
    # 否则解析写入会被 DB 拒。
    sql = BASELINE.read_text(encoding="utf-8")
    for column, values in writable_enum_values().items():
        match = re.search(column + r" = ANY \(ARRAY\[(.*?)\]\)", sql, re.S)
        if not match:
            continue  # 无 DB check 约束的列（如 information_status 若用文本）跳过
        allowed = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        extra = values - allowed
        assert not extra, f"{column} 注册表枚举含 DB 不接受的值：{sorted(extra)}"


def _infogroups_screening() -> set[str]:
    source = INFO_GROUPS.read_text(encoding="utf-8")
    fields = re.findall(r"\{\s*field:\s*'([a-z_0-9]+)',[^}]*?\}", source, re.S)
    marked = re.findall(r"\{\s*field:\s*'([a-z_0-9]+)',[^}]*?screening:\s*true[^}]*?\}", source, re.S)
    assert len(fields) > 40, "infoGroups 解析失败"
    return set(marked)


def test_screening_matches_the_frontend_badges() -> None:
    # 注册表的筛选列（去掉展示折叠列）应与 infoGroups 的「筛」角标一致，
    # 这样 R3a-2 把前端切到注册表时角标不变。
    registry = {ind.column for ind in SELLER_TARGET_INDICATORS if ind.screening and ind.fold_into is None}
    assert registry == _infogroups_screening()


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
    assert not missing, f"注册表引用了 seller_target 不存在的列：{sorted(missing)}"


def test_every_indicator_group_key_is_declared() -> None:
    group_keys = {group.key for group in GROUPS}
    used = {ind.group for ind in SELLER_TARGET_INDICATORS if ind.group is not None}
    assert used <= group_keys, f"指标引用了未声明的分组：{sorted(used - group_keys)}"
