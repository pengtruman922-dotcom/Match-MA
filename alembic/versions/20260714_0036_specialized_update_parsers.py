"""specialized seller and buyer update parsers

Revision ID: 20260714_0036
Revises: 20260714_0035
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260714_0036"
down_revision: str | None = "20260714_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "036_specialized_update_parsers.sql")


def downgrade() -> None:
    bind = op.get_bind()
    for node_name in ("seller_target_update_parser", "buyer_intent_update_parser"):
        bind.exec_driver_sql(
            "update model_node_config set is_active = false, is_default = false, updated_at = now() "
            f"where node_name = '{node_name}'"
        )
        bind.exec_driver_sql(
            "update prompt_template set is_active = false, is_default = false, updated_at = now() "
            f"where node_name = '{node_name}'"
        )
    bind.exec_driver_sql(
        "update prompt_template set is_active = false, is_default = false, updated_at = now() "
        "where node_name = 'buyer_intent_parser' and version = 'v0.6.0'"
    )
