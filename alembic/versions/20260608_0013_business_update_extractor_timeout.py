"""business update extractor timeout

Revision ID: 20260608_0013
Revises: 20260605_0012
Create Date: 2026-06-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260608_0013"
down_revision: str | None = "20260605_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("013_business_update_extractor_timeout.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for model seed tuning.")
