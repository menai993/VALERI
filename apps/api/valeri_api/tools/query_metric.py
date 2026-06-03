"""Tool: query_metric — one registered metric from the semantic layer.

Only metrics in the semantic registry can run (no free-form SQL, structurally).
RBAC (spec D2): a sales_rep may only query metrics scoped to their own customers;
company-wide metrics are finance data and are blocked for reps.
"""

import datetime
from typing import Any

from pydantic import BaseModel, Field

from valeri_api.semantic.query_builder import MetricValidationError, run_metric
from valeri_api.semantic.registry import load_registry
from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError, ToolPermissionError

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class QueryMetricInput(BaseModel):
    """Which metric to run and its (optional) scope parameters."""

    metric: str = Field(min_length=1)
    customer_id: int | None = None
    article_id: int | None = None
    category_id: int | None = None
    segment: str | None = None
    from_date: datetime.date | None = None
    to_date: datetime.date | None = None


class QueryMetricOutput(BaseModel):
    """The metric result: SQL values passed through, never recomputed."""

    metric: str
    grain: str
    value: Any | None = None  # scalar metrics
    rows: list[dict[str, Any]] = []  # series metrics
    params_used: dict[str, Any] = {}


def _run(tool_input: QueryMetricInput, context: ToolContext) -> QueryMetricOutput:
    registry = load_registry()
    definition = registry.get(tool_input.metric)
    if definition is None:
        raise ToolError(f"Nepoznata metrika: {tool_input.metric!r}")

    declared = {param.name for param in definition.params}

    # Build params from the input, keeping only what this metric accepts.
    candidates: dict[str, Any] = {
        "customer_id": tool_input.customer_id,
        "article_id": tool_input.article_id,
        "category_id": tool_input.category_id,
        "segment": tool_input.segment,
        "from_date": tool_input.from_date,
        "to_date": tool_input.to_date,
    }
    params = {
        key: value for key, value in candidates.items() if key in declared and value is not None
    }

    # ── RBAC (D2): reps only get customer-scoped data for their own customers ──
    if context.user.role == "sales_rep":
        customer_id = params.get("customer_id")
        if customer_id is None:
            raise ToolPermissionError(
                "Komercijalista ne može pokretati metrike na nivou cijele firme "
                "(finansijski podaci) — navedite kupca iz vašeg portfelja"
            )
        context.assert_customer_visible(customer_id)

    try:
        result = run_metric(context.session, tool_input.metric, params)
    except MetricValidationError as error:
        raise ToolError(str(error)) from error

    return QueryMetricOutput(
        metric=result.metric,
        grain=result.grain,
        value=result.scalar() if result.grain == "scalar" else None,
        rows=result.rows if result.grain != "scalar" else [],
        params_used=params,
    )


QUERY_METRIC = ToolDefinition(
    name="query_metric",
    description=(
        "Vraća jednu registrovanu metriku (promet, promet po mjesecima, promet kupca u 60 dana, "
        "osnovica kupca, zadnja narudžba, prosječni razmak narudžbi). Parametri: metric, "
        "customer_id?, from_date?, to_date?, segment?"
    ),
    input_schema=QueryMetricInput,
    output_schema=QueryMetricOutput,
    allowed_roles=ALL_ROLES,
    run=_run,
)
