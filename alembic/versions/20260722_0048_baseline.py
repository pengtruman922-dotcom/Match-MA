"""Match-MA baseline - squashes migrations 001-048

Revision ID: 20260722_0048
Revises:
Create Date: 2026-07-22

Keeps the pre-squash head id, so the production database (already stamped
20260722_0048 by the old tree) sees nothing to do on deploy. Only fresh
databases execute 001_baseline.sql, which reproduces the production schema
and seeds (charter docs/系统总纲.md §6.3).
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260722_0048"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "001_baseline.sql")


def downgrade() -> None:
    raise NotImplementedError("The baseline is the floor - there is nothing below it.")
