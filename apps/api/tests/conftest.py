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

# P2 request gates are exercised explicitly in test_middleware.py; everywhere
# else they stay off so the ~400 existing HTTP tests don't need CSRF headers.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CSRF_ENABLED", "false")

# P3 answer cache is exercised in test_llm_answer_cache.py; off everywhere else so
# a test sending the same simple_qa prompt twice still calls its fake both times.
os.environ.setdefault("LLM_ANSWER_CACHE_TTL_SECONDS", "0")


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


# ── Auth fixtures (M8): cookie-carrying ASGI clients per role ────────────────


async def login(client: httpx.AsyncClient, email: str, password: str | None = None) -> None:
    """Log an ASGI client in as a seed user; the session cookie stays in its jar."""
    from valeri_api.seed.users import DEV_PASSWORD

    response = await client.post(
        "/api/auth/login", json={"email": email, "password": password or DEV_PASSWORD}
    )
    assert response.status_code == 200, f"login failed for {email}: {response.text}"


def make_client() -> httpx.AsyncClient:
    """A fresh (unauthenticated) ASGI client."""
    from valeri_api.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def owner_client(seeded_db) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as the seeded owner."""
    from valeri_api.seed.users import OWNER_EMAIL

    client = make_client()
    await login(client, OWNER_EMAIL)
    yield client
    await client.aclose()


@pytest.fixture
async def admin_client(seeded_db) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as the seeded admin."""
    from valeri_api.seed.users import ADMIN_EMAIL

    client = make_client()
    await login(client, ADMIN_EMAIL)
    yield client
    await client.aclose()


@pytest.fixture
async def finance_client(seeded_db) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as the seeded finance user."""
    from valeri_api.seed.users import FINANCE_EMAIL

    client = make_client()
    await login(client, FINANCE_EMAIL)
    yield client
    await client.aclose()


@pytest.fixture
async def rep_client(seeded_db, seed_data) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as the first seeded sales rep."""
    rep_user = next(user for user in seed_data.app_users if user["role"] == "sales_rep")
    client = make_client()
    await login(client, rep_user["email"])
    yield client
    await client.aclose()
