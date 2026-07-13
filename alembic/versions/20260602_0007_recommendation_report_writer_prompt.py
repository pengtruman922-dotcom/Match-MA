"""recommendation report writer prompt

Revision ID: 20260602_0007
Revises: 20260601_0006
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260602_0007"
down_revision: str | None = "20260601_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "007_recommendation_report_writer_prompt.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
