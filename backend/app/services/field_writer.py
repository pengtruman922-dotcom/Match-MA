"""One write channel for seller_target structured facts.

Parse-apply and research-apply each carried their own copy of the same
mechanics — load the current value, diff, UPDATE the column, write the audit
log, write the field-value source, queue a search-doc rebuild — differing only
in provenance. That duplication is where a fact written by one path could be
recorded differently from the same fact written by the other. This is the
single place both now go through, so a value lands and is audited identically
regardless of who wrote it.

The column set is validated against the indicator registry: only declared
seller_target indicators can be written here. The human edit path
(PATCH /seller-targets) stays separate for now — it writes non-indicator fields
(owner, lifecycle) and does not record a field-value source.
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


def _normalize_value(db: Session, indicator: Indicator, value: Any) -> Any:
    """Validate values at the only structured-fact write boundary."""
    if value is None:
        if indicator.column in _REQUIRED_SELLER_TARGET_FIELDS:
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
    if indicator.column == "financial_period_end_date":
        try:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise FieldWriteError("financial_period_end_date must be an ISO date.") from exc
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
        return value
    if not isinstance(value, str):
        raise FieldWriteError(f"{indicator.column} must be text.")
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[: _TEXT_LIMITS.get(indicator.column, 2000)]


def _load_current(db: Session, seller_target_id: UUID, columns: list[str]) -> dict[str, Any]:
    # columns are registry-validated indicator names, safe to interpolate.
    projection = ", ".join(columns)
    row = db.execute(
        text(
            f"""
            select {projection}
            from seller_target
            where id = :id and team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {"id": seller_target_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().one_or_none()
    if row is None:
        raise FieldWriteError(f"Seller target not found: {seller_target_id}")
    return dict(row)


def write_seller_target_fields(
    db: Session,
    seller_target_id: UUID,
    changes: dict[str, Any],
    *,
    provenance: WriteProvenance,
    search_doc_source: str,
) -> list[str]:
    """Apply normalized field changes to a seller_target, audited and sourced.

    The writer is the validation boundary as well as the audit boundary. It
    validates each declared column, the provenance's write authority, and the
    value kind before writing only actual differences.
    """
    if not changes:
        return []
    unknown = set(changes) - _seller_target_columns()
    if unknown:
        raise FieldWriteError(f"Not writable seller_target indicators: {sorted(unknown)}")

    writer = _writer_from_provenance(provenance)
    if not writer:
        raise FieldWriteError(f"Unknown field writer for source: {provenance.source_type}")
    normalized_changes: dict[str, Any] = {}
    for column, value in changes.items():
        indicator = indicator_by_column("seller_target", column)
        if writer not in indicator.writable_by:
            raise FieldWriteError(f"{writer} may not write seller_target.{column}")
        normalized_changes[column] = _normalize_value(db, indicator, value)

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
    if "industry_pairs_json" in diff:
        statement = statement.bindparams(bindparam("industry_pairs_json", type_=JSONB))
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
