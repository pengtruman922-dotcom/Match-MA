"""retire embedding and generic rerank nodes

Revision ID: 20260714_0037
Revises: 20260714_0036
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260714_0037"
down_revision: str | None = "20260714_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "037_retire_embedding_and_rerank_nodes.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "update model_node_config set is_active = true, is_default = true, updated_at = now() "
        "where node_name in ('embedding_seller_doc', 'embedding_buyer_intent', 'recommendation_reranker')"
    )
