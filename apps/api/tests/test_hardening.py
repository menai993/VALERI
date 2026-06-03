"""M14 acceptance: hardening — JSON logging, backup/restore, perf budgets, query plans.

1. setup_json_logging() makes every record a parseable JSON line.
2. backup.sh → restore.sh round-trips: a restored DB has identical row counts.
3. The hot paths stay within generous perf budgets (regression guards).
4. The growth-table date-range aggregations use an index, not a seq scan.
"""

import datetime
import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

INFRA_BACKUP = Path(__file__).resolve().parents[3] / "infra" / "backup"


# ── 1. structured JSON logging ────────────────────────────────────────────────


def test_json_logging_format(capsys) -> None:
    """A log record renders as one parseable JSON line with the expected fields."""
    from valeri_api.logging_config import setup_json_logging

    setup_json_logging()
    logger = logging.getLogger("valeri.test.hardening")
    logger.info("test poruka", extra={"investigation_id": 42, "feature": "test"})

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    lines += [line for line in captured.out.splitlines() if line.strip()]
    record = next(json.loads(line) for line in lines if "test poruka" in line)

    assert record["level"] == "INFO"
    assert record["logger"] == "valeri.test.hardening"
    assert record["message"] == "test poruka"
    # ts is ISO-8601 parseable.
    datetime.datetime.fromisoformat(record["ts"])
    # explicit extras pass through; reserved/noise fields do not.
    assert record["investigation_id"] == 42
    assert record["feature"] == "test"
    assert "args" not in record and "msg" not in record


def test_json_logging_records_exceptions() -> None:
    """An exc_info log carries the traceback in the 'exc' field (one JSON object)."""
    from valeri_api.logging_config import JsonFormatter

    formatter = JsonFormatter()
    try:
        raise ValueError("bum")
    except ValueError:
        record = logging.LogRecord(
            "valeri.test", logging.ERROR, __file__, 1, "pala operacija", None, True
        )
        import sys

        record.exc_info = sys.exc_info()
    rendered = json.loads(formatter.format(record))
    assert rendered["message"] == "pala operacija"
    assert "ValueError: bum" in rendered["exc"]


# ── 2. backup / restore round-trip ────────────────────────────────────────────


def _conn_params() -> dict[str, str]:
    """psql/pg_dump connection params derived from DATABASE_URL (test DB)."""
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://valeri:valeri@localhost:5432/valeri_test"
    )
    # postgresql+psycopg://user:pass@host:port/db
    rest = url.split("://", 1)[1]
    creds, hostpart = rest.split("@", 1)
    user, password = creds.split(":", 1)
    hostport, db = hostpart.split("/", 1)
    host, port = hostport.split(":", 1)
    return {"user": user, "password": password, "host": host, "port": port, "db": db.split("?")[0]}


