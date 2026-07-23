"""Applying a research proposal, from either the review UI or the agent itself.

Research accepts its own proposals now, so the writeback path can no longer
live in the route layer and raise HTTPException — the job worker needs the same
validation, the same audit log and the same field-source trail as a consultant
clicking 确认. The route wraps ResearchApplyError back into a 4xx.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.registry.indicators import writable_columns
from backend.app.services.field_writer import WriteProvenance, write_seller_target_fields
from backend.app.services.industry_taxonomy import normalize_l2_values, resolve_l1
from backend.app.services.profile_sections import apply_profile_section
from backend.app.services.search_docs import create_search_doc_rebuild_job

LISTED_STATUS_VALUES = {"listed", "unlisted", "pre_ipo", "unknown"}

# Which canonical facts research may propose. Derived from the indicator
# registry (the single source). No numeric fields there by design: a wrong
# industry label is visible on the page and cheap to undo, a wrong revenue
# figure is neither.
RESEARCH_STRUCTURED_FIELDS = writable_columns("research")


class ResearchApplyError(ValueError):
    """A proposal that cannot be written back as-is."""


def apply_research_proposal(
    db: Session,
    proposal: dict[str, Any],
    *,
    user_id: UUID,
    review_status: str = "accepted",
) -> None:
    if proposal["proposal_kind"] == "profile_section":
        _apply_profile_proposal(db, proposal, user_id=user_id, review_status=review_status)
        return
    _apply_structured_fact_proposal(db, proposal, user_id=user_id, review_status=review_status)


def _apply_profile_proposal(
    db: Session,
    proposal: dict[str, Any],
    *,
    user_id: UUID,
    review_status: str,
) -> None:
    value = proposal.get("proposed_value_json") or {}
    content = str(value.get("content_text") or "").strip()
    # 调研查过但确实没有公开信息时提议 not_found —— 这是被确认的缺口，
    # 和「从未调研」在推荐里含义不同，因此是一条内容为空的合法建议。
    info_status = "not_found" if str(value.get("info_status")) == "not_found" else "filled"
    if not proposal.get("section_code") or (info_status == "filled" and not content):
        raise ResearchApplyError("画像建议内容为空。")
    apply_profile_section(
        db,
        entity_type="seller_target",
        entity_id=proposal["entity_id"],
        section_code=str(proposal["section_code"]),
        info_status=info_status,
        content_text=content or None,
        source_type=proposal.get("source_type"),
        source_url=proposal.get("source_url"),
        source_title=proposal.get("source_title"),
        source_excerpt=proposal.get("source_excerpt"),
        as_of_date=proposal.get("as_of_date"),
        confidence=proposal.get("confidence"),
        review_status=review_status,
        user_id=user_id,
        log_source_type="research_proposal",
        log_source_id=proposal.get("id"),
        extra_metadata={
            "research_proposal_id": str(proposal["id"]),
            "conflict_kind": proposal.get("conflict_kind"),
            "sources": value.get("sources") or [],
            "auto_accepted": review_status == "auto_accepted",
        },
    )


def _apply_structured_fact_proposal(
    db: Session,
    proposal: dict[str, Any],
    *,
    user_id: UUID,
    review_status: str,
) -> None:
    field_path = str(proposal.get("field_path") or "")
    if field_path not in RESEARCH_STRUCTURED_FIELDS:
        raise ResearchApplyError("不支持该基础事实字段。")
    raw_value = (proposal.get("proposed_value_json") or {}).get("value")
    new_value = normalize_structured_fact(db, field_path, raw_value)
    write_seller_target_fields(
        db,
        proposal["entity_id"],
        {field_path: new_value},
        provenance=WriteProvenance(
            source_type="research_proposal",
            actor_user_id=user_id,
            source_id=proposal["id"],
            field_source_label=str(proposal.get("source_title") or proposal.get("source_url") or "公开调研"),
            confidence=proposal.get("confidence"),
            review_status=review_status,
            source_context={
                "source_url": proposal.get("source_url"),
                "source_excerpt": proposal.get("source_excerpt"),
            },
            log_metadata={
                "source_url": proposal.get("source_url"),
                "source_title": proposal.get("source_title"),
                "conflict_kind": proposal.get("conflict_kind"),
                "auto_accepted": review_status == "auto_accepted",
            },
        ),
        search_doc_source="research_proposal_accept",
    )


def normalize_structured_fact(db: Session, field_path: str, value: Any) -> Any:
    """Validate a proposed fact against the same dictionaries a human write uses.

    Industry values are the reason this matters: they drive SQL screening, so a
    label outside the taxonomy silently removes the target from the pools it
    belongs in rather than showing up as a bad value on the page.
    """
    text_value = str(value or "").strip()
    if not text_value:
        raise ResearchApplyError("建议值为空。")
    if field_path == "listed_status":
        if text_value not in LISTED_STATUS_VALUES:
            raise ResearchApplyError("上市状态值无效。")
        return text_value
    if field_path == "industry_l1":
        resolved = resolve_l1(db, text_value)
        if resolved is None:
            raise ResearchApplyError("一级行业不在字典中。")
        return resolved
    if field_path == "industry_l2":
        resolved_values, _ = normalize_l2_values(db, [text_value])
        if not resolved_values:
            raise ResearchApplyError("二级行业不在字典中。")
        return resolved_values[0]
    limit = 300 if field_path in {"target_subject_name", "business_summary"} else 120
    return text_value[:limit]
