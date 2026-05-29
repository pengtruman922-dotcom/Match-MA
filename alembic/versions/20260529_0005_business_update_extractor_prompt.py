"""business update extractor prompt

Revision ID: 20260529_0005
Revises: 20260528_0004
Create Date: 2026-05-29
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260529_0005"
down_revision: str | None = "20260528_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("005_business_update_extractor_prompt.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
