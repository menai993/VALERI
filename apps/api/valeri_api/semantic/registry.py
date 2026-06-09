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
    """Load and validate the built-in YAML metric registry (cached)."""
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    metrics = raw.get("metrics", {})
    return {name: MetricDefinition(name=name, **definition) for name, definition in metrics.items()}


def active_overlay(session) -> dict[str, MetricDefinition]:
    """Active self-proposed metrics (CSA Phase 3): the DB overlay merged ON TOP of YAML.

    Only proposals a human approved (status='active') appear here, and each was
    safety-validated at approval. The built-in YAML metrics always win over an
    overlay of the same name. A malformed active row is skipped, never raised.
    """
    from valeri_api.capabilities.models import CapabilityProposal  # lazy: avoid an import cycle

    builtin = load_registry()
    overlay: dict[str, MetricDefinition] = {}
    rows = session.query(CapabilityProposal).filter(CapabilityProposal.status == "active").all()
    for row in rows:
        if row.name in builtin:
            continue  # never shadow a built-in metric
        try:
            overlay[row.name] = MetricDefinition(
                name=row.name,
                description_bs=row.description,
                description_en=row.description,
                entity=row.entity,
                grain=row.grain,
                params=[MetricParam(**param) for param in (row.params or [])],
                sql=row.sql,
            )
        except Exception:  # noqa: BLE001 — a bad active row must not break metric lookup
            continue
    return overlay


def available_metrics(session) -> dict[str, MetricDefinition]:
    """The full metric vocabulary visible to the app: built-in YAML + active overlay."""
    return {**active_overlay(session), **load_registry()}


def resolve_metric(session, metric_name: str) -> MetricDefinition | None:
    """One metric by name: built-in YAML first, then the active overlay (or None)."""
    return load_registry().get(metric_name) or active_overlay(session).get(metric_name)
