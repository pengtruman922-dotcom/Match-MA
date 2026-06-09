"""business update extractor prompt v0.5

Revision ID: 20260609_0019
Revises: 20260609_0018
Create Date: 2026-06-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260609_0019"
down_revision: str | None = "20260609_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("019_business_update_extractor_prompt_v05.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
