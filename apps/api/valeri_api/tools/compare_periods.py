"""Tool: compare_periods — turnover of two periods + the delta, in ONE SQL query.

The delta is computed by PostgreSQL (ROUND((a/b - 1) * 100, 1)), never in Python
and never by the model. RBAC (D2): company-wide comparison is finance data —
blocked for reps; per-customer comparison requires the rep to own the customer.
"""

import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from valeri_api.tools.base import ToolContext, ToolDefinition, ToolPermissionError

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")

_SQL = """
WITH period_a AS (
    SELECT COALESCE(SUM(l.line_total), 0) AS value
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    WHERE i.date > :a_from AND i.date <= :a_to
      AND (CAST(:customer_id AS bigint) IS NULL OR i.customer_id = :customer_id)
),
period_b AS (
    SELECT COALESCE(SUM(l.line_total), 0) AS value
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    WHERE i.date > :b_from AND i.date <= :b_to
      AND (CAST(:customer_id AS bigint) IS NULL OR i.customer_id = :customer_id)
)
SELECT ROUND(a.value, 2) AS value_a,
       ROUND(b.value, 2) AS value_b,
       CASE WHEN b.value > 0
            THEN ROUND((a.value / b.value - 1) * 100, 1)
       END AS delta_pct
FROM period_a a, period_b b
"""


class ComparePeriodsInput(BaseModel):
    """Two periods to compare; optional per-customer scope."""

    period_a_from: datetime.date
    period_a_to: datetime.date
    period_b_from: datetime.date
    period_b_to: datetime.date
    customer_id: int | None = None


class PeriodValue(BaseModel):
    from_date: datetime.date
    to_date: datetime.date
    value: Any


class ComparePeriodsOutput(BaseModel):
    """Both totals + the SQL-computed delta."""

    period_a: PeriodValue
    period_b: PeriodValue
    delta_pct: Any | None
    customer_id: int | None = None


def _run(tool_input: ComparePeriodsInput, context: ToolContext) -> ComparePeriodsOutput:
    # ── RBAC (D2) ─────────────────────────────────────────────────────────────
    if context.user.role == "sales_rep":
        if tool_input.customer_id is None:
            raise ToolPermissionError(
                "Komercijalista ne može porediti promet cijele firme — navedite kupca "
                "iz vašeg portfelja"
            )
        context.assert_customer_visible(tool_input.customer_id)

    row = context.session.execute(
        text(_SQL),
        {
            "a_from": tool_input.period_a_from,
            "a_to": tool_input.period_a_to,
            "b_from": tool_input.period_b_from,
            "b_to": tool_input.period_b_to,
            "customer_id": tool_input.customer_id,
        },
    ).one()

    return ComparePeriodsOutput(
        period_a=PeriodValue(
            from_date=tool_input.period_a_from, to_date=tool_input.period_a_to, value=row.value_a
        ),
        period_b=PeriodValue(
            from_date=tool_input.period_b_from, to_date=tool_input.period_b_to, value=row.value_b
        ),
        delta_pct=row.delta_pct,
        customer_id=tool_input.customer_id,
    )


COMPARE_PERIODS = ToolDefinition(
    name="compare_periods",
    description=(
        "Poredi ukupan promet dva vremenska perioda (i razliku u procentima). Parametri: "
        "period_a_from, period_a_to, period_b_from, period_b_to, customer_id?"
    ),
    input_schema=ComparePeriodsInput,
    output_schema=ComparePeriodsOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
