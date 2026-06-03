"""Append-only writer for audit.ai_log: one row per LLM call.

INSERT only — there is intentionally no update or delete path (principle 7).
Every call is logged, including rejected/failed attempts (full auditability).
"""

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.models import AiLog
from valeri_api.audit.serialization import jsonable


def log_ai_call(
    session: Session,
    model: str,
    masked_input: dict[str, Any],
    output: dict[str, Any] | None,
    confidence: Decimal | float | None = None,
    register: str | None = None,
    tokens: int | None = None,
    latency_ms: int | None = None,
) -> AiLog:
    """Append one LLM-call record. masked_input must already be PII-free."""
    entry = AiLog(
        model=model,
        masked_input=jsonable(masked_input),
        output=jsonable(output) if output is not None else None,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
        register=register,
        tokens=tokens,
        latency_ms=latency_ms,
    )
    session.add(entry)
    session.flush()
    return entry
