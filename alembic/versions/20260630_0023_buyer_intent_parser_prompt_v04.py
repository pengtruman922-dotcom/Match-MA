"""buyer intent parser prompt v0.4

Revision ID: 20260630_0023
Revises: 20260623_0022
Create Date: 2026-06-30
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260630_0023"
down_revision: str | None = "20260623_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "023_buyer_intent_parser_prompt_v04.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
