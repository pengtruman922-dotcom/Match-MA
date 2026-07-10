"""Industry taxonomy lookups: closed L1 categories with L2/alias term mapping."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

FALLBACK_L1 = "其他"


def list_l1_terms(db: Session) -> list[str]:
    rows = db.execute(
        text(
            """
            select term
            from industry_taxonomy
            where team_id = :team_id
              and workspace_id = :workspace_id
              and level = 'l1'
              and active = true
            order by sort_order, term
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).scalars().all()
    return list(rows)


def industry_l1_prompt_list(db: Session) -> str:
    terms = list_l1_terms(db)
    return "、".join(terms) if terms else FALLBACK_L1


def resolve_l1(db: Session, term: Any) -> str | None:
    """Map a free-form industry term to its L1 category, or None when unknown."""
    text_value = str(term).strip() if term is not None else ""
    if not text_value:
        return None
    row = db.execute(
        text(
            """
            select l1_name
            from industry_taxonomy
            where team_id = :team_id
              and workspace_id = :workspace_id
              and active = true
              and lower(term) = lower(:term)
            limit 1
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "term": text_value},
    ).scalar_one_or_none()
    return str(row) if row else None


def normalize_l1_values(db: Session, values: Any) -> tuple[list[str], list[str]]:
    """Normalize a list of industry terms to unique L1 categories.

    Unmappable terms fall back to FALLBACK_L1 and are reported in notes so the
    review flow can surface 待归类 items.
    """
    if not isinstance(values, list):
        return [], []
    normalized: list[str] = []
    notes: list[str] = []
    for value in values:
        text_value = str(value).strip() if value is not None else ""
        if not text_value:
            continue
        l1_name = resolve_l1(db, text_value)
        if l1_name is None:
            notes.append(f"industry_unmapped:{text_value[:50]}")
            l1_name = FALLBACK_L1
        if l1_name not in normalized:
            normalized.append(l1_name)
    return normalized, notes


def normalize_excluded_terms(values: Any) -> list[str]:
    """Clean excluded-industry terms.

    Exclusions keep their original granularity: mapping 风电 up to its L1 能源
    would wrongly exclude the whole category, so terms are only trimmed and
    deduplicated. Matching happens at term level against both industry_l1 and
    the descriptive industry text.
    """
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        text_value = str(value).strip() if value is not None else ""
        if not text_value:
            continue
        term = text_value[:50]
        if term not in cleaned:
            cleaned.append(term)
    return cleaned
