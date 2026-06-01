"""business update extractor prompt v0.3

Revision ID: 20260601_0006
Revises: 20260529_0005
Create Date: 2026-06-01
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260601_0006"
down_revision: str | None = "20260529_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("006_business_update_extractor_prompt_v03.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
