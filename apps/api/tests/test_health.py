"""GET /api/health: M0 liveness contract (always 200) + P2 dependency probes.

Probes are monkeypatched at their seams (no real LiteLLM in tests); the worker
probe reads the real heartbeat row; migrations compare alembic_version to the
repo head. `status` carries the verdict — degraded never turns into a 500.
"""

import httpx
import pytest
from sqlalchemy import Engine, text

from tests.conftest import make_client
from valeri_api.config import get_settings
from valeri_api.db import get_engine


def _set_heartbeat(engine: Engine, fresh: bool) -> None:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM app.job_run WHERE job = 'worker_heartbeat'"))
        if fresh:
            conn.execute(
                text(
                    "INSERT INTO app.job_run (job, status, finished_at) "
                    "VALUES ('worker_heartbeat', 'ok', now())"
                )
            )
        conn.commit()


# ── M0 contract: always 200, never a 500 on a down dependency ─────────────────


@pytest.mark.anyio
async def test_health_returns_200(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["db"] in {"ok", "unavailable"}


@pytest.mark.anyio
async def test_health_degrades_gracefully_without_db(
    monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:9/nothing")
    get_settings.cache_clear()
    get_engine.cache_clear()

    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "unavailable"
    assert body["status"] == "degraded"


# ── P2 probes ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_health_ok_when_all_up(db_engine: Engine, monkeypatch) -> None:
    import valeri_api.api.health as health

    monkeypatch.setattr(health, "_probe_llm", lambda: "ok")
    _set_heartbeat(db_engine, fresh=True)

    client = make_client()
    try:
        body = (await client.get("/api/health")).json()
        assert body == {
            "status": "ok",
            "db": "ok",
            "llm_gateway": "ok",
            "worker": "ok",
            "migrations": "ok",
        }
    finally:
        await client.aclose()
        _set_heartbeat(db_engine, fresh=False)


@pytest.mark.anyio
async def test_degraded_when_llm_unreachable(db_engine: Engine, monkeypatch) -> None:
    import valeri_api.api.health as health

    monkeypatch.setattr(health, "_probe_llm", lambda: "unavailable")
    _set_heartbeat(db_engine, fresh=True)

    client = make_client()
    try:
        body = (await client.get("/api/health")).json()
        assert body["llm_gateway"] == "unavailable"
        assert body["status"] == "degraded"
    finally:
        await client.aclose()
        _set_heartbeat(db_engine, fresh=False)


@pytest.mark.anyio
async def test_degraded_when_worker_heartbeat_missing(db_engine: Engine, monkeypatch) -> None:
    import valeri_api.api.health as health

    monkeypatch.setattr(health, "_probe_llm", lambda: "ok")
    _set_heartbeat(db_engine, fresh=False)  # no heartbeat at all

    client = make_client()
    try:
        body = (await client.get("/api/health")).json()
        assert body["worker"] == "stale"
        assert body["status"] == "degraded"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_degraded_when_migrations_behind(db_engine: Engine, monkeypatch) -> None:
    import valeri_api.api.health as health

    monkeypatch.setattr(health, "_probe_llm", lambda: "ok")
    monkeypatch.setattr(health, "_repo_migration_head", lambda: "9999_not_applied")
    _set_heartbeat(db_engine, fresh=True)

    client = make_client()
    try:
        body = (await client.get("/api/health")).json()
        assert body["migrations"] == "behind"
        assert body["status"] == "degraded"
    finally:
        await client.aclose()
        _set_heartbeat(db_engine, fresh=False)
