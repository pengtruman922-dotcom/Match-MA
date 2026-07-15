"""industry dictionary hierarchy and alias ownership

Revision ID: 20260715_0040
Revises: 20260715_0039
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260715_0040"
down_revision: str | None = "20260715_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "040_industry_dictionary_hierarchy.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop index if exists idx_industry_taxonomy_canonical")
    bind.exec_driver_sql("drop index if exists idx_industry_taxonomy_parent")
    bind.exec_driver_sql("alter table industry_taxonomy drop column if exists canonical_term_id")
    bind.exec_driver_sql("alter table industry_taxonomy drop column if exists parent_id")
