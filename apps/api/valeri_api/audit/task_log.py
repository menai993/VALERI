"""Append-only writer for audit.task_log.

This module exposes INSERT only. There is intentionally no update or delete
path: the task log is an immutable history (principle 7).
"""

from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.models import TaskLog
from valeri_api.audit.serialization import jsonable

# The recognised lifecycle events (docs/data-model.md).
TASK_EVENTS = ("created", "assigned", "viewed", "actioned", "outcome", "feedback")


def log_task_event(
    session: Session, task_id: int, event: str, payload: dict[str, Any] | None = None
) -> TaskLog:
    """Append one lifecycle event for a task. Never updates or deletes."""
    if event not in TASK_EVENTS:
        raise ValueError(f"Unknown task event {event!r}; expected one of {TASK_EVENTS}")

    entry = TaskLog(task_id=task_id, event=event, payload=jsonable(payload) if payload else None)
    session.add(entry)
    session.flush()
    return entry
