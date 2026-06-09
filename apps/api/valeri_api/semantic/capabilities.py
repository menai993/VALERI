"""Capability self-description (CSA): the agent's machine-readable map of what the
platform can answer — registered metrics + the safe tool catalog, RBAC-filtered.

This lists CAPABILITIES (names, Bosnian descriptions, parameters), never business
numbers (Principle 1 untouched). The intent/planner prompt is built from this, so
a newly registered metric or tool is automatically known to the agent — no prompt
edits, no hard-coded lists. Adding a metric to registry.yaml IS configuring the
agent.
"""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.semantic.registry import available_metrics

_REP_ROLE = "sales_rep"
# Surfaced via their metrics / handled elsewhere, not as standalone planner tools.
_HIDDEN_TOOLS = {"query_metric", "describe_capabilities"}


class CapabilityDescriptor(BaseModel):
    """One thing the platform can do, as the planner/introspection sees it."""

    kind: Literal["metric", "tool"]
    name: str
    description: str  # Bosnian (description_bs / tool description)
    params: list[str]  # param names; optional ones suffixed with '?'
    entity: str | None = None  # metrics only


def _metric_descriptors(session: Session, user_role: str) -> list[CapabilityDescriptor]:
    descriptors: list[CapabilityDescriptor] = []
    for name, definition in available_metrics(session).items():
        param_names = {param.name for param in definition.params}
        # A rep can only run metrics that can be scoped to a customer; pure
        # company/segment-wide metrics are finance data (blocked for reps, D2).
        if user_role == _REP_ROLE and "customer_id" not in param_names:
            continue
        params = [f"{param.name}{'' if param.required else '?'}" for param in definition.params]
        descriptors.append(
            CapabilityDescriptor(
                kind="metric",
                name=name,
                description=definition.description_bs,
                params=params,
                entity=definition.entity,
            )
        )
    return descriptors


def _tool_descriptors(user_role: str) -> list[CapabilityDescriptor]:
    from valeri_api.tools.catalog import TOOLS  # lazy import: avoids a catalog↔capabilities cycle

    descriptors: list[CapabilityDescriptor] = []
    for name, tool in TOOLS.items():
        if name in _HIDDEN_TOOLS or user_role not in tool.allowed_roles:
            continue
        params = [
            f"{field}{'' if info.is_required() else '?'}"
            for field, info in tool.input_schema.model_fields.items()
        ]
        descriptors.append(
            CapabilityDescriptor(
                kind="tool", name=name, description=tool.description, params=params
            )
        )
    return descriptors


def list_capabilities(session: Session, user_role: str) -> list[CapabilityDescriptor]:
    """The full RBAC-filtered capability catalog for a role: metrics (incl. approved
    overlay) + tools."""
    return _metric_descriptors(session, user_role) + _tool_descriptors(user_role)
