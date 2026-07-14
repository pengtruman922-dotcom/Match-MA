"""recommendation deep-eval prompt v0.2

Revision ID: 20260714_0038
Revises: 20260714_0037
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260714_0038"
down_revision: str | None = "20260714_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "038_recommendation_deep_eval_prompt_v02.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "update prompt_template set is_active = false, is_default = false, updated_at = now() "
        "where node_name = 'recommendation_deep_eval' and version = 'v0.2.0'"
    )
    bind.exec_driver_sql(
        "update prompt_template set is_active = true, is_default = true, updated_at = now() "
        "where node_name = 'recommendation_deep_eval' and version = 'v0.1.0'"
    )
