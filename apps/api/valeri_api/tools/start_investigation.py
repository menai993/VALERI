"""Tool: start_investigation — the real investigation starter (M13, replaces the stub).

Creates a queued app.investigation; the worker runs it asynchronously. The
investigation row itself is the visible, append-only record of this action (it
appears in AI Report → Istrage with its full trace) — no app.decision is written
because nothing configurable changed and nothing external happened; the dispatch
is still fully recorded in app.tool_call_log.
"""

from pydantic import BaseModel, Field

from valeri_api.tools.base import ToolContext, ToolDefinition

# Spec D4: investigations are owner-level deep analysis (reps/finance ask via the owner).
INVESTIGATION_ROLES = ("owner", "admin")


class StartInvestigationInput(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    signal_id: int | None = None


class StartInvestigationOutput(BaseModel):
    """What the chat shows: the queued investigation + where to follow it."""

    investigation_id: int
    status: str
    question: str
    register: str = "analiza"
    message: str


def _run(tool_input: StartInvestigationInput, context: ToolContext) -> StartInvestigationOutput:
    from valeri_api.investigation.runner import create_investigation

    investigation = create_investigation(
        context.session,
        tool_input.question,
        context.user,
        signal_id=tool_input.signal_id,
        trigger="user",
    )
    return StartInvestigationOutput(
        investigation_id=investigation.id,
        status=investigation.status,
        question=investigation.question,
        message=(
            f"Istraga #{investigation.id} je pokrenuta i obrađuje se u pozadini jačim modelom. "
            "Rezultat (nalazi + dokazi + preporuka) će biti dostupan u AI Report → Istrage."
        ),
    )


START_INVESTIGATION = ToolDefinition(
    name="start_investigation",
    description=(
        "Pokreće dubinsku istragu složenog pitanja jačim modelom (asinhrono, u pozadini). "
        "Parametri: question, signal_id?"
    ),
    input_schema=StartInvestigationInput,
    output_schema=StartInvestigationOutput,
    allowed_roles=INVESTIGATION_ROLES,
    run=_run,
    mutates=True,
)
