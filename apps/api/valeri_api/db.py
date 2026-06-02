"""SQLAlchemy 2.x engine/session wiring. Models are added from M1 onward."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from valeri_api.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all VALERI models (populated from M1)."""


@lru_cache
def get_engine() -> Engine:
    """Cached engine bound to the configured database (cache is cleared in tests)."""
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a DB session."""
    factory = sessionmaker(bind=get_engine())
    session = factory()
    try:
        yield session
    finally:
        session.close()
