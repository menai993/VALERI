"""Tool: explain_signal — one signal's full evidence, its task, and its customer.

The evidence is returned verbatim from app.signal.evidence (SQL-computed by the
M4 detection rules) — never summarised or rewritten here.
"""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from valeri_api.audit.serialization import jsonable
from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")

_SQL = """
SELECT s.id AS signal_id, s.rule, s.customer_id, c.name AS customer_name, c.segment,
       s.article_id, s.evidence, s.confidence, s.conf_band, s.register, s.status,
       s.created_at, t.id AS task_id, t.title AS task_title, t.status AS task_status
FROM app.signal s
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN app.task t ON t.signal_id = s.id
WHERE s.id = :signal_id
"""


class ExplainSignalInput(BaseModel):
    signal_id: int


class ExplainSignalOutput(BaseModel):
    """Everything known about one signal — evidence verbatim from SQL."""

    signal_id: int
    rule: str
    customer_id: int | None
    customer_name: str | None
    segment: str | None
    article_id: int | None
    evidence: dict[str, Any]
    confidence: Any
    conf_band: str
    register: str
    status: str
    created_at: Any
    task_id: int | None
    task_title: str | None
    task_status: str | None


def _run(tool_input: ExplainSignalInput, context: ToolContext) -> ExplainSignalOutput:
    row = (
        context.session.execute(text(_SQL), {"signal_id": tool_input.signal_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ToolError(f"Signal {tool_input.signal_id} ne postoji")

    # Row-level RBAC: a rep may only explain their own customers' signals.
    if row["customer_id"] is not None:
        context.assert_customer_visible(row["customer_id"])

    return ExplainSignalOutput(**jsonable(dict(row)))


EXPLAIN_SIGNAL = ToolDefinition(
    name="explain_signal",
    description=(
        "Objašnjava jedan AI signal: puni dokaz (brojke iz baze), pouzdanost, povezani zadatak "
        "i kupac. Parametri: signal_id"
    ),
    input_schema=ExplainSignalInput,
    output_schema=ExplainSignalOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
