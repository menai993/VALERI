"""Worker process: the scheduled jobs (M4 scans + M11 audit + M13 investigations).

Hosts the APScheduler scheduler: daily/weekly detection scans, the weekly
over-suppression audit, and the investigation queue poll. Structured JSON logs
(M14) so the worker's output is machine-parseable alongside the API's.
"""

import logging

from valeri_api.logging_config import setup_json_logging


def main() -> None:
    """Start the scheduler (blocks until SIGTERM/SIGINT)."""
    setup_json_logging()  # M14: structured JSON logs from the worker process
    logger = logging.getLogger("valeri.worker")

    from valeri_api.scanner.scheduler import create_scheduler

    scheduler = create_scheduler()
    logger.info("VALERI worker started: %d scheduled jobs", len(scheduler.get_jobs()))
    try:
        scheduler.start()  # blocks; handles SIGTERM/SIGINT internally
    except (KeyboardInterrupt, SystemExit):
        logger.info("VALERI worker stopped")


if __name__ == "__main__":
    main()
