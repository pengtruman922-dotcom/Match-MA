"""Seller target business tags: industry dictionary retirement, stage A.

Revision ID: 20260909_0072
Revises: 20260907_0071
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260909_0072"
down_revision: str | None = "20260907_0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "025_seller_target_business_tags.sql")


def downgrade() -> None:
    op.execute("drop index if exists idx_seller_target_business_tags")
    op.execute("alter table seller_target drop constraint if exists chk_seller_target_business_tags_json")
    op.execute("alter table seller_target drop column if exists business_tags_json")
