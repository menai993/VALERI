"""Append-only writer for app.investigation_step (the agent's full trace).

INSERT only — there is intentionally no update or delete path. Every node
execution and every tool call inside the agent leaves exactly one row, in order.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.investigation.models import InvestigationStep


def record_step(
    session: Session,
    investigation_id: int,
    node: str,
    tool: str | None = None,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
) -> InvestigationStep:
    """Append one trace entry; step_no is assigned monotonically per investigation."""
    next_no = session.execute(
        text(
            "SELECT COALESCE(MAX(step_no), 0) + 1 FROM app.investigation_step "
            "WHERE investigation_id = :id"
        ),
        {"id": investigation_id},
    ).scalar()

    step = InvestigationStep(
        investigation_id=investigation_id,
        step_no=next_no,
        node=node,
        tool=tool,
        input=jsonable(input_payload) if input_payload is not None else None,
        output=jsonable(output_payload) if output_payload is not None else None,
    )
    session.add(step)
    session.flush()
    return step
