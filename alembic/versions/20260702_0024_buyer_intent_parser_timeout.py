"""buyer intent parser timeout tuning

Revision ID: 20260702_0024
Revises: 20260630_0023
Create Date: 2026-07-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260702_0024"
down_revision: str | None = "20260630_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("024_buyer_intent_parser_timeout.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for model config seed data.")
