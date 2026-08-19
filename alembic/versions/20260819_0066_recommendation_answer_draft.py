"""Writer answer draft: prose survives the browser disconnecting.

Revision ID: 20260819_0066
Revises: 20260817_0065
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260819_0066"
down_revision: str | None = "20260817_0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "019_recommendation_answer_draft.sql")


def downgrade() -> None:
    # 草稿是进行中的中间态，写完即删；丢掉这张表最多让当时正在写的那一轮
    # 退回「等 worker 写完再看」，没有历史资料在里面。
    op.execute("drop table if exists recommendation_answer_draft")
