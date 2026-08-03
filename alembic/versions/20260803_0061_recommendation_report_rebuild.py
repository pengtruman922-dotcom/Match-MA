"""Rebuild customer-facing recommendation report types and clear legacy reports.

Revision ID: 20260803_0061
Revises: 20260803_0060
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260803_0061"
down_revision: str | None = "20260803_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "014_recommendation_report_rebuild.sql")


def downgrade() -> None:
    raise NotImplementedError("legacy recommendation reports cannot be restored")
