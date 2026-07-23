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
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import (
    diff_payload,
    write_action_logs_for_diff,
    write_field_value_sources_for_diff,
)
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicators_for
from backend.app.services.search_docs import create_search_doc_rebuild_job


class FieldWriteError(ValueError):
    """A change that cannot be written — e.g. a column outside the registry."""


@dataclass
class WriteProvenance:
    """Where a write came from, carried through to the audit and source trail."""

    source_type: str  # "extracted_action" | "research_proposal"
    actor_user_id: UUID
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


def _seller_target_columns() -> set[str]:
    return {ind.column for ind in indicators_for("seller_target")}


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

    `changes` must already be normalized by the caller (its source knows the
    rules — industry taxonomy, enum coercion). This validates the columns are
    registry indicators, writes only the fields that actually changed, and
    returns the applied field names ([] on a no-op).
    """
    if not changes:
        return []
    unknown = set(changes) - _seller_target_columns()
    if unknown:
        raise FieldWriteError(f"Not writable seller_target indicators: {sorted(unknown)}")

    original = _load_current(db, seller_target_id, list(changes))
    diff = diff_payload(original, changes)
    if not diff:
        return []

    set_clauses = [f"{column} = :{column}" for column in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
    db.execute(
        text(
            f"""
            update seller_target
            set {', '.join(set_clauses)}
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            **{column: changes[column] for column in diff},
            "updated_by": provenance.actor_user_id,
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

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
            changes=changes,
            diff=diff,
            source_type=provenance.source_type,
            source_id=provenance.source_id,
            evidence_id=provenance.evidence_id,
            source_label=provenance.field_source_label,
            confidence=provenance.confidence,
            review_status=provenance.review_status,
            source_context=provenance.source_context,
        )
    create_search_doc_rebuild_job(
        db,
        entity_type="seller_target",
        entity_id=seller_target_id,
        source=search_doc_source,
    )
    return list(diff)
