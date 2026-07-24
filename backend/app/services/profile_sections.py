"""Per-group supplementary information that structured fields cannot express.

Three layers feed a recommendation. Canonical facts live in the entity's own
columns and tags. This module owns one “其他” supplementary block per
information group
per entity, each with its own source and as-of date — and builds the third:
the trimmed text actually sent to deep eval, budgeted per section rather than
sliced off the front of one long document.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import write_action_log
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID

# 更新记录里画像字段的前缀。画像不是实体的列，靠这个前缀和普通字段区分，
# 回滚时据此走 entity_profile_section 的版本恢复而不是 update 某一列。
PROFILE_SECTION_FIELD_PREFIX = "profile_section."

# 栏目由指标对照表倒推：每一栏都有明确的买家诉求作为对手方，
# 没有对手方的维度不设栏，避免画像变成又一份越写越长的公司简介。
PROFILE_SECTIONS: tuple[tuple[str, str, int], ...] = (
    # (section_code, 中文栏目名, 送深评时的字符预算)
    ("identity", "身份与地区", 200),
    ("business_product", "业务与产品", 400),
    ("tech_team", "技术与团队能力", 300),
    ("ops_quality", "经营质量", 300),
    ("deal_terms", "交易属性与出售诉求", 400),
)

PROFILE_SECTION_CODES = tuple(code for code, _, _ in PROFILE_SECTIONS)
PROFILE_SECTION_ALIASES = {
    "chain_position": "business_product",
    "sell_intent_risk": "deal_terms",
}

PROFILE_SECTION_LABELS = {code: label for code, label, _ in PROFILE_SECTIONS}

PROFILE_SECTION_BUDGETS = {code: budget for code, _, budget in PROFILE_SECTIONS}

PROFILE_TOTAL_BUDGET = sum(PROFILE_SECTION_BUDGETS.values())

PROFILE_CLAUSE_SPLIT_PATTERN = re.compile(r"[，,；;。\n]+")
DEAL_TERMS_NOISE_TERMS = ("融资阶段", "融资规模", "融资金额", "估值", "营业收入", "营收", "净利润")

INFO_STATUS_LABELS = {
    "not_found": "（暂无信息）",
    "not_applicable": "（不适用）",
}


def normalize_profile_section_items(values: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate profile sections emitted by a parser or research node.

    Profile text is deliberately qualitative. Empty rows, unknown section
    codes and non-object values are dropped before they can reach the profile
    table; duplicate sections keep the first supported claim so one LLM call
    cannot overwrite itself nondeterministically.
    """
    if not isinstance(values, list):
        return [], [] if values is None else ["profile_sections:not_a_list"]
    normalized: list[dict[str, Any]] = []
    notes: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            notes.append(f"profile_sections[{index}]:not_an_object")
            continue
        raw_section_code = str(value.get("section_code") or "").strip()
        section_code = PROFILE_SECTION_ALIASES.get(raw_section_code, raw_section_code)
        if section_code not in PROFILE_SECTION_CODES:
            notes.append(f"profile_sections[{index}]:unknown_section:{section_code[:50]}")
            continue
        if section_code in seen:
            notes.append(f"profile_sections[{index}]:duplicate_section:{section_code}")
            continue
        content_text = str(value.get("content_text") or "").strip()
        if not content_text:
            notes.append(f"profile_sections[{index}]:empty_content:{section_code}")
            continue
        cleaned_content = _clean_profile_content(section_code, content_text)
        if cleaned_content != content_text:
            notes.append(f"profile_sections[{index}]:removed_cross_layer_noise:{section_code}")
        if not cleaned_content:
            notes.append(f"profile_sections[{index}]:empty_after_cleaning:{section_code}")
            continue
        raw_as_of_date = str(value.get("as_of_date") or "").strip()[:10]
        as_of_date = None
        if raw_as_of_date:
            try:
                as_of_date = date.fromisoformat(raw_as_of_date).isoformat()
            except ValueError:
                notes.append(
                    f"profile_sections[{index}]:invalid_as_of_date:{raw_as_of_date}"
                )
        normalized.append(
            {
                "section_code": section_code,
                "content_text": cleaned_content[:2000],
                "source_excerpt": str(value.get("source_excerpt") or "").strip()[:2000] or None,
                "as_of_date": as_of_date,
            }
        )
        seen.add(section_code)
    return normalized, notes


