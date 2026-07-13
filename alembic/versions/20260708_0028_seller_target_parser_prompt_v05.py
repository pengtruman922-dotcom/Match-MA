"""seller target parser prompt v0.5 with concise business summary

Revision ID: 20260708_0028
Revises: 20260708_0027
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260708_0028"
down_revision: str | None = "20260708_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "028_seller_target_parser_prompt_v05.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
