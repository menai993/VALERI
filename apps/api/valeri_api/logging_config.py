"""Structured JSON logging (M14): one JSON object per line, for every service.

Docker-native: logs go to stdout as JSON lines, so any aggregator can parse them
without a custom decoder. The formatter emits metadata only — timestamp, level,
logger, message, and any explicit `extra=` fields — and NEVER request bodies,
prompt payloads, or PII (principle 6: masking is upstream; logs add no new
exposure surface).
"""

import datetime
import json
import logging
from typing import Any

# LogRecord attributes that are framework noise, not message content — never emitted.
_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON line (ts, level, logger, message + extras)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.datetime.fromtimestamp(record.created, tz=datetime.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Explicit extras (logger.info(..., extra={...})) pass through as fields.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_json_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger (idempotent).

    Replaces any existing handlers so app + uvicorn + worker all emit one JSON
    line per record. Call once at process startup (API app factory / worker main).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn keeps its own handlers by default — route them through root instead
    # so access/error lines are JSON too.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
