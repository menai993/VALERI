"""Health endpoint — liveness plus dependency probes (P2).

Always 200 (the M0 contract): a down dependency degrades the body, never the
status code. Probes: db (SELECT 1), llm_gateway (LiteLLM liveness, short
timeout), worker (heartbeat row age), migrations (alembic_version vs repo head).
"""

from pathlib import Path

import httpx
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Connection, text

from valeri_api.config import get_settings
from valeri_api.db import get_engine

router = APIRouter()

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class HealthResponse(BaseModel):
    """Status of the API process and each dependency it needs to be useful."""

    status: str  # ok | degraded
    db: str  # ok | unavailable
    llm_gateway: str  # ok | unavailable
    worker: str  # ok | stale
    migrations: str  # ok | behind | unknown


def _probe_llm() -> str:
    """LiteLLM liveness (unauthenticated, no model call); short timeout."""
    settings = get_settings()
    url = f"{settings.litellm_base_url.rstrip('/')}/health/liveliness"
    try:
        response = httpx.get(url, timeout=settings.llm_health_timeout_seconds)
        return "ok" if response.status_code < 500 else "unavailable"
    except httpx.HTTPError:
        return "unavailable"


def _repo_migration_head() -> str:
    """The newest migration revision shipped with this build."""
    return ScriptDirectory(str(_MIGRATIONS_DIR)).get_current_head() or ""


def _probe_worker(conn: Connection) -> str:
    """Fresh heartbeat row (written by the worker's poll loop) → ok, else stale."""
    age = conn.execute(
        text(
            "SELECT extract(epoch FROM (now() - coalesce(finished_at, started_at))) "
            "FROM app.job_run WHERE job = 'worker_heartbeat' ORDER BY id DESC LIMIT 1"
        )
    ).scalar_one_or_none()
    if age is None or age > get_settings().worker_heartbeat_stale_seconds:
        return "stale"
    return "ok"


def _probe_migrations(conn: Connection) -> str:
    """Applied alembic revision must match the repo head (catch un-migrated deploys)."""
    applied = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    return "ok" if applied == _repo_migration_head() else "behind"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness/readiness probe. Always 200; the fields report dependency state."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            worker = _probe_worker(conn)
            migrations = _probe_migrations(conn)
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
        worker = "stale"
        migrations = "unknown"
    llm = _probe_llm()
    all_ok = (db_status, llm, worker, migrations) == ("ok", "ok", "ok", "ok")
    return HealthResponse(
        status="ok" if all_ok else "degraded",
        db=db_status,
        llm_gateway=llm,
        worker=worker,
        migrations=migrations,
    )
