"""Shared test fixtures for the VALERI API test suite."""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from valeri_api.config import get_settings
from valeri_api.db import get_engine

API_ROOT = Path(__file__).resolve().parent.parent

# Tests never talk to a real LLM gateway: narration stays disabled unless a test
# explicitly injects a (fake) client. The production default remains enabled.
os.environ.setdefault("LLM_NARRATION_ENABLED", "false")


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests on asyncio (anyio pytest plugin)."""
    return "asyncio"


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    """Give every test fresh settings/engine so env monkeypatching takes effect."""
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client against the ASGI app, no running server needed."""
    from valeri_api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Database fixtures (M1+) ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Session-scoped engine against the test database, migrated to head.

    Skips DB-dependent tests when PostgreSQL is not reachable (they run in CI
    and against a local postgres / the compose db service).
    """
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("PostgreSQL not reachable in this environment (runs in CI and compose)")

    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig(str(API_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    command.upgrade(alembic_cfg, "head")

    yield engine


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Function-scoped session inside a transaction that always rolls back."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ── Seed fixtures (M1+): shared by seed, capability, and later milestone tests ─

TEST_RNG_SEED = 20260601


@pytest.fixture(scope="session")
def seed_data():
    """Generate the seed once, in memory, with fixed parameters."""
    import datetime

    from valeri_api.seed.config import SeedConfig
    from valeri_api.seed.generate import generate

    config = SeedConfig(rng_seed=TEST_RNG_SEED, as_of=datetime.date.today())
    return generate(config)


@pytest.fixture(scope="session")
def seeded_db(db_engine: Engine, seed_data) -> Engine:
    """Load the generated seed into the test database (once per session)."""
    from valeri_api.seed.loader import load, reset

    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()
    return db_engine
