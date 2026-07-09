"""app_user username/password_hash and system assistant user

Revision ID: 20260709_0030
Revises: 20260708_0029
Create Date: 2026-07-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260709_0030"
down_revision: str | None = "20260708_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("030_app_user_auth_and_system_user.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop index if exists uq_app_user_username")
    bind.exec_driver_sql("alter table app_user drop column if exists password_hash")
    bind.exec_driver_sql("alter table app_user drop column if exists username")
    # The seeded system assistant user is kept on downgrade: created_by /
    # updated_by rows may already reference it.
