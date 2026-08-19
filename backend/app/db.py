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


@contextmanager
def savepoint(session: Session | None) -> Iterator[None]:
    """Run a block so its failure cannot poison the surrounding transaction.

    Swallowing an exception after a failed statement is what actually costs the
    incident: PostgreSQL puts the transaction in aborted state, so the *next*
    query is the one that raises InFailedSqlTransaction and the original error
    is gone. A SAVEPOINT gives the swallowing `except` somewhere clean to roll
    back to first.

    Two shapes are tolerated on purpose. `session` may be None — the agent
    tools are constructed without one in tests and in pure-computation paths —
    and the block may commit (the recommendation handler is inline-commit by
    design, see AGENTS.md). A commit inside the block ends the savepoint, so
    afterwards there is nothing to release; if such a block then fails, the
    whole transaction is rolled back instead, which is equally safe because
    everything before it was already committed.
    """
    begin_nested = getattr(session, "begin_nested", None)
    if begin_nested is None:
        yield
        return
    nested = begin_nested()
    try:
        yield
    except Exception:
        if nested.is_active:
            nested.rollback()
        else:
            session.rollback()
        raise
    else:
        if nested.is_active:
            nested.commit()
