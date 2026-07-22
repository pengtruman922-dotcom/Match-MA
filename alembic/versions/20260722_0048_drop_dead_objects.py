"""drop the tables and columns the 2026-07-22 audit sentenced

Revision ID: 20260722_0048
Revises: 20260721_0047
Create Date: 2026-07-22
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260722_0048"
down_revision: str | None = "20260721_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "048_drop_dead_objects.sql")


def downgrade() -> None:
    raise NotImplementedError(
        "048 drops audit-confirmed dead tables and columns and is not reversible. "
        "Restore from a database backup or replay migrations 001-047 into a fresh database."
    )
