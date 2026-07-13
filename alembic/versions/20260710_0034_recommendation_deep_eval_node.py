"""recommendation deep-eval node and prompt

Revision ID: 20260710_0034
Revises: 20260710_0033
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260710_0034"
down_revision: str | None = "20260710_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "034_recommendation_deep_eval_node.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "update model_node_config set is_active = false, is_default = false, updated_at = now() "
        "where node_name = 'recommendation_deep_eval'"
    )
    bind.exec_driver_sql(
        "update prompt_template set is_active = false, is_default = false, updated_at = now() "
        "where node_name = 'recommendation_deep_eval'"
    )
