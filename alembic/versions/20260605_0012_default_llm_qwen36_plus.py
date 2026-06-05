"""default LLM qwen3.6-plus

Revision ID: 20260605_0012
Revises: 20260603_0011
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260605_0012"
down_revision: str | None = "20260603_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("012_default_llm_qwen36_plus.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for default model seed data.")
