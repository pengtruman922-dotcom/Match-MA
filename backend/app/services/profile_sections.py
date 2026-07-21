"""Matching profile sections: the qualitative layer screening cannot express.

Three layers feed a recommendation. Canonical facts live in the entity's own
columns and tags. This module owns the middle layer — six qualitative sections
per entity, each with its own source and as-of date — and builds the third:
the trimmed text actually sent to deep eval, budgeted per section rather than
sliced off the front of one long document.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

# 栏目由指标对照表倒推：每一栏都有明确的买家诉求作为对手方，
# 没有对手方的维度不设栏，避免画像变成又一份越写越长的公司简介。
PROFILE_SECTIONS: tuple[tuple[str, str, int], ...] = (
    # (section_code, 中文栏目名, 送深评时的字符预算)
    ("business_product", "业务与产品", 400),
    ("chain_position", "产业链位置与行业地位", 400),
    ("tech_team", "技术与团队能力", 300),
    ("ops_quality", "经营质量", 300),
    ("deal_terms", "交易属性与配合度", 300),
    ("sell_intent_risk", "出售诉求与风险缺口", 200),
)

PROFILE_SECTION_CODES = tuple(code for code, _, _ in PROFILE_SECTIONS)

PROFILE_SECTION_LABELS = {code: label for code, label, _ in PROFILE_SECTIONS}

PROFILE_SECTION_BUDGETS = {code: budget for code, _, budget in PROFILE_SECTIONS}

PROFILE_TOTAL_BUDGET = sum(PROFILE_SECTION_BUDGETS.values())

INFO_STATUS_LABELS = {
    "not_found": "（暂无信息）",
    "not_applicable": "（不适用）",
}


def load_profile_sections(
    db: Session,
    *,
    entity_type: str,
    entity_ids: list[Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Load the current section per entity, keyed by entity id then section.

    Several rows may exist for one section — different periods or sources that
    the research flow deliberately keeps side by side — so the newest accepted
    row wins.
    """
    if not entity_ids:
        return {}
    rows = db.execute(
        text(
            """
            select
              entity_id, section_code, info_status, content_text,
              source_type, source_url, as_of_date, confidence, updated_at
            from entity_profile_section
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = any(:entity_ids)
              and deleted_at is null
              and review_status in ('accepted', 'auto_accepted')
            order by entity_id, section_code,
                     as_of_date desc nulls last, updated_at desc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_ids": [str(value) for value in entity_ids],
        },
    ).mappings().all()

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        entity_key = str(row["entity_id"])
        sections = grouped.setdefault(entity_key, {})
        # 已排序，同一栏目的第一行就是当前值
        sections.setdefault(row["section_code"], dict(row))
    return grouped


def render_profile_text(sections: dict[str, dict[str, Any]] | None) -> str:
    """Compose the deep-eval profile with a budget per section.

    Cutting one long document at a fixed offset drops whichever sections happen
    to be last; budgeting per section keeps every dimension represented even
    when one of them is verbose.
    """
    if not sections:
        return ""
    parts: list[str] = []
    for code, label, budget in PROFILE_SECTIONS:
        row = sections.get(code)
        if not row:
            continue
        status = str(row.get("info_status") or "filled")
        if status != "filled":
            parts.append(f"【{label}】{INFO_STATUS_LABELS.get(status, '（暂无信息）')}")
            continue
        content = str(row.get("content_text") or "").strip()
        if not content:
            continue
        trimmed = content[:budget]
        if len(content) > budget:
            trimmed += "…"
        parts.append(f"【{label}】{trimmed}")
    return "\n".join(parts)


def profile_coverage(sections: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Which sections carry usable content, and which are still open questions."""
    filled: list[str] = []
    missing: list[str] = []
    for code, label, _ in PROFILE_SECTIONS:
        row = (sections or {}).get(code)
        if row and str(row.get("info_status") or "filled") == "filled" and str(row.get("content_text") or "").strip():
            filled.append(label)
        elif row and str(row.get("info_status")) == "not_applicable":
            continue
        else:
            missing.append(label)
    return {"filled_sections": filled, "missing_sections": missing}


def buyer_party_fact_block(db: Session, buyer_party_id: Any) -> str:
    """A few lines of the buyer's own business, for synergy questions.

    Requirements like 北控's "与现有业务有关联性" or 北京工控's "强链补链" cannot be
    judged without knowing what the buyer already does. Identity fields are left
    out — the block exists to support the judgement, not to name the buyer.
    """
    if not buyer_party_id:
        return ""
    row = db.execute(
        text(
            """
            select buyer_type, group_name, region_province, main_business,
                   capital_strength_summary, profile_summary
            from buyer_party
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        return ""
    lines = [
        f"买方类型：{row['buyer_type']}" if row["buyer_type"] else None,
        f"所属集团：{row['group_name']}" if row["group_name"] else None,
        f"所在地区：{row['region_province']}" if row["region_province"] else None,
        f"现有主业：{row['main_business']}" if row["main_business"] else None,
        f"资金实力：{row['capital_strength_summary']}" if row["capital_strength_summary"] else None,
        f"产业布局：{row['profile_summary']}" if row["profile_summary"] else None,
    ]
    body = "\n".join(line for line in lines if line)
    return f"【买方自身情况（供协同性判断）】\n{body}" if body else ""


def upsert_profile_section(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    section_code: str,
    info_status: str,
    content_text: str | None,
    source_type: str | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
    source_excerpt: str | None = None,
    as_of_date: Any = None,
    confidence: float | None = None,
    review_status: str = "accepted",
    user_id: Any = None,
) -> dict[str, Any]:
    """Insert a new revision of a section rather than overwriting the old one."""
    if section_code not in PROFILE_SECTION_CODES:
        raise ValueError(f"Unknown profile section: {section_code}")
    db.execute(
        text(
            """
            update entity_profile_section
            set deleted_at = now(), updated_at = now(), updated_by = :user_id
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
              and section_code = :section_code
              and deleted_at is null
              and review_status in ('accepted', 'auto_accepted')
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "section_code": section_code,
            "user_id": user_id,
        },
    )
    row = db.execute(
        text(
            """
            insert into entity_profile_section (
              team_id, workspace_id, entity_type, entity_id, section_code,
              info_status, content_text, source_type, source_url, source_title,
              source_excerpt, as_of_date, confidence, review_status,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :entity_type, :entity_id, :section_code,
              :info_status, :content_text, :source_type, :source_url, :source_title,
              :source_excerpt, :as_of_date, :confidence, :review_status,
              :user_id, :user_id
            )
            returning
              id, entity_type, entity_id, section_code, info_status, content_text,
              source_type, source_url, source_title, source_excerpt,
              as_of_date::text as as_of_date, confidence, review_status,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "section_code": section_code,
            "info_status": info_status,
            "content_text": content_text,
            "source_type": source_type,
            "source_url": source_url,
            "source_title": source_title,
            "source_excerpt": source_excerpt,
            "as_of_date": as_of_date,
            "confidence": confidence,
            "review_status": review_status,
            "user_id": user_id,
        },
    ).mappings().one()
    return dict(row)
