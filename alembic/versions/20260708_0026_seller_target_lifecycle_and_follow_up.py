"""seller target lifecycle status and follow-up log

Revision ID: 20260708_0026
Revises: 20260702_0025
Create Date: 2026-07-08
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260708_0026"
down_revision: str | None = "20260702_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("026_seller_target_lifecycle_and_follow_up.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop table if exists target_follow_up")
    bind.exec_driver_sql("alter table seller_target drop column if exists lifecycle_status")