@pytest.mark.skipif(
    subprocess.run(["which", "pg_dump"], capture_output=True).returncode != 0,
    reason="pg_dump not available",
)
def test_backup_restore_roundtrip(seeded_db: Engine, tmp_path) -> None:
    """backup.sh dumps the seeded DB; restore.sh restores it into a scratch DB with
    identical row counts (the backup is provably restorable)."""
    params = _conn_params()
    env = {
        **os.environ,
        "PGHOST": params["host"],
        "PGPORT": params["port"],
        "POSTGRES_USER": params["user"],
        "POSTGRES_PASSWORD": params["password"],
        "POSTGRES_DB": params["db"],
        "BACKUP_DIR": str(tmp_path),
        "BACKUP_RETENTION_DAYS": "14",
    }

    # ── backup ────────────────────────────────────────────────────────────────
    result = subprocess.run(
        ["sh", str(INFRA_BACKUP / "backup.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    dumps = list(tmp_path.glob("valeri_*.dump"))
    assert len(dumps) == 1, f"expected one dump, got {dumps}"
    assert dumps[0].stat().st_size > 0

    # Source row counts (the tables that carry data).
    def counts(engine: Engine) -> dict[str, int]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT schemaname || '.' || relname, n_live_tup "
                    "FROM pg_stat_user_tables WHERE schemaname IN ('core','app','audit')"
                )
            ).all()
        return {name: n for name, n in rows if n > 0}

    source_counts = counts(seeded_db)
    assert source_counts, "the seeded DB should have data to back up"

    # ── restore into a scratch DB ─────────────────────────────────────────────
    scratch_db = f"valeri_restore_{uuid.uuid4().hex[:8]}"
    admin_url = (
        f"postgresql+psycopg://{params['user']}:{params['password']}"
        f"@{params['host']}:{params['port']}/postgres"
    )
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch_db}"'))

        restore = subprocess.run(
            ["sh", str(INFRA_BACKUP / "restore.sh"), str(dumps[0]), "--yes"],
            env={**env, "TARGET_DB": scratch_db},
            capture_output=True,
            text=True,
        )
        assert restore.returncode == 0, restore.stderr

        scratch_url = (
            f"postgresql+psycopg://{params['user']}:{params['password']}"
            f"@{params['host']}:{params['port']}/{scratch_db}"
        )
        scratch = create_engine(scratch_url)
        try:
            # ANALYZE so pg_stat_user_tables is populated, then compare via COUNT(*).
            with scratch.connect() as conn:
                for name in source_counts:
                    restored = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
                    with seeded_db.connect() as src_conn:
                        original = src_conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
                    assert restored == original, f"{name}: restored {restored} != source {original}"
        finally:
            scratch.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": scratch_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
        admin.dispose()


def test_restore_requires_confirmation() -> None:
    """restore.sh refuses to run without the explicit --yes argument."""
    result = subprocess.run(
        ["sh", str(INFRA_BACKUP / "restore.sh"), "/tmp/whatever.dump"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--yes" in result.stderr


# ── 3. perf budgets (regression guards, not benchmarks) ───────────────────────


@pytest.fixture
def perf_db(seeded_db: Engine, seed_data):
    """Seeded DB with signals + tasks already scanned (no LLM — template bodies)."""
    from valeri_api.scanner.scan import run_scan

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(seeded_db) as session:
        run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()
    return seeded_db, as_of


def test_perf_budgets(perf_db) -> None:
    """The SQL hot paths stay well within generous budgets (catch 10x regressions)."""
    from valeri_api.metrics.dashboard import assemble_dashboard, resolve_range
    from valeri_api.metrics.recompute import recompute_all
    from valeri_api.scanner.scan import run_scan

    engine, as_of = perf_db

    with Session(engine) as session:
        start = time.monotonic()
        run_scan(session, as_of=as_of, recompute=False, create_tasks=False)
        scan_seconds = time.monotonic() - start
    assert scan_seconds < 10, f"scan (no recompute) took {scan_seconds:.2f}s"

    with Session(engine) as session:
        start = time.monotonic()
        recompute_all(session, as_of=as_of)
        session.commit()
        recompute_seconds = time.monotonic() - start
    assert recompute_seconds < 10, f"recompute_all took {recompute_seconds:.2f}s"

    with Session(engine) as session:
        start = time.monotonic()
        assemble_dashboard(
            session, as_of=as_of, range_days=resolve_range("30d"), owner_report_summary=None
        )
        dashboard_seconds = time.monotonic() - start
    assert dashboard_seconds < 3, f"assemble_dashboard took {dashboard_seconds:.2f}s"


# ── 4. query plans use indexes on the growth tables ───────────────────────────


def test_invoice_date_range_uses_index(seeded_db: Engine) -> None:
    """All-customer invoice date-range aggregation uses ix_invoice_date, not a seq scan."""
    with seeded_db.connect() as conn:
        plan = "\n".join(
            row[0]
            for row in conn.execute(
                text(
                    "EXPLAIN SELECT customer_id, SUM(total) FROM core.invoice "
                    "WHERE date > CURRENT_DATE - 60 GROUP BY customer_id"
                )
            )
        )
    assert "ix_invoice_date" in plan, plan
    assert "Seq Scan on invoice" not in plan, plan
