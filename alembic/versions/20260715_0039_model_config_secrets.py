"""model configurations and encrypted secrets

Revision ID: 20260715_0039
Revises: 20260714_0038
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260715_0039"
down_revision: str | None = "20260714_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "039_model_config_secrets.sql")


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("alter table model_provider_config drop constraint if exists chk_model_provider_secret_mode")
    bind.exec_driver_sql("alter table model_provider_config drop column if exists api_key_encrypted")
    bind.exec_driver_sql("alter table model_provider_config drop column if exists secret_mode")
    bind.exec_driver_sql("alter table model_provider_config drop column if exists model_name")
