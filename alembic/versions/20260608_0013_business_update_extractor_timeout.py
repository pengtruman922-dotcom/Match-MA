"""business update extractor timeout

Revision ID: 20260608_0013
Revises: 20260605_0012
Create Date: 2026-06-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260608_0013"
down_revision: str | None = "20260605_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "013_business_update_extractor_timeout.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for model seed tuning.")
