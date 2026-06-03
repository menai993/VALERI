"""Stub tool: start_investigation (M13).

It exists now so the intent router and the catalog contract stay stable; it
answers honestly that the capability arrives in a later milestone, mutates
nothing, and is still fully logged (no silent paths).

propose_rule_change graduated to a real tool in M10 (tools/propose_rule_change.py).
"""

from pydantic import BaseModel

from valeri_api.tools.base import ToolContext, ToolDefinition

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class StartInvestigationInput(BaseModel):
    question: str | None = None
    signal_id: int | None = None


class StubOutput(BaseModel):
    """An honest 'not yet available' answer (register analiza, nothing happened)."""

    available: bool
    milestone: str
    message: str


def _run_start_investigation(
    tool_input: StartInvestigationInput, context: ToolContext
) -> StubOutput:
    return StubOutput(
        available=False,
        milestone="M13",
        message=(
            "Dubinske istrage (jači model, višekoračna analiza) stižu u milestone-u M13. "
            "Vaše pitanje je zabilježeno u logu razgovora."
        ),
    )


START_INVESTIGATION = ToolDefinition(
    name="start_investigation",
    description=(
        "Pokreće dubinsku istragu složenog pitanja jačim modelom. Parametri: question, signal_id?"
    ),
    input_schema=StartInvestigationInput,
    output_schema=StubOutput,
    allowed_roles=ALL_ROLES,
    run=_run_start_investigation,
)
