"""APScheduler wiring: daily detection scan + the weekly cycle (worker process).

The weekly Sunday-night job runs the full pipeline: scan → tasks → owner report
(M7). All of it is internal and auto-runs; customer-facing message drafts
created along the way are approval-gated and never sent automatically.
"""

import datetime
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from valeri_api.db import get_engine
from valeri_api.llm.client import LLMClient
from valeri_api.reports.models import OwnerReport
from valeri_api.scanner.scan import ScanResult, run_scan

logger = logging.getLogger("valeri.scanner.scheduler")

TIMEZONE = "Europe/Sarajevo"


def run_weekly_cycle(
    session: Session,
    as_of: datetime.date | None = None,
    client: LLMClient | None = None,
) -> tuple[ScanResult, OwnerReport]:
    """The full weekly pipeline: scan → tasks → weekly owner report → suppression audit.

    Everything here is an internal action and runs without approval; the
    customer-facing drafts the report generates are approval-gated rows.
    `client` is forwarded to report/draft/audit narration (tests inject a fake).
    """
    from valeri_api.reports.builder import build_weekly_report
    from valeri_api.selfconfig.auditor import audit_suppressions

    reference = as_of or datetime.date.today()
    scan_result = run_scan(session, as_of=as_of)
    report = build_weekly_report(session, week_end=reference, client=client)
    # M11: the over-suppression audit closes the cycle — suppressed streams are
    # re-examined every week, never forgotten.
    audit_suppressions(session, client=client)
    return scan_result, report


def scan_job() -> None:
    """One scheduled scan run (its own session/transaction)."""
    engine = get_engine()
    with Session(engine) as session:
        try:
            result = run_scan(session)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("scheduled scan failed (rolled back)")
            return
    logger.info(
        "scheduled scan done: %d new signals, %d suppressed, %d tasks created",
        result.total_inserted,
        result.total_suppressed,
        result.tasks_created,
    )


def weekly_job() -> None:
    """The Sunday-night job: scan → tasks → weekly owner report (M7)."""
    engine = get_engine()
    with Session(engine) as session:
        try:
            scan_result, report = run_weekly_cycle(session)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("weekly cycle failed (rolled back)")
            return
    logger.info(
        "weekly cycle done: %d new signals, %d suppressed, %d tasks, report %d (%s — %s)",
        scan_result.total_inserted,
        scan_result.total_suppressed,
        scan_result.tasks_created,
        report.id,
        report.week_start,
        report.week_end,
    )


def audit_job() -> None:
    """The standalone over-suppression audit (M11) — its own session/transaction.

    The weekly cycle already audits; this job exists so the audit can also run
    independently of the report pipeline. Dedup makes a re-run a no-op.
    """
    from valeri_api.selfconfig.auditor import audit_suppressions

    engine = get_engine()
    with Session(engine) as session:
        try:
            result = audit_suppressions(session)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("over-suppression audit failed (rolled back)")
            return
    logger.info(
        "over-suppression audit done: %d checked, %d flagged, %d expired",
        result.rules_checked,
        len(result.flagged),
        len(result.expired_rule_ids),
    )


def create_scheduler(
    daily_hour: int = 6,
    weekly_day_of_week: str = "sun",
    weekly_hour: int = 2,
) -> BlockingScheduler:
    """The worker's scheduler: a light daily scan + the weekly full cycle + the audit."""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        scan_job,
        CronTrigger(hour=daily_hour, minute=0, timezone=TIMEZONE),
        id="daily_scan",
        name="VALERI daily detection scan",
    )
    scheduler.add_job(
        weekly_job,
        CronTrigger(day_of_week=weekly_day_of_week, hour=weekly_hour, minute=0, timezone=TIMEZONE),
        id="weekly_scan",
        name="VALERI weekly cycle (scan + tasks + owner report)",
    )
    scheduler.add_job(
        audit_job,
        CronTrigger(
            day_of_week=weekly_day_of_week, hour=weekly_hour + 1, minute=0, timezone=TIMEZONE
        ),
        id="over_suppression_audit",
        name="VALERI over-suppression audit (Na provjeri)",
    )
    return scheduler
