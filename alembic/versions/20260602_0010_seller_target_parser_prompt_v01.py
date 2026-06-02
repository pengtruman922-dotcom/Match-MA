"""seller target parser prompt v0.1

Revision ID: 20260602_0010
Revises: 20260602_0009
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260602_0010"
down_revision: str | None = "20260602_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("010_seller_target_parser_prompt_v01.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for prompt seed data.")
