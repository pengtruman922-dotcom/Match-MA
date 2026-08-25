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
    BUYER_PARTY_FINANCIAL_TIME_COLUMNS,
    FieldWriteError,
    WriteProvenance,
    write_buyer_party_fields,
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

# 买家主体的两个来源各有自己的白名单，都从注册表派生。material 来自顾问粘贴的
# 材料与附件（parse），web 来自联网调研（research）—— 后者刻意不含
# contact_name / contact_info_json / our_contact_name：那三项只能来自非公开
# 渠道，不该出现在调研目标里（规则编码在注册表的 writable_by 里）。
BUYER_PARTY_PARSE_FIELDS = writable_columns("parse", "buyer_party")
BUYER_PARTY_RESEARCH_FIELDS = writable_columns("research", "buyer_party")
BUYER_PARTY_WRITABLE_FIELDS = BUYER_PARTY_PARSE_FIELDS | BUYER_PARTY_RESEARCH_FIELDS

# 时间伴生列由代码从事实自己的期间元数据派生（市值配行情日期，营收与现金流共用
# 报告期标签，估值配估值时点）。列进「你可以写的字段」，模型就会把它们当普通字段
# 单独输出，于是同一份财务快照出现两条可能互相矛盾的提案 —— 标的侧的
# RESEARCH_INTERNAL_FIELDS 是同一个道理。
BUYER_PARTY_TIME_COMPANION_FIELDS = frozenset(BUYER_PARTY_FINANCIAL_TIME_COLUMNS.values())
BUYER_PARTY_MODEL_PARSE_FIELDS = BUYER_PARTY_PARSE_FIELDS - BUYER_PARTY_TIME_COMPANION_FIELDS
BUYER_PARTY_MODEL_RESEARCH_FIELDS = BUYER_PARTY_RESEARCH_FIELDS - BUYER_PARTY_TIME_COMPANION_FIELDS
BUYER_PARTY_MODEL_FIELDS = BUYER_PARTY_WRITABLE_FIELDS - BUYER_PARTY_TIME_COMPANION_FIELDS

# material / web —— 提案是哪一段产出的。写入权限按它选，不看 source_url 有没有：
# 材料来源永远没有 URL，拿 URL 判来源会把解析结果全部当成调研结果。
PROPOSAL_SOURCE_WRITERS = {"material": "parse", "web": "research"}

# 存对象而不是数组的 json 列。清单很短，写死比猜形状可靠：
# 猜错的表现是一条合法建议被「需要数组」拦下来。
OBJECT_JSON_FIELDS = frozenset({"contact_info_json"})

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
    """Write one accepted proposal back to its entity.

    ``entity_type`` decides the write path, not the caller: the same review
    endpoint serves seller-target research and buyer-party ingest, and a
    proposal that reached the wrong table would be a silent cross-entity write.
    """
    entity_type = str(proposal.get("entity_type") or "seller_target")
    if entity_type == "buyer_party":
        _apply_buyer_party_proposal(db, proposal, user_id=user_id, review_status=review_status)
        return
    if entity_type != "seller_target":
        raise ResearchApplyError(f"不支持对 {entity_type} 应用调研建议。")
    if proposal["proposal_kind"] == "profile_section":
        _apply_profile_proposal(db, proposal, user_id=user_id, review_status=review_status)
        return
    _apply_structured_fact_proposal(db, proposal, user_id=user_id, review_status=review_status)


