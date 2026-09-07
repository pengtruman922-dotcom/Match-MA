"""API keys and agent call log for the external-agent MCP endpoint.

Revision ID: 20260907_0071
Revises: 20260901_0070
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

from backend.app.migration_sql import run_migration_sql

revision: str = "20260907_0071"
down_revision: str | None = "20260901_0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    run_migration_sql(op.get_bind(), "024_api_keys_and_agent_calls.sql")


def downgrade() -> None:
    op.execute("drop table if exists agent_call_log")
    op.execute("drop table if exists api_key")
