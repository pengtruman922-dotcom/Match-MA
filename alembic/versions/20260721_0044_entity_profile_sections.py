"""entity profile sections: qualitative matching profile in its own table

Revision ID: 20260721_0044
Revises: 20260721_0043
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260721_0044"
down_revision: str | None = "20260721_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "044_entity_profile_sections.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("drop index if exists idx_entity_profile_section_review")
    bind.exec_driver_sql("drop index if exists idx_entity_profile_section_entity")
    bind.exec_driver_sql("drop table if exists entity_profile_section")
