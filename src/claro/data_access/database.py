from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from claro.config.settings import ClaroSettings


def create_database_engine(settings: ClaroSettings) -> Engine:
    url = settings.resolved_database_url()
    if url.startswith("sqlite:"):
        database = make_url(url).database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if database in {None, ":memory:"}:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, echo=settings.database.echo, **kwargs)

    return create_engine(
        url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout,
        pool_pre_ping=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
