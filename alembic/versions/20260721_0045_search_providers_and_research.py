"""search providers and research proposals

Revision ID: 20260721_0045
Revises: 20260721_0044
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260721_0045"
down_revision: str | None = "20260721_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "045_search_providers_and_research.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "alter table seller_target drop constraint if exists chk_seller_target_research_outcome"
    )
    bind.exec_driver_sql("alter table seller_target drop column if exists research_retry_after")
    bind.exec_driver_sql("alter table seller_target drop column if exists research_last_outcome")
    bind.exec_driver_sql("drop index if exists idx_research_proposal_pending")
    bind.exec_driver_sql("drop index if exists idx_research_proposal_entity")
    bind.exec_driver_sql("drop table if exists research_proposal")
    bind.exec_driver_sql(
        "alter table model_provider_config drop constraint if exists chk_model_provider_type"
    )
    bind.exec_driver_sql(
        """
        alter table model_provider_config
          add constraint chk_model_provider_type check (provider_type in (
            'openai_compatible', 'dashscope', 'deepseek', 'azure_openai',
            'ocr', 'embedding', 'custom'
          ))
        """
    )
