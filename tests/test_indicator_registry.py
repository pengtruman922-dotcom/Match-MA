"""The registry must reproduce the five sources it will replace.

Until each consumer is switched to read from the registry, the old source stays
authoritative. These tests pin the registry to every one of those sources, so
the registry cannot drift from reality while the migration is in flight — and
once a consumer is switched, the same assertion guarantees the switch changed
no behaviour.
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


def test_parse_whitelist_matches_the_registry() -> None:
    assert writable_columns("parse") == set(SELLER_TARGET_CHANGE_FIELDS)


def test_research_whitelist_matches_the_registry() -> None:
    assert writable_columns("research") == set(RESEARCH_STRUCTURED_FIELDS)


def test_writable_enum_values_match_the_parser() -> None:
    assert writable_enum_values() == {k: set(v) for k, v in SELLER_TARGET_ENUM_FIELDS.items()}


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
