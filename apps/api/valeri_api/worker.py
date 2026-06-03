"""Worker process: runs the scheduled detection scans (M4).

M0 shipped this as a placeholder loop; from M4 it hosts the APScheduler
scheduler (daily + weekly scans). Async investigations attach in M13.
"""

import logging


def main() -> None:
    """Start the scan scheduler (blocks until SIGTERM/SIGINT)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
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
