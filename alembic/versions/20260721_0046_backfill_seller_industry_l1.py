"""backfill seller industry l1 after specialized update parsing

Revision ID: 20260721_0046
Revises: 20260721_0045
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260721_0046"
down_revision: str | None = "20260721_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "046_backfill_seller_industry_l1.sql")


def downgrade() -> None:
    # Data backfills are intentionally not reversed.
    pass
