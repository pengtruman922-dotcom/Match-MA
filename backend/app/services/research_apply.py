"""Applying a research proposal, from either the review UI or the agent itself.

Research accepts its own proposals now, so the writeback path can no longer
live in the route layer and raise HTTPException — the job worker needs the same
validation, the same audit log and the same field-source trail as a consultant
clicking 确认. The route wraps ResearchApplyError back into a 4xx.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.registry.indicators import Indicator, indicators_for, writable_columns
from backend.app.services.field_writer import (
    FieldWriteError,
    WriteProvenance,
    write_seller_target_fields,
)
from backend.app.services.industry_taxonomy import normalize_industry_pairs, normalize_l2_values, resolve_l1
from backend.app.services.profile_sections import apply_profile_section
from backend.app.services.search_docs import create_search_doc_rebuild_job

LISTED_STATUS_VALUES = {"listed", "unlisted", "pre_ipo", "unknown"}

# Which canonical facts research may propose. Derived from the indicator
# registry (the single source). No numeric fields there by design: a wrong
# industry label is visible on the page and cheap to undo, a wrong revenue
# figure is neither.
# Both values are derived from each core financial claim's period metadata.
# Asking the mapper to emit them as standalone facts creates a duplicate
# proposal that can disagree with the metric it describes.
RESEARCH_INTERNAL_FIELDS = {"financial_period_end_date", "financial_period_label"}
RESEARCH_STRUCTURED_FIELDS = writable_columns("research")
RESEARCH_AGENT_STRUCTURED_FIELDS = RESEARCH_STRUCTURED_FIELDS - RESEARCH_INTERNAL_FIELDS

CORE_FINANCIAL_FIELDS = {
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_assets_yuan",
    "current_debt_ratio",
    "current_operating_cash_flow_yuan",
}


class ResearchApplyError(ValueError):
    """A proposal that cannot be written back as-is."""


_PER_SHARE_CASH_FLOW_RE = re.compile(
    r"(?:每股[^，。；;]{0,20}现金流|现金流[^，。；;]{0,20}每股|(?:元|万元)\s*[/／]\s*股)",
    re.IGNORECASE,
)


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
    new_value = normalize_structured_fact(
        db,
        field_path,
        raw_value,
        source_excerpt=proposal.get("source_excerpt"),
    )
    # FieldWriteError 和 ResearchApplyError 是兄弟类，不翻译的话它会越过
    # 调用方的 per-claim 捕获，一个越界的负债率就能把整轮调研连同其他建议一起回滚。
    try:
        _write_structured_fact(
            db,
            proposal,
            field_path=field_path,
            new_value=new_value,
            user_id=user_id,
            review_status=review_status,
        )
    except FieldWriteError as exc:
        raise ResearchApplyError(str(exc)) from exc


def _write_structured_fact(
    db: Session,
    proposal: dict[str, Any],
    *,
    field_path: str,
    new_value: Any,
    user_id: UUID,
    review_status: str,
) -> None:
    changes: dict[str, Any] = {field_path: new_value}
    if field_path in CORE_FINANCIAL_FIELDS:
        as_of_date = proposal.get("as_of_date")
        try:
            period_end = as_of_date if isinstance(as_of_date, date) else date.fromisoformat(str(as_of_date or ""))
        except (TypeError, ValueError) as exc:
            raise ResearchApplyError(f"{field_path} 缺少合法财务期间截止日。") from exc
        changes["financial_period_end_date"] = period_end
        period_label = str(proposal.get("period_label") or "").strip()
        if period_label:
            changes["financial_period_label"] = period_label

    write_seller_target_fields(
        db,
        proposal["entity_id"],
        changes,
        provenance=WriteProvenance(
            source_type="research_proposal",
            actor_user_id=user_id,
            source_id=proposal["id"],
            field_source_label=str(proposal.get("source_title") or proposal.get("source_url") or "公开调研"),
            review_status=review_status,
            source_context={
                "source_url": proposal.get("source_url"),
                "source_excerpt": proposal.get("source_excerpt"),
                "source_title": proposal.get("source_title"),
                "period_label": proposal.get("period_label"),
                "as_of_date": str(proposal.get("as_of_date") or "") or None,
                "research_job_id": str(proposal.get("job_id") or "") or None,
            },
            log_metadata={
                "source_url": proposal.get("source_url"),
                "source_title": proposal.get("source_title"),
                "conflict_kind": proposal.get("conflict_kind"),
                "auto_accepted": review_status == "auto_accepted",
            },
            write_unchanged_field_source=proposal.get("conflict_kind") == "consistent",
        ),
        search_doc_source="research_proposal_accept",
    )


# 中文财报的金额单位。调研 agent 被要求原样交出数字和单位，不自己折算 ——
# 差一个数量级是一万倍，进了筛选完全看不出来，这种确定性换算必须由代码做。
MONEY_UNIT_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "元": Decimal(1),
    "圆": Decimal(1),
    "人民币": Decimal(1),
    "千": Decimal(10) ** 3,
    "千元": Decimal(10) ** 3,
    "万": Decimal(10) ** 4,
    "万元": Decimal(10) ** 4,
    "十万": Decimal(10) ** 5,
    "百万": Decimal(10) ** 6,
    "千万": Decimal(10) ** 7,
    "亿": Decimal(10) ** 8,
    "亿元": Decimal(10) ** 8,
    "十亿": Decimal(10) ** 9,
    "百亿": Decimal(10) ** 10,
    "万亿": Decimal(10) ** 12,
}


def _indicator(field_path: str) -> Indicator | None:
    return next(
        (item for item in indicators_for("seller_target") if item.column == field_path),
        None,
    )


def _money_to_yuan(field_path: str, value: Any) -> Decimal:
    """Turn `{"value": 83200, "unit": "万元"}` — or a bare number — into yuan."""
    unit = ""
    raw = value
    if isinstance(value, dict):
        raw = value.get("value")
        unit = str(value.get("unit") or "").strip()
    text_value = str(raw if raw is not None else "").replace(",", "").replace("，", "").strip()
    if not text_value:
        raise ResearchApplyError(f"{field_path} 建议值为空。")
    try:
        number = Decimal(text_value)
    except InvalidOperation as exc:
        raise ResearchApplyError(f"{field_path} 不是数字：{text_value[:40]}") from exc
    multiplier = MONEY_UNIT_MULTIPLIERS.get(unit)
    if multiplier is None:
        raise ResearchApplyError(f"{field_path} 的金额单位无法识别：{unit[:20]}")
    return number * multiplier


def _ratio_value(field_path: str, value: Any) -> Decimal:
    """Ratios are stored on their own scale (0–100 for percentages), so a unit
    here only ever means "%" or "倍" — strip it rather than multiply by it."""
    raw = value.get("value") if isinstance(value, dict) else value
    text_value = str(raw if raw is not None else "").replace(",", "").replace("%", "").strip()
    if not text_value:
        raise ResearchApplyError(f"{field_path} 建议值为空。")
    try:
        return Decimal(text_value)
    except InvalidOperation as exc:
        raise ResearchApplyError(f"{field_path} 不是数字：{text_value[:40]}") from exc


def normalize_structured_fact(
    db: Session,
    field_path: str,
    value: Any,
    *,
    source_excerpt: Any = None,
) -> Any:
    """Turn one proposed fact into something the field writer will accept.

    Only two things happen here that the writer cannot do for itself: money
    units (the writer sees a number with no idea whether it was 万元) and the
    industry dictionaries (a label outside the taxonomy silently removes the
    target from the pools it belongs in, rather than showing up as a bad value
    on the page). Type, enum and range checks are left to `field_writer`, which
    derives them from the same registry — duplicating them here is how the two
    ends drift apart.
    """
    if field_path == "industry_pairs_json":
        pairs, notes = normalize_industry_pairs(db, value)
        if not pairs:
            raise ResearchApplyError(f"行业不在字典中：{notes[0] if notes else '空值'}")
        return pairs

    indicator = _indicator(field_path)
    if indicator is not None and indicator.kind == "yuan":
        if field_path == "current_operating_cash_flow_yuan":
            unit = str(value.get("unit") or "") if isinstance(value, dict) else ""
            excerpt = str(source_excerpt or "")
            if "股" in unit or _PER_SHARE_CASH_FLOW_RE.search(excerpt):
                raise ResearchApplyError(
                    "current_operating_cash_flow_yuan 只接受公司经营现金流总额，"
                    "不能写入每股经营现金流。"
                )
        return _money_to_yuan(field_path, value)
    if indicator is not None and indicator.kind == "ratio":
        return _ratio_value(field_path, value)

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
    # 文本长度上限归 field_writer 的 _TEXT_LIMITS 管，这里不再各留一份 ——
    # 旧的 120 字符兜底会把风险摘要拦腰截断。
    return text_value