def _clean_profile_content(section_code: str, content_text: str) -> str:
    """Keep profile sections qualitative and dimension-specific.

    The model occasionally repeats financing/valuation facts in deal_terms or
    treats financial investors as members of the operating team. Those facts
    remain in the canonical/document layer and should not pollute semantic
    matching dimensions.
    """
    if section_code not in {"deal_terms", "tech_team"}:
        return content_text
    kept: list[str] = []
    for clause in PROFILE_CLAUSE_SPLIT_PATTERN.split(content_text):
        clause = clause.strip()
        if not clause:
            continue
        if section_code == "deal_terms" and any(term in clause for term in DEAL_TERMS_NOISE_TERMS):
            continue
        if section_code == "tech_team" and "股东" in clause and not any(
            term in clause for term in ("团队", "创始人", "高管", "管理层")
        ):
            continue
        kept.append(clause)
    return "；".join(kept)


def load_profile_sections(
    db: Session,
    *,
    entity_type: str,
    entity_ids: list[Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Load the current section per entity, keyed by entity id then section.

    Accepting supersedes, so one accepted row per section is the normal state.
    The ordering is a safety net for rows that predate that rule, and it sorts
    by when the revision was accepted rather than by as_of_date — a researched
    date is often the page's publication date rather than the fact's, and it
    must not decide which revision the consultant sees.
    """
    if not entity_ids:
        return {}
    rows = db.execute(
        text(
            """
            select
              entity_id, section_code, info_status, content_text,
              source_type, source_url, as_of_date, updated_at
            from entity_profile_section
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = any(:entity_ids)
              and deleted_at is null
              and review_status in ('accepted', 'auto_accepted')
            order by entity_id, section_code, updated_at desc
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
    review_status: str = "accepted",
    user_id: Any = None,
) -> dict[str, Any]:
    """Insert a new revision of a section rather than overwriting the old one.

    Accepting always supersedes the current revision. Letting as_of_date decide
    which revision is current makes accepting a proposal a silent no-op
    whenever the incoming date is missing or older than what is on file — the
    consultant clicks 确认 and the panel does not change. Whoever accepted last
    wins; as_of_date stays a display and deep-eval signal only.
    """
    if section_code not in PROFILE_SECTION_CODES:
        raise ValueError(f"Unknown profile section: {section_code}")
    superseded = db.execute(
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
            returning id, info_status, content_text
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
    ).mappings().all()
    row = db.execute(
        text(
            """
            insert into entity_profile_section (
              team_id, workspace_id, entity_type, entity_id, section_code,
              info_status, content_text, source_type, source_url, source_title,
              source_excerpt, as_of_date, review_status,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :entity_type, :entity_id, :section_code,
              :info_status, :content_text, :source_type, :source_url, :source_title,
              :source_excerpt, :as_of_date, :review_status,
              :user_id, :user_id
            )
            returning
              id, entity_type, entity_id, section_code, info_status, content_text,
              source_type, source_url, source_title, source_excerpt,
              as_of_date::text as as_of_date, review_status,
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
            "review_status": review_status,
            "user_id": user_id,
        },
    ).mappings().one()
    previous = dict(superseded[0]) if superseded else None
    return {**dict(row), "superseded": previous}


def apply_profile_section(
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
    review_status: str = "accepted",
    user_id: Any = None,
    log_source_type: str = "direct_api",
    log_source_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a section and record it where 更新记录 can see it.

    Profile sections live in their own table, so nothing about them reached
    action_application_log — a researched section changed the profile with no
    entry in the update timeline and no way to undo it. Since research is what
    writes most of them, that audit trail is the thing making automatic
    acceptance safe rather than merely convenient.
    """
    row = upsert_profile_section(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        section_code=section_code,
        info_status=info_status,
        content_text=content_text,
        source_type=source_type,
        source_url=source_url,
        source_title=source_title,
        source_excerpt=source_excerpt,
        as_of_date=as_of_date,
        review_status=review_status,
        user_id=user_id,
    )
    previous = row.get("superseded")
    write_action_log(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        field_path=f"{PROFILE_SECTION_FIELD_PREFIX}{section_code}",
        old_value=_profile_log_value(previous),
        new_value=_profile_log_value(row),
        source_type=log_source_type,
        source_id=log_source_id,
        business_update_id=business_update_id,
        applied_by=user_id,
        metadata_json={
            "section_code": section_code,
            "section_label": PROFILE_SECTION_LABELS.get(section_code, section_code),
            "profile_section_id": str(row["id"]),
            "superseded_profile_section_id": str(previous["id"]) if previous else None,
            "source_url": source_url,
            **(extra_metadata or {}),
        },
    )
    return row


def _profile_log_value(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "info_status": row.get("info_status"),
        "content_text": row.get("content_text"),
    }
