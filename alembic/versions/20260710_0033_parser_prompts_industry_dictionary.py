"""parser prompts with closed industry dictionary

Revision ID: 20260710_0033
Revises: 20260710_0032
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import load_migration_sql, split_sql_statements

revision: str = "20260710_0033"
down_revision: str | None = "20260710_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    sql = load_migration_sql("033_parser_prompts_industry_dictionary.sql")
    for statement in split_sql_statements(sql):
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for node_name, restore_version, new_version in (
        ("buyer_intent_parser", "v0.4.0", "v0.5.0"),
        ("seller_target_parser", "v0.5.0", "v0.6.0"),
    ):
        bind.exec_driver_sql(
            "update prompt_template set is_default = false, is_active = false, updated_at = now() "
            f"where node_name = '{node_name}' and version = '{new_version}'"
        )
        bind.exec_driver_sql(
            "update prompt_template set is_default = true, is_active = true, updated_at = now() "
            f"where node_name = '{node_name}' and version = '{restore_version}'"
        )
