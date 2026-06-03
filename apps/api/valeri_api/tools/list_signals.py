"""Tool: list_signals — open detection signals with their full evidence envelopes.

Reps see only their own customers' signals (row-level RBAC, fail closed).
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from valeri_api.audit.serialization import jsonable
from valeri_api.tools.base import ToolContext, ToolDefinition

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")

_SQL = """
SELECT s.id AS signal_id, s.rule, s.customer_id, c.name AS customer_name, c.segment,
       s.article_id, s.evidence, s.confidence, s.conf_band, s.register, s.status,
       s.created_at, t.id AS task_id
FROM app.signal s
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN app.task t ON t.signal_id = s.id
WHERE s.status IN ('new', 'tasked')
  AND (CAST(:rule AS text) IS NULL OR s.rule = :rule)
  AND (CAST(:conf_band AS text) IS NULL OR s.conf_band::text = :conf_band)
  AND (CAST(:scoped AS boolean) IS FALSE
       OR s.customer_id = ANY(CAST(:customer_ids AS bigint[])))
ORDER BY s.confidence DESC, s.id
LIMIT :limit
"""


class ListSignalsInput(BaseModel):
    """Optional filters; reps are additionally scoped to their own customers."""

    rule: str | None = None
    conf_band: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ListSignalsOutput(BaseModel):
    """Open signals, strongest first, each with its evidence envelope."""

    items: list[dict[str, Any]]
    total_returned: int


def _run(tool_input: ListSignalsInput, context: ToolContext) -> ListSignalsOutput:
    scope = context.visible_customers()
    rows = context.session.execute(
        text(_SQL),
        {
            "rule": tool_input.rule,
            "conf_band": tool_input.conf_band,
            "limit": tool_input.limit,
            "scoped": scope is not None,
            "customer_ids": sorted(scope) if scope is not None else [],
        },
    ).mappings()

    items = [jsonable(dict(row)) for row in rows]
    return ListSignalsOutput(items=items, total_returned=len(items))


LIST_SIGNALS = ToolDefinition(
    name="list_signals",
    description=(
        "Lista otvorenih AI signala (padovi prometa, izgubljeni artikli, uspavani kupci...) "
        "s dokazima. Parametri: rule?, conf_band?, limit?"
    ),
    input_schema=ListSignalsInput,
    output_schema=ListSignalsOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
