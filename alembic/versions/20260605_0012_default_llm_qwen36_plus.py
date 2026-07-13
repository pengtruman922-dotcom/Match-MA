"""default LLM qwen3.6-plus

Revision ID: 20260605_0012
Revises: 20260603_0011
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260605_0012"
down_revision: str | None = "20260603_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "012_default_llm_qwen36_plus.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for default model seed data.")
