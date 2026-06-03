"""Append-only writer for audit.llm_route_log (M12).

INSERT only — there is intentionally no other path. Every routing choice (initial
role mapping, cascade escalation, injected test client) leaves exactly one row.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from valeri_api.audit.models import LlmRouteLog


def log_route(
    session: Session,
    request_id: str,
    task_role: str,
    chosen_tier: str,
    model: str,
    reason: str,
    confidence: float | Decimal | None = None,
) -> LlmRouteLog:
    """Append one routing-decision record."""
    entry = LlmRouteLog(
        request_id=request_id,
        task_role=task_role,
        chosen_tier=chosen_tier,
        model=model,
        reason=reason,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
    )
    session.add(entry)
    session.flush()
    return entry
