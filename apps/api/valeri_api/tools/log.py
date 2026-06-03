"""Append-only writer for app.tool_call_log (M9).

INSERT only. Every dispatch writes exactly one row — successes AND failures
(permission denials, validation errors, tool errors) — so the audit trail shows
what the model attempted, not just what worked.
"""

from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.tools.models import ToolCallLog


def log_tool_call(
    session: Session,
    tool: str,
    args: dict[str, Any] | None,
    ok: bool,
    result_ref: str | None = None,
    latency_ms: int | None = None,
    message_id: int | None = None,
) -> ToolCallLog:
    """Append one tool-call record."""
    entry = ToolCallLog(
        message_id=message_id,
        tool=tool,
        args=jsonable(args) if args is not None else None,
        result_ref=result_ref,
        latency_ms=latency_ms,
        ok=ok,
    )
    session.add(entry)
    session.flush()
    return entry
