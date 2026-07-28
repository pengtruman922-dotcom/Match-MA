"""Drop the retired seller_target recommendation status (phase B).

Revision ID: 20260727_0053
Revises: 20260727_0052
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260727_0053"
down_revision: str | None = "20260727_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "006_drop_target_recommendation_status.sql")


def downgrade() -> None:
    raise NotImplementedError("Dropping recommendation_status is intentionally forward-only.")
