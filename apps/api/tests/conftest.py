"""Shared test fixtures for the VALERI API test suite."""

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from valeri_api.config import get_settings
from valeri_api.db import get_engine


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
