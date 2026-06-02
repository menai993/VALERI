"""APScheduler wiring: weekly + daily detection scans (run by the worker process)."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from valeri_api.db import get_engine
from valeri_api.scanner.scan import run_scan

logger = logging.getLogger("valeri.scanner.scheduler")

TIMEZONE = "Europe/Sarajevo"


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
        "scheduled scan done: %d new signals, %d suppressed",
        result.total_inserted,
        result.total_suppressed,
    )


def create_scheduler(
    daily_hour: int = 6,
    weekly_day_of_week: str = "sun",
    weekly_hour: int = 2,
) -> BlockingScheduler:
    """The worker's scheduler: a light daily scan + a weekly full scan."""
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        scan_job,
        CronTrigger(hour=daily_hour, minute=0, timezone=TIMEZONE),
        id="daily_scan",
        name="VALERI daily detection scan",
    )
    scheduler.add_job(
        scan_job,
        CronTrigger(day_of_week=weekly_day_of_week, hour=weekly_hour, minute=0, timezone=TIMEZONE),
        id="weekly_scan",
        name="VALERI weekly detection scan",
    )
    return scheduler
