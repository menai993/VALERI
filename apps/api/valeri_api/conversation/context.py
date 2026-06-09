"""Conversation slot memory (CSA Phase 2).

Carries the last period + metrics used in a conversation so a follow-up like
"a prošli mjesec?" / "isto za restorane?" can be answered without the user
repeating context. Read-only and deterministic — derived from the recorded
tool-call params on recent assistant messages (never the model guessing).
"""

from typing import Any

from sqlalchemy.orm import Session

from valeri_api.conversation.models import Message

_HISTORY_WINDOW = 8


def prior_context(session: Session, conversation_id: int) -> dict[str, Any]:
    """The most recent period + metrics this conversation used, for the agent prompt."""
    rows = (
        session.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.role == "assistant")
        .order_by(Message.id.desc())
        .limit(_HISTORY_WINDOW)
        .all()
    )

    period: dict[str, str] | None = None
    metrics: list[str] = []
    for message in rows:
        for call in message.tool_calls or []:
            params = call.get("params") or {}
            if period is None and params.get("from_date") and params.get("to_date"):
                period = {"from_date": params["from_date"], "to_date": params["to_date"]}
            metric = params.get("metric")
            if metric and metric not in metrics:
                metrics.append(metric)
        if period is not None and metrics:
            break

    context: dict[str, Any] = {}
    if period is not None:
        context["zadnji_period"] = period
    if metrics:
        context["zadnje_metrike"] = metrics[:4]
    return context
