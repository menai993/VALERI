"""Stub tools: propose_rule_change (M10) and start_investigation (M13).

They exist now so the intent router and the catalog contract stay stable; they
answer honestly that the capability arrives in a later milestone, mutate nothing,
and are still fully logged (no silent paths).
"""

from pydantic import BaseModel

from valeri_api.tools.base import ToolContext, ToolDefinition

ALL_ROLES = ("owner", "admin", "finance", "sales_rep")


class ProposeRuleChangeInput(BaseModel):
    reason: str | None = None
    signal_id: int | None = None


class StartInvestigationInput(BaseModel):
    question: str | None = None
    signal_id: int | None = None


class StubOutput(BaseModel):
    """An honest 'not yet available' answer (register analiza, nothing happened)."""

    available: bool
    milestone: str
    message: str


def _run_propose_rule_change(
    tool_input: ProposeRuleChangeInput, context: ToolContext
) -> StubOutput:
    return StubOutput(
        available=False,
        milestone="M10",
        message=(
            "Samokonfiguracija (učenje pravila iz odbacivanja) stiže u milestone-u M10. "
            "Vaš razlog je zabilježen u logu razgovora."
        ),
    )


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


PROPOSE_RULE_CHANGE = ToolDefinition(
    name="propose_rule_change",
    description=(
        "Predlaže promjenu pravila detekcije na osnovu povratne informacije "
        "(npr. 'ne prijavljuj sezonske kupce'). Parametri: reason?, signal_id?"
    ),
    input_schema=ProposeRuleChangeInput,
    output_schema=StubOutput,
    allowed_roles=ALL_ROLES,
    run=_run_propose_rule_change,
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
