"""Buyer intent scenarios, phase A: real columns on the scenario table, backfill, retire the intent-level fields.

Revision ID: 20260901_0070
Revises: 20260828_0069
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260901_0070"
down_revision: str | None = "20260828_0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "023_buyer_intent_scenarios.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "Rolling back would have to decide which of a requirement's scenarios "
        "owns each value when folding them back into the single intent row, and "
        "that is exactly the ambiguity this migration exists to remove"
    )
