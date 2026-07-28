"""Prepare seller_target status consolidation (non-destructive phase A).

Revision ID: 20260727_0052
Revises: 20260723_0051
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260727_0052"
down_revision: str | None = "20260723_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "005_target_status_consolidation.sql")


def downgrade() -> None:
    raise NotImplementedError("Status consolidation preparation is intentionally forward-only.")
