from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_database_url() -> str:
    settings = get_settings()
    database_url = settings.sqlalchemy_database_url or config.get_main_option("sqlalchemy.url")
    if not database_url or database_url.startswith("postgresql+psycopg://user:password@"):
        raise RuntimeError("DATABASE_URL must be configured before running Alembic.")
    return database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    connectable = create_engine(get_database_url(), pool_pre_ping=True)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
