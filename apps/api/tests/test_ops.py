"""P2 ops hardening: the job-run ledger, derived alerts, and the freshness guard.

job_run is operational telemetry (prunable) — distinct from the append-only
audit family. Alerts are deterministic SQL facts; thresholds live in
app.rule_config (rule 'ops'), never code.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.seed.users import FINANCE_EMAIL, OWNER_EMAIL


def _clear_job_runs(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM app.job_run"))
        conn.commit()


def _insert_run(engine: Engine, job: str, status: str, error: str | None = None) -> int:
    with engine.connect() as conn:
        run_id = conn.execute(
            text(
                "INSERT INTO app.job_run (job, started_at, finished_at, status, error) "
                "VALUES (:job, now(), now(), :status, :error) RETURNING id"
            ),
            {"job": job, "status": status, "error": error},
        ).scalar_one()
        conn.commit()
    return run_id


# ── the ledger wrapper ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_job_run_recorded_ok_and_failed(db_engine: Engine) -> None:
    """record_job_run writes running→ok, running→failed(+error), and skipped rows —
    and the failure row survives even though the wrapped job raised."""
    from valeri_api.ops.runs import record_job_run

    _clear_job_runs(db_engine)

    with record_job_run("test_job"):
        pass  # success path

    with pytest.raises(RuntimeError):
        with record_job_run("test_job"):
            raise RuntimeError("boom")

    with record_job_run("test_job") as run:
        run.skip("stale data")

    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT status, error, finished_at FROM app.job_run "
                "WHERE job = 'test_job' ORDER BY id"
            )
        ).all()
    assert [row.status for row in rows] == ["ok", "failed", "skipped"]
    assert rows[1].error and "boom" in rows[1].error
    assert all(row.finished_at is not None for row in rows)
    _clear_job_runs(db_engine)


# ── alert derivation ──────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_consecutive_failures_alert(db_engine: Engine) -> None:
    """N consecutive failures (threshold from rule_config) → one alert; an 'ok'
    in between resets the streak."""
    from valeri_api.ops.runs import derive_alerts

    _clear_job_runs(db_engine)
    _insert_run(db_engine, "daily_scan", "failed", "err1")
    _insert_run(db_engine, "daily_scan", "failed", "err2")

    with Session(db_engine) as session:
        alerts = derive_alerts(session)
    kinds = {alert["kind"] for alert in alerts}
    assert "job_failures" in kinds
    failure_alert = next(a for a in alerts if a["kind"] == "job_failures")
    assert "daily_scan" in failure_alert["message"]

    # An ok run resets the streak → no job_failures alert.
    _insert_run(db_engine, "daily_scan", "ok")
    with Session(db_engine) as session:
        alerts = derive_alerts(session)
    assert "job_failures" not in {alert["kind"] for alert in alerts}
    _clear_job_runs(db_engine)


@pytest.mark.anyio
async def test_backup_unverified_alert(db_engine: Engine) -> None:
    """No (or stale) backup_restore_check run → 'backup_unverified' alert; a
    recent ok run clears it."""
    from valeri_api.ops.runs import derive_alerts

    _clear_job_runs(db_engine)
    with Session(db_engine) as session:
        kinds = {alert["kind"] for alert in derive_alerts(session)}
    assert "backup_unverified" in kinds

    _insert_run(db_engine, "backup_restore_check", "ok")
    with Session(db_engine) as session:
        kinds = {alert["kind"] for alert in derive_alerts(session)}
    assert "backup_unverified" not in kinds
    _clear_job_runs(db_engine)


# ── the freshness guard ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_scan_freshness_guard(db_session: Session) -> None:
    """A DB with no/stale invoices → the scan SKIPS (reason recorded) instead of
    silently scanning old data; fresh data → the scan runs."""
    from valeri_api.scanner.scan import run_scan

    # Age every invoice past the threshold (inside the rolled-back txn) → stale.
    db_session.execute(text("UPDATE core.invoice SET date = date - 400"))
    result = run_scan(db_session, create_tasks=False)
    assert result.skipped_reason is not None
    assert result.total_inserted == 0

    # One fresh invoice → the guard passes and the rules execute.
    cid = db_session.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar_one()
    db_session.execute(
        text(
            "INSERT INTO core.invoice (customer_id, date, total) "
            "VALUES (:cid, CURRENT_DATE, 100)"
        ),
        {"cid": cid},
    )
    result = run_scan(db_session, create_tasks=False, recompute=False)
    assert result.skipped_reason is None


@pytest.mark.anyio
async def test_data_stale_alert(db_engine: Engine, seeded_db: Engine) -> None:
    """Seeded data is fresh → no data_stale alert (the positive control)."""
    from valeri_api.ops.runs import derive_alerts

    with Session(seeded_db) as session:
        kinds = {alert["kind"] for alert in derive_alerts(session)}
    assert "data_stale" not in kinds


# ── the ops-status endpoint ───────────────────────────────────────────────────


@pytest.mark.anyio
async def test_ops_status_matches_sql_and_rbac(seeded_db: Engine, seed_data) -> None:
    _clear_job_runs(seeded_db)
    _insert_run(seeded_db, "daily_scan", "ok")
    _insert_run(seeded_db, "daily_scan", "failed", "x")

    owner = make_client()
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep = make_client()
    finance = make_client()
    try:
        await login(owner, OWNER_EMAIL)
        body = (await owner.get("/api/admin/ops/status")).json()

        scan_row = next(j for j in body["jobs"] if j["job"] == "daily_scan")
        assert scan_row["last_status"] == "failed"
        assert scan_row["consecutive_failures"] == 1
        assert scan_row["last_ok_at"] is not None
        assert "data_freshness" in body and body["data_freshness"]["stale"] is False
        assert isinstance(body["alerts"], list)

        await login(rep, rep_user["email"])
        assert (await rep.get("/api/admin/ops/status")).status_code == 403
        await login(finance, FINANCE_EMAIL)
        assert (await finance.get("/api/admin/ops/status")).status_code == 403
    finally:
        await owner.aclose()
        await rep.aclose()
        await finance.aclose()
        _clear_job_runs(seeded_db)
