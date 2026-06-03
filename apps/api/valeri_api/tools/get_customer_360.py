"""Tool: get_customer_360 — the 360-lite metrics block for one customer.

Wraps metrics.dashboard.customer_360() (pure SQL from M8); rep-scoped.
"""

import datetime
from typing import Any

from pydantic import BaseModel

from valeri_api.metrics.dashboard import customer_360
from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class Customer360Input(BaseModel):
    customer_id: int


class Customer360Output(BaseModel):
    """The 360 metrics: header values, 12-month turnover, basket — all SQL."""

    customer_id: int
    customer_name: str
    segment: str | None
    status: str
    turnover_60d: Any | None
    baseline_60d: Any | None
    last_order_date: Any | None
    avg_order_interval_d: Any | None
    monthly_turnover: list[dict[str, Any]]
    basket: list[dict[str, Any]]


def _run(tool_input: Customer360Input, context: ToolContext) -> Customer360Output:
    # Row-level RBAC first: reps only see their own customers.
    context.assert_customer_visible(tool_input.customer_id)

    result = customer_360(context.session, tool_input.customer_id, as_of=datetime.date.today())
    if result is None:
        raise ToolError(f"Kupac {tool_input.customer_id} nema izračunate metrike")

    return Customer360Output(
        customer_id=result.customer_id,
        customer_name=result.customer_name,
        segment=result.segment,
        status=result.status,
        turnover_60d=result.turnover_60d,
        baseline_60d=result.baseline_60d,
        last_order_date=result.last_order_date,
        avg_order_interval_d=result.avg_order_interval_d,
        monthly_turnover=result.monthly_turnover,
        basket=[row.model_dump() for row in result.basket],
    )


GET_CUSTOMER_360 = ToolDefinition(
    name="get_customer_360",
    description=(
        "Kompletna slika jednog kupca: promet 60 dana, osnovica, zadnja narudžba, prosječni "
        "razmak, mjesečni promet (12 mjeseci) i korpa po kategorijama. Parametri: customer_id"
    ),
    input_schema=Customer360Input,
    output_schema=Customer360Output,
    allowed_roles=ALL_ROLES,
    run=_run,
)
