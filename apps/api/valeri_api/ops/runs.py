"""Job-run ledger + alert derivation (P2 ops hardening).

record_job_run() uses ITS OWN session so a failed job's rollback can never erase
the record of its failure. Alerts are deterministic SQL/Python-over-DB facts;
thresholds come from app.rule_config (rule 'ops'), never code.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.db import session_scope
from valeri_api.ops.models import ALERTED_JOBS, HEARTBEAT_JOB
from valeri_api.rules.engine import load_rule_config

logger = logging.getLogger("valeri.ops.runs")

# Telemetry retention (not a business threshold — infra knob, spec D5).
RETENTION_DAYS = 90


class JobRunHandle:
    """Lets the wrapped job mark itself skipped or attach detail."""

    def __init__(self) -> None:
        self.status = "ok"
        self.reason: str | None = None
        self.detail: dict[str, Any] | None = None

    def skip(self, reason: str) -> None:
        self.status = "skipped"
        self.reason = reason


@contextmanager
def record_job_run(job: str) -> Iterator[JobRunHandle]:
    """Record one job execution: running → ok|skipped|failed(+error).

    Writes happen in dedicated sessions (commit immediately), independent of the
    job's own transaction — a rolled-back job still leaves its failure row.
    """
    with session_scope() as session:
        run_id = session.execute(
            text("INSERT INTO app.job_run (job, status) VALUES (:job, 'running') RETURNING id"),
            {"job": job},
        ).scalar_one()

    handle = JobRunHandle()
    try:
        yield handle
    except Exception as error:
        with session_scope() as session:
            session.execute(
                text(
                    "UPDATE app.job_run SET status = 'failed', error = :error, "
                    "finished_at = now() WHERE id = :id"
                ),
                {"error": f"{type(error).__name__}: {error}", "id": run_id},
            )
        raise
    else:
        with session_scope() as session:
            session.execute(
                text(
                    "UPDATE app.job_run SET status = :status, error = :reason, "
                    "detail = CAST(:detail AS jsonb), finished_at = now() WHERE id = :id"
                ),
                {
                    "status": handle.status,
                    "reason": handle.reason,
                    "detail": (
                        None if handle.detail is None else json.dumps(jsonable(handle.detail))
                    ),
                    "id": run_id,
                },
            )


def heartbeat() -> None:
    """Upsert the single worker-heartbeat row (liveness for /health)."""
    with session_scope() as session:
        updated = session.execute(
            text(
                "UPDATE app.job_run SET started_at = now(), finished_at = now(), "
                "status = 'ok' WHERE job = :job"
            ),
            {"job": HEARTBEAT_JOB},
        )
        if updated.rowcount == 0:
            session.execute(
                text(
                    "INSERT INTO app.job_run (job, status, finished_at) "
                    "VALUES (:job, 'ok', now())"
                ),
                {"job": HEARTBEAT_JOB},
            )


def prune_job_runs(session: Session, retention_days: int = RETENTION_DAYS) -> int:
    """Drop telemetry older than the retention window (NOT an audit table)."""
    result = session.execute(
        text(
            "DELETE FROM app.job_run WHERE started_at < now() - make_interval(days => :days) "
            "AND job <> :heartbeat"
        ),
        {"days": retention_days, "heartbeat": HEARTBEAT_JOB},
    )
    return result.rowcount


# ── alert derivation (SQL facts; thresholds from rule_config) ─────────────────


def _job_rows(session: Session) -> list[dict[str, Any]]:
    """Last runs per alerted job, newest first (window over the ledger)."""
    rows = session.execute(
        text(
            "SELECT job, status, error, started_at, finished_at FROM ("
            "  SELECT *, row_number() OVER (PARTITION BY job ORDER BY id DESC) AS rn"
            "  FROM app.job_run WHERE job = ANY(:jobs)"
            ") ranked WHERE rn <= 10 ORDER BY job, started_at DESC"
        ),
        {"jobs": list(ALERTED_JOBS)},
    ).mappings()
    return [dict(row) for row in rows]


def job_statuses(session: Session) -> list[dict[str, Any]]:
    """Per-job rollup for the ops panel: last status, last ok, failure streak."""
    by_job: dict[str, list[dict[str, Any]]] = {}
    for row in _job_rows(session):
        by_job.setdefault(row["job"], []).append(row)

    statuses = []
    for job in ALERTED_JOBS:
        runs = by_job.get(job, [])
        streak = 0
        for run in runs:  # newest first
            if run["status"] == "failed":
                streak += 1
            else:
                break
        last_ok = next((r for r in runs if r["status"] == "ok"), None)
        statuses.append(
            {
                "job": job,
                "last_status": runs[0]["status"] if runs else None,
                "last_run_at": runs[0]["started_at"] if runs else None,
                "last_ok_at": last_ok["started_at"] if last_ok else None,
                "consecutive_failures": streak,
            }
        )
    return statuses


def data_freshness(session: Session) -> dict[str, Any]:
    """How fresh core.invoice is, against ops.scan_stale_days."""
    stale_days = int(load_rule_config(session, "ops")["scan_stale_days"])
    row = session.execute(
        text(
            "SELECT max(date) AS last_invoice_date, "
            "       (max(date) IS NULL OR max(date) < CURRENT_DATE - :days) AS stale "
            "FROM core.invoice"
        ),
        {"days": stale_days},
    ).one()
    return {
        "last_invoice_date": row.last_invoice_date,
        "stale": bool(row.stale),
        "stale_days_threshold": stale_days,
    }


def derive_alerts(session: Session) -> list[dict[str, str]]:
    """The active ops alert conditions (the bell's `alerts` count, D1: owner/admin)."""
    config = load_rule_config(session, "ops")
    failure_threshold = int(config["alert_consecutive_failures"])
    restore_max_age = int(config["restore_check_max_age_days"])

    alerts: list[dict[str, str]] = []

    for status in job_statuses(session):
        if status["consecutive_failures"] >= failure_threshold:
            alerts.append(
                {
                    "kind": "job_failures",
                    "message": (
                        f"Posao '{status['job']}' nije uspio "
                        f"{status['consecutive_failures']} puta zaredom."
                    ),
                }
            )

    freshness = data_freshness(session)
    if freshness["stale"]:
        alerts.append(
            {
                "kind": "data_stale",
                "message": (
                    "Podaci o fakturama su stariji od "
                    f"{freshness['stale_days_threshold']} dana — skeniranje je obustavljeno."
                ),
            }
        )

    restore_ok = session.execute(
        text(
            "SELECT 1 FROM app.job_run WHERE job = 'backup_restore_check' AND status = 'ok' "
            "AND started_at >= now() - make_interval(days => :days) LIMIT 1"
        ),
        {"days": restore_max_age},
    ).first()
    if restore_ok is None:
        alerts.append(
            {
                "kind": "backup_unverified",
                "message": (
                    f"Provjera vraćanja backupa nije uspješno izvršena u zadnjih "
                    f"{restore_max_age} dana."
                ),
            }
        )

    # P3: month LLM spend at/over the budget's alert_pct (the 'default' row is the
    # fallback so this fires without per-month admin upkeep).
    from valeri_api.llm.cost import budget_status

    spend = budget_status(session)
    if spend["pct"] is not None and spend["pct"] >= spend["alert_pct"]:
        alerts.append(
            {
                "kind": "llm_budget",
                "message": (
                    f"Potrošnja LLM-a je na {spend['pct']:.0f}% mjesečnog budžeta "
                    f"({spend['spent_usd']:.2f} / {spend['limit_usd']:.2f} USD)."
                ),
            }
        )

    return alerts