def _apply_buyer_party_proposal(
    db: Session,
    proposal: dict[str, Any],
    *,
    user_id: UUID,
    review_status: str,
) -> None:
    """买家主体只有字段事实，没有画像栏 —— 两个业务字段就是全部。

    财务数字连着它的时间一起写：市值配行情日期，营收与经营现金流共用报告期
    标签，估值配估值时点。没有时间的财务数字是不可用的，所以时间不是可选项。
    """
    if proposal["proposal_kind"] != "structured_fact":
        raise ResearchApplyError("买家主体不设画像栏，只接受字段事实建议。")
    field_path = str(proposal.get("field_path") or "")
    if field_path not in BUYER_PARTY_MODEL_FIELDS:
        raise ResearchApplyError("不支持该买家主体字段。")
    source_type = str(proposal.get("source_type") or "")
    writer = PROPOSAL_SOURCE_WRITERS.get(source_type)
    if writer is None:
        raise ResearchApplyError(f"无法判断建议来源：{source_type or '（空）'}")

    proposed_value = proposal.get("proposed_value_json") or {}
    raw_value = (
        proposed_value["reviewed_value"]
        if "reviewed_value" in proposed_value
        else proposed_value.get("value")
    )
    new_value = normalize_structured_fact(
        db,
        field_path,
        raw_value,
        source_excerpt=proposal.get("source_excerpt"),
        entity="buyer_party",
    )
    changes: dict[str, Any] = {field_path: new_value}
    time_column = BUYER_PARTY_FINANCIAL_TIME_COLUMNS.get(field_path)
    if time_column:
        time_value = _buyer_party_time_value(time_column, proposal)
        if time_value is None:
            raise ResearchApplyError(f"{field_path} 缺少期间或行情日期，财务数字不能不带时间入库。")
        changes[time_column] = time_value

    try:
        write_buyer_party_fields(
            db,
            proposal["entity_id"],
            changes,
            provenance=WriteProvenance(
                source_type="research_proposal",
                writer=writer,
                actor_user_id=user_id,
                source_id=proposal["id"],
                field_source_label=str(
                    proposal.get("source_title")
                    or proposal.get("source_url")
                    or ("材料解析" if writer == "parse" else "公开调研")
                ),
                review_status=review_status,
                source_context={
                    "source_type": source_type,
                    "source_url": proposal.get("source_url"),
                    "source_excerpt": proposal.get("source_excerpt"),
                    "source_title": proposal.get("source_title"),
                    "period_label": proposal.get("period_label"),
                    "as_of_date": str(proposal.get("as_of_date") or "") or None,
                    "job_id": str(proposal.get("job_id") or "") or None,
                },
                log_metadata={
                    "source_type": source_type,
                    "source_url": proposal.get("source_url"),
                    "source_title": proposal.get("source_title"),
                    "conflict_kind": proposal.get("conflict_kind"),
                    "auto_accepted": review_status == "auto_accepted",
                    "user_modified": "reviewed_value" in proposed_value,
                },
                write_unchanged_field_source=proposal.get("conflict_kind") == "consistent",
            ),
        )
    except FieldWriteError as exc:
        raise ResearchApplyError(str(exc)) from exc


def _buyer_party_time_value(time_column: str, proposal: dict[str, Any]) -> Any:
    """市值要机器日期，营收/估值要人写的期间标签。两者不能互相顶替。"""
    if time_column == "market_cap_as_of":
        raw = proposal.get("as_of_date")
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw or "")[:10])
        except ValueError:
            return None
    label = str(proposal.get("period_label") or "").strip()
    return label or None


def _apply_profile_proposal(
    db: Session,
    proposal: dict[str, Any],
    *,
    user_id: UUID,
    review_status: str,
) -> None:
    value = proposal.get("proposed_value_json") or {}
    raw_content = value["reviewed_value"] if "reviewed_value" in value else value.get("content_text")
    content = str(raw_content or "").strip()
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
            "user_modified": "reviewed_value" in value,
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
    proposed_value = proposal.get("proposed_value_json") or {}
    raw_value = (
        proposed_value["reviewed_value"]
        if "reviewed_value" in proposed_value
        else proposed_value.get("value")
    )
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
                "user_modified": "reviewed_value" in (proposal.get("proposed_value_json") or {}),
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


def _indicator(field_path: str, entity: str = "seller_target") -> Indicator | None:
    return next(
        (item for item in indicators_for(entity) if item.column == field_path),
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
    entity: str = "seller_target",
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

    indicator = _indicator(field_path, entity)
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
    if indicator is not None and indicator.kind == "json":
        # 注册表里的 json 列几乎都存数组，只有联系方式存对象
        # （{"text": "..."} 或 {"phone": ..., "email": ...}）。不分开的话，
        # 一条联系方式建议会被下面的「需要数组」拦死，而它本来是合法的。
        if field_path in OBJECT_JSON_FIELDS:
            if isinstance(value, str) and value.strip():
                return {"text": value.strip()}
            if isinstance(value, dict) and value:
                return value
            raise ResearchApplyError(f"{field_path} 需要对象。")
        # 闭集多值列的建议值是数组。不接住的话下面的 str() 会把它压成
        # "['litigation']"，写入端再以「must be a JSON object or array」拒绝——
        # 报错位置离病因很远。取值合法性仍由 field_writer 从同一份注册表判定。
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ResearchApplyError(f"{field_path} 需要数组。")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ResearchApplyError("建议值为空。")
        return cleaned

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
