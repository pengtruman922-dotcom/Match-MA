"""Buyer intent field slimming, phase A: add the five new columns, backfill, drop the orphans.

Revision ID: 20260828_0069
Revises: 20260825_0068
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260828_0069"
down_revision: str | None = "20260825_0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "022_buyer_intent_field_slimming.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "The four orphan columns are dropped here and their values are not "
        "recoverable, and re-splitting the merged business tags back into the "
        "industry dictionary columns would have to guess which tier each tag "
        "came from"
    )
