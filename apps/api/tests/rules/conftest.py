"""Shared fixtures for per-rule detection tests."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session


@pytest.fixture
def rule_session(db_engine: Engine, seed_data) -> Iterator[Session]:
    """A session for rule fixtures; restores the M1 seed afterwards.

    Detection fixtures rebuild core.* from scratch, so the seed must be reloaded
    when the test is done (other test modules depend on it).
    """
    from valeri_api.seed.loader import load, reset

    with Session(db_engine) as session:
        yield session
        session.rollback()
        reset(session)
        load(seed_data, session)
        session.commit()
