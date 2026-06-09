"""Validated metric query builder + executor.

Only registered metrics can run; parameters are validated against the registry
and passed exclusively as bind values. SQL injection is structurally impossible:
no user/model-provided value is ever concatenated into SQL text.
"""

import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.semantic.registry import MetricDefinition, load_registry


class MetricValidationError(Exception):
    """Raised when a metric name or its parameters are invalid."""


class MetricResult(BaseModel):
    """Typed result of a metric execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    metric: str
    grain: str
    rows: list[dict[str, Any]]

    def scalar(self) -> Any:
        """The single value of a scalar metric (None when the metric matched nothing)."""
        if not self.rows:
            return None
        first_row = self.rows[0]
        if "value" in first_row:
            return first_row["value"]
        return next(iter(first_row.values()))


_TYPE_CHECKS: dict[str, Any] = {
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "date": lambda v: isinstance(v, datetime.date),
    "decimal": lambda v: isinstance(v, Decimal | int) and not isinstance(v, bool),
}


def _validate_params(definition: MetricDefinition, params: dict[str, Any]) -> dict[str, Any]:
    declared = {param.name: param for param in definition.params}

    unknown = set(params) - set(declared)
    if unknown:
        raise MetricValidationError(
            f"Metric {definition.name!r} does not accept parameters: {sorted(unknown)}"
        )

    missing = [name for name, param in declared.items() if param.required and name not in params]
    if missing:
        raise MetricValidationError(f"Metric {definition.name!r} requires parameters: {missing}")

    for key, value in params.items():
        if value is None:
            continue
        expected = declared[key].type
        if not _TYPE_CHECKS[expected](value):
            raise MetricValidationError(
                f"Metric {definition.name!r}: parameter {key!r} must be of type {expected}, "
                f"got {type(value).__name__}"
            )

    # Bind every declared parameter; absent optional parameters bind as NULL.
    return {name: params.get(name) for name in declared}


def build_metric_query(metric_name: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate and return (sql, binds) for a registered metric. Never interpolates values."""
    registry = load_registry()
    definition = registry.get(metric_name)
    if definition is None:
        raise MetricValidationError(f"Unknown metric: {metric_name!r}")
    binds = _validate_params(definition, params)
    return definition.sql, binds


def run_metric(session: Session, metric_name: str, params: dict[str, Any]) -> MetricResult:
    """Execute a registered metric (built-in OR an approved overlay metric)."""
    from valeri_api.semantic.registry import resolve_metric

    definition = resolve_metric(session, metric_name)
    if definition is None:
        raise MetricValidationError(f"Unknown metric: {metric_name!r}")
    binds = _validate_params(definition, params)
    result = session.execute(text(definition.sql), binds)
    columns = list(result.keys())
    rows = [dict(zip(columns, row, strict=True)) for row in result]
    return MetricResult(metric=metric_name, grain=definition.grain, rows=rows)
