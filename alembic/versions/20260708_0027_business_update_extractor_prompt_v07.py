"""business update extractor prompt v0.7 with target follow-up notes

Revision ID: 20260708_0027
Revises: 20260708_0026
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260708_0027"
down_revision: str | None = "20260708_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "027_business_update_extractor_prompt_v07.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
