"""reranker node qwen3

Revision ID: 20260602_0008
Revises: 20260602_0007
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260602_0008"
down_revision: str | None = "20260602_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "008_reranker_node_qwen3.sql")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for model config seed data.")
