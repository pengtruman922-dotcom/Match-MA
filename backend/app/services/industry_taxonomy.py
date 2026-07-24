"""Industry taxonomy lookups: closed L1 categories with L2/alias term mapping."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

DEFAULT_L1_TERMS = (
    "能源",
    "金融",
    "信息技术与通信",
    "房地产与建筑",
    "交通与物流",
    "文化与传媒",
    "制造与工业",
    "商贸与消费",
    "医药与健康",
    "教育与科研",
    "环保与公用事业",
    "农林牧渔",
    "军工",
    "商务与专业服务",
    "其他",
)

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
    # A missing seed must not silently collapse the model's closed taxonomy to
    # only "其他". Keep the canonical 15-way taxonomy available to parsers;
    # normal write-time resolution still validates values against the database.
    return "、".join(terms or DEFAULT_L1_TERMS)


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


def list_l2_terms(db: Session) -> list[str]:
    rows = db.execute(
        text(
            """
            select term
            from industry_taxonomy
            where team_id = :team_id
              and workspace_id = :workspace_id
              and level = 'l2'
              and active = true
            order by l1_name, sort_order, term
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).scalars().all()
    return list(rows)


def industry_l2_prompt_list(db: Session) -> str:
    terms = list_l2_terms(db)
    return "、".join(terms)


def normalize_l2_values(db: Session, values: Any) -> tuple[list[str], list[str]]:
    """Keep only terms that exist as L2 segments in the dictionary.

    Unlike L1 there is no fallback bucket: a term the dictionary does not carry
    as a segment (产品级说法如 醋酸下游 / 偏光膜) is dropped from the screening
    field and reported, so it stays a semantic matter for deep eval instead of
    silently narrowing SQL.
    """
    if not isinstance(values, list):
        return [], []
    known = {term.lower(): term for term in list_l2_terms(db)}
    normalized: list[str] = []
    notes: list[str] = []
    for value in values:
        text_value = str(value).strip() if value is not None else ""
        if not text_value:
            continue
        canonical = known.get(text_value.lower())
        if canonical is None:
            notes.append(f"industry_l2_unmapped:{text_value[:50]}")
            continue
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized, notes


def normalize_industry_pairs(db: Session, values: Any) -> tuple[list[dict[str, str]], list[str]]:
    """Canonicalize a target's industry pairs without losing L2 parentage.

    A target can span several L1 categories and several L2 tracks. Keeping
    two independent arrays makes an L2's parent unknowable, so the canonical
    value is an ordered, de-duplicated list of ``{"l1": ..., "l2": ...}``
    objects. A pair is also allowed to contain L1 only.
    """
    if not isinstance(values, list):
        return [], ["industry_pairs:not_a_list"]

    normalized: list[dict[str, str]] = []
    notes: list[str] = []
    for index, value in enumerate(values):
        if isinstance(value, dict):
            raw_l1 = value.get("l1") or value.get("industry_l1")
            raw_l2 = value.get("l2") or value.get("industry_l2")
        else:
            # A legacy list of terms is accepted as an L1/L2 candidate so old
            # prompt versions can be recovered without persisting raw terms.
            raw_l1 = value
            raw_l2 = value
        l1 = resolve_l1(db, raw_l1) if raw_l1 else None
        resolved_l2, l2_notes = normalize_l2_values(db, [raw_l2]) if raw_l2 else ([], [])
        l2 = resolved_l2[0] if resolved_l2 else None
        if raw_l1 and l1 is None and not l2:
            notes.append(f"industry_pairs[{index}]:l1_unmapped:{str(raw_l1)[:50]}")
        if raw_l2 and not l2 and not l1:
            notes.append(f"industry_pairs[{index}]:l2_unmapped:{str(raw_l2)[:50]}")
        if l2:
            l2_l1 = resolve_l1(db, l2)
            if not l2_l1:
                notes.append(f"industry_pairs[{index}]:l2_missing_parent:{l2[:50]}")
                l2 = None
            else:
                if l1 and l1 != l2_l1:
                    notes.append(f"industry_pairs[{index}]:l2_parent_overrode_l1")
                l1 = l2_l1
        if not l1:
            continue
        pair: dict[str, str] = {"l1": l1}
        if l2:
            pair["l2"] = l2
        if pair not in normalized:
            normalized.append(pair)
    return normalized, notes


def load_term_levels(db: Session) -> dict[str, tuple[str, str]]:
    """Map every dictionary term to ``(level, l1_name)`` in one query.

    Screening compares hundreds of candidates per request, so per-term lookups
    are loaded once and resolved in memory.
    """
    rows = db.execute(
        text(
            """
            select term, level, l1_name
            from industry_taxonomy
            where team_id = :team_id
              and workspace_id = :workspace_id
              and active = true
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return {str(row["term"]).strip().lower(): (str(row["level"]), str(row["l1_name"])) for row in rows}


def classify_terms(values: Any, term_levels: dict[str, tuple[str, str]]) -> dict[str, list[str]]:
    """Split free-form industry terms into L1 / L2 / unresolved buckets.

    Exclusions are stored at whatever granularity the buyer wrote them, so the
    level has to be recovered here: an L1 term is compared against the target's
    ``industry_l1`` and an L2 term against ``industry_l2``. Anything the
    dictionary does not know falls through to descriptive text matching.
    """
    buckets: dict[str, list[str]] = {"l1": [], "l2": [], "unresolved": []}
    if not isinstance(values, list):
        return buckets
    for value in values:
        term = str(value).strip() if value is not None else ""
        if not term:
            continue
        entry = term_levels.get(term.lower())
        if entry is None:
            bucket = "unresolved"
        elif entry[0] == "l1":
            bucket = "l1"
        else:
            # L2 terms and aliases both screen at the segment level; an alias
            # pointing at an L1 still only tells us the L1 name, so treat the
            # written term as the segment and let exact matching decide.
            bucket = "l2" if entry[0] == "l2" else "unresolved"
        if term not in buckets[bucket]:
            buckets[bucket].append(term)
    return buckets


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
