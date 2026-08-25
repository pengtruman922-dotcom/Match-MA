"""One write channel for structured facts on seller targets and buyer parties.

Parse-apply and research-apply each carried their own copy of the same
mechanics — load the current value, diff, UPDATE the column, write the audit
log, write the field-value source, queue a search-doc rebuild — differing only
in provenance. That duplication is where a fact written by one path could be
recorded differently from the same fact written by the other. This is the
single place both now go through, so a value lands and is audited identically
regardless of who wrote it.

The column set is validated against the indicator registry: only declared
seller_target indicators can be written here. The human edit path
(PATCH /seller-targets) stays separate for now — it writes the remaining
non-indicator fields (owner) and does not record a field-value source. Since
0814 the trade lifecycle is an indicator too, so a consultant changing 级别 or
交易状态 comes through here and gets the same audit and source trail as a parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import (
    diff_payload,
    write_action_logs_for_diff,
    write_field_value_sources_for_diff,
)
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import Indicator, indicator_by_column, indicators_for
from backend.app.services.buyer_party_name import (
    BuyerPartyNameChangeRequiresReview,
    plan_buyer_party_rename,
)
from backend.app.services.entity_grade import SELLER_GRADE, resolve_grade_pair
from backend.app.services.industry_taxonomy import normalize_industry_pairs, normalize_l2_values, resolve_l1
from backend.app.services.region_dictionary import NORMALIZERS as REGION_NORMALIZERS
from backend.app.services.search_docs import create_search_doc_rebuild_job


class FieldWriteError(ValueError):
    """A change that cannot be written — e.g. a column outside the registry."""


@dataclass
class WriteProvenance:
    """Where a write came from, carried through to the audit and source trail."""

    source_type: str  # audit source: extracted_action | research_proposal | manual_edit
    actor_user_id: UUID
    # Authority source is intentionally separate from the audit source. A
    # manual UI edit records manual_edit but is authorized as manual.
    writer: str | None = None  # parse | research | manual
    source_id: UUID | None = None
    evidence_id: UUID | None = None
    business_update_id: UUID | None = None
    extracted_action_id: UUID | None = None
    field_source_label: str | None = None
    confidence: Any = None
    review_status: str = "auto_accepted"
    source_context: dict[str, Any] | None = None
    log_metadata: dict[str, Any] = field(default_factory=dict)
    write_field_source: bool = True
    # A research run that independently confirms the current value is still
    # useful provenance.  It must not create a fake action log, but it should
    # append a field source saying when and where the value was re-verified.
    write_unchanged_field_source: bool = False


def _seller_target_columns() -> set[str]:
    return {ind.column for ind in indicators_for("seller_target")}


def _writer_from_provenance(provenance: WriteProvenance) -> str:
    if provenance.writer:
        return provenance.writer
    return {
        "extracted_action": "parse",
        "seller_target_parse": "parse",
        "research_proposal": "research",
        "manual_edit": "manual",
    }.get(provenance.source_type, "")


_TEXT_LIMITS = {
    "target_name": 300,
    "target_subject_name": 300,
    "business_summary": 300,
    "valuation_date": 80,
    "asking_price_date": 80,
}
_REQUIRED_SELLER_TARGET_FIELDS = {"target_name", "target_type", "listed_status"}
_ISO_DATE_COLUMNS = frozenset({"financial_period_end_date", "market_cap_as_of"})


def _normalize_value(
    db: Session,
    indicator: Indicator,
    value: Any,
    *,
    required_columns: frozenset[str] = frozenset(_REQUIRED_SELLER_TARGET_FIELDS),
) -> Any:
    """Validate values at the only structured-fact write boundary."""
    if value is None:
        if indicator.column in required_columns:
            raise FieldWriteError(f"{indicator.column} may not be empty.")
        return None
    if indicator.column == "industry_l1":
        resolved = resolve_l1(db, str(value).strip())
        if resolved is None:
            raise FieldWriteError(f"一级行业不在字典中: {value!r}")
        return resolved
    if indicator.column == "industry_l2":
        resolved, _ = normalize_l2_values(db, [str(value).strip()])
        if not resolved:
            raise FieldWriteError(f"二级行业不在字典中: {value!r}")
        return resolved[0]
    if indicator.column == "industry_pairs_json":
        normalized, notes = normalize_industry_pairs(db, value)
        if notes and not normalized:
            raise FieldWriteError(f"行业不在字典中: {notes[0]}")
        return normalized
    if indicator.column in REGION_NORMALIZERS:
        # Province is spelled one way for everyone, so cascading filters match
        # regardless of whether a value came from the picker or from an LLM.
        return REGION_NORMALIZERS[indicator.column](value)
    # 只有这两列真的是 date 列。**不要**改成按 indicator.kind == "date" 泛化：
    # seller_target.valuation_date / asking_price_date 在注册表里也标 date，
    # 但 DDL 是 text，存的是「2025年一季度」这种中文标签。
    if indicator.column in _ISO_DATE_COLUMNS:
        try:
            return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError) as exc:
            raise FieldWriteError(f"{indicator.column} must be an ISO date.") from exc
    if indicator.kind == "enum":
        if not isinstance(value, str):
            raise FieldWriteError(f"{indicator.column} must be an enum value.")
        valid = {code for code, _ in indicator.enum_options or ()}
        if value not in valid:
            raise FieldWriteError(f"Invalid {indicator.column}: {value!r}")
        return value
    if indicator.kind in {"yuan", "ratio"}:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise FieldWriteError(f"{indicator.column} must be numeric.") from exc
        if not number.is_finite():
            raise FieldWriteError(f"{indicator.column} must be finite.")
        if indicator.column in {
            "current_debt_ratio", "premium_rate", "transfer_ratio_min",
            "transfer_ratio_max",
        } and not Decimal("0") <= number <= Decimal("100"):
            raise FieldWriteError(f"{indicator.column} must be between 0 and 100.")
        return number
    if indicator.kind == "json":
        if not isinstance(value, (list, dict)):
            raise FieldWriteError(f"{indicator.column} must be a JSON object or array.")
        # 闭集多值列在这里就把字典外的取值拦下来，而不是让 DB 的 check 约束在
        # 更新的最后一刻抛整条事务——那时报的是约束名，看不出是哪个取值不合法。
        if indicator.multi_value and indicator.enum_options:
            if not isinstance(value, list):
                raise FieldWriteError(f"{indicator.column} must be a JSON array.")
            valid = {code for code, _ in indicator.enum_options}
            invalid = [item for item in value if item not in valid]
            if invalid:
                raise FieldWriteError(f"Invalid {indicator.column}: {invalid!r}")
            deduplicated: list[Any] = []
            for item in value:
                if item not in deduplicated:
                    deduplicated.append(item)
            return deduplicated
        return value
    if not isinstance(value, str):
        raise FieldWriteError(f"{indicator.column} must be text.")
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[: _TEXT_LIMITS.get(indicator.column, 2000)]


def _load_current(db: Session, seller_target_id: UUID, columns: list[str]) -> dict[str, Any]:
    return _load_current_row(
        db,
        table="seller_target",
        entity_id=seller_target_id,
        columns=columns,
        missing_message=f"Seller target not found: {seller_target_id}",
    )


def _load_current_row(
    db: Session,
    *,
    table: str,
    entity_id: UUID,
    columns: list[str],
    missing_message: str,
) -> dict[str, Any]:
    # Table names are module constants and columns are registry-validated
    # indicator names, so both are safe to interpolate.
    projection = ", ".join(columns)
    row = db.execute(
        text(
            f"""
            select {projection}
            from {table}
            where id = :id and team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {"id": entity_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise FieldWriteError(missing_message)
    return dict(row)


def write_seller_target_fields(
    db: Session,
    seller_target_id: UUID,
    changes: dict[str, Any],
    *,
    provenance: WriteProvenance,
    search_doc_source: str,
    rejected_fields: dict[str, str] | None = None,
) -> list[str]:
    """Apply normalized field changes to a seller_target, audited and sourced.

    The writer is the validation boundary as well as the audit boundary. It
    validates each declared column, the provenance's write authority, and the
    value kind before writing only actual differences.

    Pass ``rejected_fields`` to collect per-field validation failures instead of
    aborting: a batch from an LLM is a bag of independent claims, and one badly
    formatted number should not throw away the eight fields that were fine.
    Callers that hand-build their changes leave it None and keep the strict
    all-or-nothing contract, because for them a bad field is a code bug.
    """
    if not changes:
        return []

    def _reject(column: str, reason: str) -> None:
        if rejected_fields is None:
            raise FieldWriteError(reason)
        rejected_fields[column] = reason

    writer = _writer_from_provenance(provenance)
    if not writer:
        # Not data-dependent: a caller passed a provenance the writer registry
        # does not know. Always a bug, never a bad LLM value.
        raise FieldWriteError(f"Unknown field writer for source: {provenance.source_type}")

    known_columns = _seller_target_columns()
    normalized_changes: dict[str, Any] = {}
    for column, value in changes.items():
        if column not in known_columns:
            _reject(column, f"Not writable seller_target indicators: {[column]}")
            continue
        indicator = indicator_by_column("seller_target", column)
        if writer not in indicator.writable_by:
            _reject(column, f"{writer} may not write seller_target.{column}")
            continue
        try:
            normalized_changes[column] = _normalize_value(db, indicator, value)
        except FieldWriteError as exc:
            _reject(column, str(exc))

    # 级别与它的 E 细分原因必须成对落地，而 parse / research / 人工信息页编辑三条
    # 路都汇到这里，所以派生放在这个咽喉上，一处覆盖三条路。空结果就是「这批材料
    # 没有级别主张」或「AI 想把 E 拉回在售」，两种都不写。
    if normalized_changes.keys() & {SELLER_GRADE.grade_column, SELLER_GRADE.reason_column}:
        resolved = resolve_grade_pair(
            SELLER_GRADE,
            normalized_changes,
            _load_current(db, seller_target_id, [SELLER_GRADE.grade_column, SELLER_GRADE.reason_column]),
            allow_reactivation=writer == "manual",
        )
        normalized_changes.pop(SELLER_GRADE.grade_column, None)
        normalized_changes.pop(SELLER_GRADE.reason_column, None)
        normalized_changes.update(resolved)

    if not normalized_changes:
        return []

    original = _load_current(db, seller_target_id, list(normalized_changes))
    diff = diff_payload(original, normalized_changes)
    if not diff:
        if provenance.write_field_source and provenance.write_unchanged_field_source:
            unchanged = {
                column: (original.get(column), normalized_changes[column])
                for column in normalized_changes
            }
            write_field_value_sources_for_diff(
                db,
                entity_type="seller_target",
                entity_id=seller_target_id,
                changes=normalized_changes,
                diff=unchanged,
                source_type=provenance.source_type,
                source_id=provenance.source_id,
                evidence_id=provenance.evidence_id,
                source_label=provenance.field_source_label,
                confidence=provenance.confidence,
                review_status=provenance.review_status,
                source_context=provenance.source_context,
                created_by=provenance.actor_user_id,
            )
        return []

    set_clauses = [f"{column} = :{column}" for column in diff]
    statement_params: dict[str, Any] = {
        **{column: normalized_changes[column] for column in diff},
        "updated_by": provenance.actor_user_id,
        "seller_target_id": seller_target_id,
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
    }
    if "industry_pairs_json" in diff:
        # The retired scalar columns are a read compatibility projection only.
        # Their values are always derived from the first canonical pair.
        first_pair = normalized_changes["industry_pairs_json"][0] if normalized_changes["industry_pairs_json"] else {}
        set_clauses.extend(["industry_l1 = :compat_industry_l1", "industry_l2 = :compat_industry_l2"])
        statement_params["compat_industry_l1"] = first_pair.get("l1")
        statement_params["compat_industry_l2"] = first_pair.get("l2")
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    statement = text(
        f"""
        update seller_target
        set {', '.join(set_clauses)}
        where id = :seller_target_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    # 每个 jsonb 列都要显式绑定类型，否则驱动会把 Python list 当成数组字面量适配，
    # 落库不是 jsonb。以前只有 industry_pairs_json 一列时是硬编码的。
    json_bindings = [
        bindparam(column, type_=JSONB)
        for column in diff
        if indicator_by_column("seller_target", column).kind == "json"
    ]
    if json_bindings:
        statement = statement.bindparams(*json_bindings)
    db.execute(statement, statement_params)

    write_action_logs_for_diff(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        diff=diff,
        source_type=provenance.source_type,
        source_id=provenance.source_id,
        evidence_id=provenance.evidence_id,
        business_update_id=provenance.business_update_id,
        extracted_action_id=provenance.extracted_action_id,
        metadata_json=provenance.log_metadata,
        applied_by=provenance.actor_user_id,
    )
    if provenance.write_field_source:
        write_field_value_sources_for_diff(
            db,
            entity_type="seller_target",
            entity_id=seller_target_id,
            changes=normalized_changes,
            diff=diff,
            source_type=provenance.source_type,
            source_id=provenance.source_id,
            evidence_id=provenance.evidence_id,
            source_label=provenance.field_source_label,
            confidence=provenance.confidence,
            review_status=provenance.review_status,
            source_context=provenance.source_context,
            created_by=provenance.actor_user_id,
        )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source=search_doc_source,
    )
    return list(diff)


_REQUIRED_BUYER_PARTY_FIELDS = frozenset({"buyer_name", "ownership_type", "listed_status"})

# 财务数字必须带时间一起落库：没有时间的财务数字是不可用的。
# 一个数字对应哪一格时间由列决定，不由模型说，所以映射写在代码里。
BUYER_PARTY_FINANCIAL_TIME_COLUMNS: dict[str, str] = {
    "market_cap_yuan": "market_cap_as_of",
    "valuation_yuan": "valuation_date",
    "current_revenue_yuan": "financial_period_label",
    "current_operating_cash_flow_yuan": "financial_period_label",
}


def _buyer_party_columns() -> set[str]:
    return {ind.column for ind in indicators_for("buyer_party")}


def write_buyer_party_fields(
    db: Session,
    buyer_party_id: UUID,
    changes: dict[str, Any],
    *,
    provenance: WriteProvenance,
    rejected_fields: dict[str, str] | None = None,
) -> list[str]:
    """Apply normalized field changes to a buyer_party, audited and sourced.

    Same contract as ``write_seller_target_fields`` — registry-validated columns,
    per-source write authority, one audit log and one field-value source per
    changed column — minus the three seller-only pieces: the grade pair, the
    industry compatibility projection, and the search-doc rebuild (buyer parties
    have no search document).

    改名仍然是特例：旧名自动进 aliases_json，而非人工来源的改名必须已经被人
    确认过。改错名字影响该主体的所有关联需求、撮合关系和搜索，**而且不会报错**，
    只会让人找不到东西。
    """
    if not changes:
        return []

    def _reject(column: str, reason: str) -> None:
        if rejected_fields is None:
            raise FieldWriteError(reason)
        rejected_fields[column] = reason

    writer = _writer_from_provenance(provenance)
    if not writer:
        raise FieldWriteError(f"Unknown field writer for source: {provenance.source_type}")

    known_columns = _buyer_party_columns()
    normalized_changes: dict[str, Any] = {}
    for column, value in changes.items():
        if column not in known_columns:
            _reject(column, f"Not writable buyer_party indicators: {[column]}")
            continue
        indicator = indicator_by_column("buyer_party", column)
        if writer not in indicator.writable_by:
            _reject(column, f"{writer} may not write buyer_party.{column}")
            continue
        try:
            normalized_changes[column] = _normalize_value(
                db,
                indicator,
                value,
                required_columns=_REQUIRED_BUYER_PARTY_FIELDS,
            )
        except FieldWriteError as exc:
            _reject(column, str(exc))

    if not normalized_changes:
        return []

    current = _load_buyer_party_current(
        db,
        buyer_party_id,
        [*normalized_changes, "buyer_name", "aliases_json"],
    )
    if "buyer_name" in normalized_changes:
        try:
            renamed, aliases = _plan_buyer_party_name_write(
                current=current,
                new_name=str(normalized_changes["buyer_name"]),
                writer=writer,
                provenance=provenance,
            )
        except FieldWriteError as exc:
            _reject("buyer_name", str(exc))
            normalized_changes.pop("buyer_name", None)
        else:
            normalized_changes["buyer_name"] = renamed
            if aliases != [str(alias) for alias in (current.get("aliases_json") or [])]:
                normalized_changes["aliases_json"] = aliases
        if not normalized_changes:
            return []

    original = {column: current.get(column) for column in normalized_changes}
    diff = diff_payload(original, normalized_changes)
    if not diff:
        if provenance.write_field_source and provenance.write_unchanged_field_source:
            unchanged = {
                column: (original.get(column), normalized_changes[column])
                for column in normalized_changes
            }
            write_field_value_sources_for_diff(
                db,
                entity_type="buyer_party",
                entity_id=buyer_party_id,
                changes=normalized_changes,
                diff=unchanged,
                source_type=provenance.source_type,
                source_id=provenance.source_id,
                evidence_id=provenance.evidence_id,
                source_label=provenance.field_source_label,
                confidence=provenance.confidence,
                review_status=provenance.review_status,
                source_context=provenance.source_context,
                created_by=provenance.actor_user_id,
            )
        return []

    set_clauses = [f"{column} = :{column}" for column in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    assignments = ", ".join(set_clauses)
    statement = text(
        f"""
        update buyer_party
        set {assignments}
        where id = :buyer_party_id
          and team_id = :team_id
          and workspace_id = :workspace_id
          and deleted_at is null
        """
    )
    # 每个 jsonb 列都要显式绑定类型，否则驱动会把 Python list 当成数组字面量适配，
    # 落库不是 jsonb。aliases_json 不是注册表指标，所以要单独列出来。
    json_bindings = [
        bindparam(column, type_=JSONB)
        for column in diff
        if column == "aliases_json" or indicator_by_column("buyer_party", column).kind == "json"
    ]
    if json_bindings:
        statement = statement.bindparams(*json_bindings)
    db.execute(
        statement,
        {
            **{column: normalized_changes[column] for column in diff},
            "updated_by": provenance.actor_user_id,
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

    write_action_logs_for_diff(
        db,
        entity_type="buyer_party",
        entity_id=buyer_party_id,
        diff=diff,
        source_type=provenance.source_type,
        source_id=provenance.source_id,
        evidence_id=provenance.evidence_id,
        business_update_id=provenance.business_update_id,
        extracted_action_id=provenance.extracted_action_id,
        metadata_json=provenance.log_metadata,
        applied_by=provenance.actor_user_id,
    )
    if provenance.write_field_source:
        write_field_value_sources_for_diff(
            db,
            entity_type="buyer_party",
            entity_id=buyer_party_id,
            changes=normalized_changes,
            diff=diff,
            source_type=provenance.source_type,
            source_id=provenance.source_id,
            evidence_id=provenance.evidence_id,
            source_label=provenance.field_source_label,
            confidence=provenance.confidence,
            review_status=provenance.review_status,
            source_context=provenance.source_context,
            created_by=provenance.actor_user_id,
        )
    return list(diff)


def _load_buyer_party_current(
    db: Session,
    buyer_party_id: UUID,
    columns: list[str],
) -> dict[str, Any]:
    return _load_current_row(
        db,
        table="buyer_party",
        entity_id=buyer_party_id,
        columns=list(dict.fromkeys(columns)),
        missing_message=f"Buyer party not found: {buyer_party_id}",
    )


def _plan_buyer_party_name_write(
    *,
    current: dict[str, Any],
    new_name: str,
    writer: str,
    provenance: WriteProvenance,
) -> tuple[str, list[str]]:
    """人工保存即确认；解析/调研改名必须已经被人在复核里点过采纳。

    ``review_status`` 是这条判断的唯一依据：``auto_accepted`` 表示没人看过，
    那正是不能静默覆盖名称的情况。
    """
    confirmed = writer == "manual" or provenance.review_status == "accepted"
    try:
        return plan_buyer_party_rename(
            current_name=str(current.get("buyer_name") or ""),
            current_aliases=[str(alias) for alias in (current.get("aliases_json") or [])],
            new_name=new_name,
            source=writer,
            confirmed=confirmed,
        )
    except BuyerPartyNameChangeRequiresReview as exc:
        raise FieldWriteError(str(exc)) from exc
    except ValueError as exc:
        raise FieldWriteError(str(exc)) from exc
