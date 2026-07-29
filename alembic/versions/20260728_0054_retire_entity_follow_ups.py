"""Retire entity-level follow-up records in favor of relation events.

Revision ID: 20260728_0054
Revises: 20260727_0053
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260728_0054"
down_revision: str | None = "20260727_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "007_retire_entity_follow_ups.sql")


def downgrade() -> None:
    raise NotImplementedError("Entity follow-up data retirement is intentionally forward-only.")
