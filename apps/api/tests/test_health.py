"""Smoke tests for GET /api/health (M0 acceptance)."""

import httpx
import pytest
from sqlalchemy import text

from valeri_api.config import get_settings
from valeri_api.db import get_engine


def _db_reachable() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.anyio
async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    """The health endpoint always answers 200 with status ok."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] in {"ok", "unavailable"}


@pytest.mark.anyio
async def test_health_reports_db_status(client: httpx.AsyncClient) -> None:
    """With PostgreSQL reachable, the health endpoint reports db: ok."""
    if not _db_reachable():
        pytest.skip("PostgreSQL not reachable in this environment (runs in CI and compose)")
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"


@pytest.mark.anyio
async def test_health_degrades_gracefully_without_db(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    """With an unreachable database, the API answers 200 (never 500s on a down dependency)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:9/nothing")
    get_settings.cache_clear()
    get_engine.cache_clear()

    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "unavailable"
