"""Append-only writer for app.decision (M9+; the M10 self-config loop reuses it).

INSERT only — there is intentionally no update or delete path. A revert is a NEW
decision (kind='undo') that references the original via reverted_decision_id.
"""

from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.models import DECISION_KINDS, Decision
from valeri_api.audit.serialization import jsonable


def log_decision(
    session: Session,
    kind: str,
    actor: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    reversible: bool = True,
    reverted_decision_id: int | None = None,
) -> Decision:
    """Append one decision record ("show the decision on the platform")."""
    if kind not in DECISION_KINDS:
        raise ValueError(f"Unknown decision kind {kind!r}; allowed: {DECISION_KINDS}")
    if actor not in ("valeri", "user"):
        raise ValueError(f"Unknown actor {actor!r}; allowed: 'valeri', 'user'")

    decision = Decision(
        kind=kind,
        actor=actor,
        summary=summary,
        payload=jsonable(payload) if payload is not None else None,
        reversible=reversible,
        reverted_decision_id=reverted_decision_id,
    )
    session.add(decision)
    session.flush()
    return decision
