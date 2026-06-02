"""Placeholder worker process (M0).

The real scheduler (APScheduler weekly/daily scans) lands in M4; async
investigations land in M13. This placeholder keeps the compose `worker`
service running and proves the image/process wiring.
"""

import logging
import signal
import threading

logger = logging.getLogger("valeri.worker")

HEARTBEAT_SECONDS = 60.0

_stop = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("received signal %s — shutting down", signum)
    _stop.set()


def main() -> None:
    """Run the worker loop until SIGTERM/SIGINT."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("VALERI worker started (placeholder — scheduler lands in M4)")
    while not _stop.is_set():
        logger.info("VALERI worker idle (scheduler lands in M4)")
        _stop.wait(HEARTBEAT_SECONDS)
    logger.info("VALERI worker stopped")


if __name__ == "__main__":
    main()
