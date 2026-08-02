"""买家需求行业字段的字典对齐。

`industries_json` / `industry_l2_json` / `excluded_industries_json` 都是**封闭词表
的筛选列** —— 查询用 ``industries_json ? :industry``，字典外的词写进去等于没写，
但页面上看着像有筛选条件，实际把全部标的挡在门外。

所以这三个列只能通过这里写。字典装不下的说法不丢弃，落进
``industry_focus_tags_json``（``default_effect="deep_eval"``），交给深评理解。

买家需求有**两个**写入者：新建解析（`buyer_intent_parse`）和带附件时的
`business_update_extractor` → `extracted_action_apply`。两边必须用同一套政策，
否则「带不带附件」会决定行业字段要不要过字典 —— 这正是 2026-08-01 实测到的问题。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.services.industry_taxonomy import (
    classify_terms,
    load_term_levels,
    normalize_excluded_terms,
    normalize_l1_values,
    normalize_l2_values,
    resolve_l1,
)

MAX_FOCUS_TAGS = 50
MAX_FOCUS_TAG_CHARS = 80


def normalize_buyer_intent_industry_changes(db: Session, changes: dict[str, Any]) -> list[str]:
    """就地把行业字段映射到封闭字典，返回可读的处理说明。

    ``changes`` 被原地修改：映射得上的留在筛选列，映射不上的挪进
    ``industry_focus_tags_json``。返回的 notes 只用于留痕，调用方可以忽略。
    """
    notes: list[str] = []
    semantic_focus_terms: list[str] = []
    for value in changes.get("industry_focus_tags_json") or []:
        term = str(value or "").strip()
        if term and term not in semantic_focus_terms:
            semantic_focus_terms.append(term)
    if "industries_json" in changes:
        raw_l1 = [str(value).strip() for value in changes["industries_json"] if str(value or "").strip()]
        normalized, industry_notes = normalize_l1_values(
            db,
            changes["industries_json"],
            fallback_unmapped=False,
        )
        notes.extend(industry_notes)
        if normalized:
            changes["industries_json"] = normalized
        else:
            changes.pop("industries_json", None)
        mapped_l1 = set(normalized)
        for term in raw_l1:
            if resolve_l1(db, term) is None and term not in mapped_l1 and term not in semantic_focus_terms:
                semantic_focus_terms.append(term)
    if "industry_l2_json" in changes:
        # L2 是筛选字段，只保留字典里真实存在的赛道；写不进字典的细分方向
        # （醋酸下游、偏光膜这类产品级说法）留给深评，不污染 SQL。
        raw_l2 = [str(value).strip() for value in changes["industry_l2_json"] if str(value or "").strip()]
        normalized_l2, l2_notes = normalize_l2_values(db, raw_l2)
        notes.extend(l2_notes)
        if normalized_l2:
            changes["industry_l2_json"] = normalized_l2
        else:
            changes.pop("industry_l2_json", None)
        for term in raw_l2:
            if term not in normalized_l2 and term not in semantic_focus_terms:
                semantic_focus_terms.append(term)
    if "excluded_industries_json" in changes:
        cleaned = normalize_excluded_terms(changes["excluded_industries_json"])
        classified = classify_terms(cleaned, load_term_levels(db))
        effective_exclusions = classified["l1"] + classified["l2"]
        for term in classified["unresolved"]:
            notes.append(f"excluded_industry_unmapped:{term[:50]}")
            if term not in semantic_focus_terms:
                semantic_focus_terms.append(term)
        if effective_exclusions:
            changes["excluded_industries_json"] = effective_exclusions
        else:
            changes.pop("excluded_industries_json", None)
    if "industry_focus_tags_json" in changes:
        raw_tags = changes["industry_focus_tags_json"]
        tags: list[str] = []
        if isinstance(raw_tags, list):
            for value in raw_tags:
                tag = str(value or "").strip()[:MAX_FOCUS_TAG_CHARS]
                if tag and tag not in tags:
                    tags.append(tag)
        if tags:
            changes["industry_focus_tags_json"] = tags
        else:
            changes.pop("industry_focus_tags_json", None)
    if semantic_focus_terms:
        changes["industry_focus_tags_json"] = semantic_focus_terms[:MAX_FOCUS_TAGS]
    if "industries_json" not in changes and changes.get("industry_primary"):
        l1_name = resolve_l1(db, changes["industry_primary"])
        if l1_name:
            changes["industries_json"] = [l1_name]
    return notes
