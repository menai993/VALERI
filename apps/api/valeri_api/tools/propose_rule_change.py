"""Tool: propose_rule_change — the real self-configuration tool (M10, replaces the stub).

Runs the selfconfig proposer: reason (+ optional signal) → structured rule change →
graduated autonomy → learned rule (+ reversible decision when auto-applied).
The /tool mutation contract holds: every behaviour-changing application writes an
append-only reversible app.decision (pending rules are inert until confirmed).
"""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError, ToolPermissionError

# Finance never manages signals/rules; reps may only act on their own customers' signals.
RULE_ROLES = ("owner", "admin", "sales_rep")


class ProposeRuleChangeInput(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    signal_id: int | None = None


class ProposeRuleChangeOutput(BaseModel):
    """What the chat shows: the proposal + what happened (applied/pending)."""

    applied: bool
    requires_confirm: bool
    learned_rule_id: int
    description: str
    effect_estimate: dict[str, Any]
    interpretation_confidence: float
    register: str  # akcija (applied) | preporuka (pending confirm)
    decision_id: int | None = None


def _run(tool_input: ProposeRuleChangeInput, context: ToolContext) -> ProposeRuleChangeOutput:
    from valeri_api.selfconfig.proposer import (
        ProposalFailed,
        SignalNotFound,
        propose_from_dismissal,
        propose_from_text,
    )

    try:
        if tool_input.signal_id is not None:
            # Rep scope check on the signal's customer (fail closed).
            customer_id = context.session.execute(
                text("SELECT customer_id FROM app.signal WHERE id = :id"),
                {"id": tool_input.signal_id},
            ).scalar()
            if customer_id is not None:
                context.assert_customer_visible(customer_id)
            response = propose_from_dismissal(
                context.session,
                tool_input.signal_id,
                tool_input.reason,
                context.user,
                client=context.llm_client,
                source_message_id=context.message_id,
            )
        else:
            # Free-text proposals can affect many customers → owner/admin only.
            if context.user.role == "sales_rep":
                raise ToolPermissionError(
                    "Komercijalisti mogu predlagati pravila samo za konkretan signal "
                    "svog kupca — opšta pravila predlaže vlasnik"
                )
            response = propose_from_text(
                context.session,
                tool_input.reason,
                context.user,
                client=context.llm_client,
                source_message_id=context.message_id,
            )
    except SignalNotFound as error:
        raise ToolError(str(error)) from error
    except ProposalFailed as error:
        raise ToolError(str(error)) from error

    return ProposeRuleChangeOutput(
        applied=response.applied,
        requires_confirm=response.requires_confirm,
        learned_rule_id=response.learned_rule.id,
        description=response.learned_rule.description,
        effect_estimate=response.effect_estimate.model_dump(),
        interpretation_confidence=response.proposal.interpretation_confidence,
        register=response.register,
        decision_id=response.decision_id,
    )


PROPOSE_RULE_CHANGE = ToolDefinition(
    name="propose_rule_change",
    description=(
        "Pretvara povratnu informaciju ('ne prijavljuj...') u strukturirano, reverzibilno "
        "pravilo. Parametri: reason, signal_id?"
    ),
    input_schema=ProposeRuleChangeInput,
    output_schema=ProposeRuleChangeOutput,
    allowed_roles=RULE_ROLES,
    run=_run,
    mutates=True,
)
