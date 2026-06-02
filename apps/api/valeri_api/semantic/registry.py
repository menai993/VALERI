"""Metric registry: Pydantic-validated definitions loaded from registry.yaml."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"

ParamType = Literal["integer", "string", "date", "decimal"]


class MetricParam(BaseModel):
    """One accepted parameter of a registered metric."""

    name: str
    type: ParamType
    required: bool = False


class MetricDefinition(BaseModel):
    """A registered metric: where its number comes from and what it accepts."""

    name: str
    description_bs: str
    description_en: str
    entity: Literal["customer", "article", "segment", "company"]
    grain: Literal["scalar", "row", "series"]
    params: list[MetricParam] = []
    sql: str

    @field_validator("sql")
    @classmethod
    def sql_uses_bind_params_only(cls, value: str) -> str:
        """Reject any SQL that could be string-interpolated (injection surface)."""
        forbidden = ("%s", "%(", "{", "}")
        for token in forbidden:
            if token in value:
                raise ValueError(
                    f"SQL must use named bind parameters only; found forbidden token {token!r}"
                )
        return value


@lru_cache
def load_registry() -> dict[str, MetricDefinition]:
    """Load and validate the metric registry (cached)."""
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    metrics = raw.get("metrics", {})
    return {name: MetricDefinition(name=name, **definition) for name, definition in metrics.items()}
