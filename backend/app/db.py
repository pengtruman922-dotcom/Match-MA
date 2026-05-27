from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def engine_is_configured() -> bool:
    settings = get_settings()
    return bool(settings.sqlalchemy_database_url)


def get_engine() -> Engine:
    global _engine

    settings = get_settings()
    if not settings.sqlalchemy_database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    if _engine is None:
        _engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)

    return _session_factory


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
