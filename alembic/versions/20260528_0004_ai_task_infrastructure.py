"""ai task infrastructure

Revision ID: 20260528_0004
Revises: 20260527_0003
Create Date: 2026-05-28
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260528_0004"
down_revision: str | None = "20260527_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "004_ai_task_infrastructure.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for AI task infrastructure.")
