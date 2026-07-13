"""seller target subject and price dates

Revision ID: 20260609_0017
Revises: 20260608_0016
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260609_0017"
down_revision: str | None = "20260608_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "017_seller_target_subject_price_dates.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for seller target field expansion.")
