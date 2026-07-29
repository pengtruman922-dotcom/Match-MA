"""Add a comparable seller-target financial period.

Revision ID: 20260728_0056
Revises: 20260728_0055
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260728_0056"
down_revision: str | None = "20260728_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "009_research_financial_period_guard.sql")


def downgrade() -> None:
    op.execute("alter table seller_target drop column if exists financial_period_end_date")
