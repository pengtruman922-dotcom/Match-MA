"""The 「筛」 badge on the target info page must match what actually screens.

The badge tells a consultant which blanks are worth filling first — a missing
profit figure can keep a target out of a buyer's pool, a missing description
only changes deep-eval wording. That only holds while the badge tracks the
scorer, and nothing in the type system connects a TSX file to
recommendation_flow. This test is that connection.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INFO_GROUPS = REPO_ROOT / "frontend/src/features/targets/infoGroups.ts"
RECOMMENDATION_FLOW = REPO_ROOT / "backend/app/services/recommendation_flow.py"

FIELD_ENTRY = re.compile(r"\{\s*field:\s*'([a-z_0-9]+)',[^}]*?\}", re.S)

# 页面上合并展示、但打分器分别读取的字段。
DISPLAY_ALIASES = {
    "headquarter_province": {"headquarter_province", "headquarter_city"},
    "transfer_ratio_min": {"transfer_ratio_min", "transfer_ratio_max"},
}

# 打分器读取、但不作为标的自身字段展示的中间量。
NOT_DISPLAYED_AS_FIELDS = {
    # 定性摘要进画像栏目而不是字段格
    "risk_summary",
    "gap_summary",
    # 页面展示规范化后的 L1/L2，原文字段本身不参与筛选
    "industry_primary",
    "industry_secondary",
}


def _info_fields() -> list[tuple[str, bool]]:
    source = INFO_GROUPS.read_text(encoding="utf-8")
    return [
        (match.group(1), "screening: true" in match.group(0))
        for match in FIELD_ENTRY.finditer(source)
    ]


def _screening_fields() -> set[str]:
    """Fields the scorer reads off a target row."""
    source = RECOMMENDATION_FLOW.read_text(encoding="utf-8")
    fields = set(re.findall(r"target\.get\(\"([a-z_0-9]+)\"", source))
    # 能力维度经 CAPABILITY_DIMENSIONS 映射读取，不是直接 target.get
    fields |= set(re.findall(r"\(\s*\"[a-z_]+\",\s*\"([a-z_0-9]+)\",\s*[\d.]+,", source))
    return fields


def test_info_group_source_files_exist() -> None:
    assert INFO_GROUPS.exists()
    assert RECOMMENDATION_FLOW.exists()


def test_every_field_declares_a_column_name() -> None:
    fields = _info_fields()
    assert len(fields) > 40, "字段解析失败，正则可能与 infoGroups.ts 的写法脱节"
    assert len({name for name, _ in fields}) == len(fields), "同一列名重复出现"


@pytest.mark.parametrize("field_name,marked", _info_fields())
def test_screening_badge_matches_the_scorer(field_name: str, marked: bool) -> None:
    screening = _screening_fields()
    covered = DISPLAY_ALIASES.get(field_name, {field_name})
    actually_screens = bool(covered & screening)

    if marked and not actually_screens:
        pytest.fail(
            f"{field_name} 标了「筛」，但 recommendation_flow 并不读取它。"
            "角标会让顾问把时间花在不影响召回的字段上。"
        )
    if actually_screens and not marked and field_name not in NOT_DISPLAYED_AS_FIELDS:
        pytest.fail(
            f"{field_name} 参与筛选/打分，但页面没标「筛」。"
            "顾问看不出补它能改善召回。"
        )


def test_scoring_fields_are_all_either_displayed_or_explicitly_excluded() -> None:
    """打分器新增维度时，这条会提醒把它放进信息页或写进豁免清单。"""
    displayed = set()
    for name, _ in _info_fields():
        displayed |= DISPLAY_ALIASES.get(name, {name})

    missing = _screening_fields() - displayed - NOT_DISPLAYED_AS_FIELDS
    assert not missing, f"打分器读取但信息页没有展示的字段：{sorted(missing)}"
