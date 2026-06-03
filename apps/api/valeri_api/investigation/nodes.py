"""The agent's nodes: plan → act ⇄ critic → [execute_action] → synthesize (M13).

Every node opens its own DB session (the agent runs in the worker, not in a
request), records an append-only investigation_step, commits its own work (so the
trace survives crashes), and returns ONLY JSON-serializable state updates — the
LangGraph checkpointer persists them so a restarted process resumes.

The discipline is inherited, never reimplemented:
- LLM calls → narrate_structured (masking, number contract, ai_log, M12 routing);
- data access → dispatch() (RBAC, validation, tool_call_log);
- the act node can NEVER execute a mutation — it can only record a proposal,
  and the graph interrupts before the node that would execute it.
"""

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.auth.models import AppUser
from valeri_api.investigation.budget import load_budget, over_budget
from valeri_api.investigation.prompts import (
    ACT_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    SYNTHESIZE_SYSTEM_PROMPT,
)
from valeri_api.investigation.schemas import (
    CriticVerdict,
    InvestigationState,
    PlanOutput,
    SynthesisOutput,
    ToolChoice,
)
from valeri_api.investigation.steps import record_step
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import (
    MaskingContext,
    collect_allowed_numbers,
    mask_customer_fields,
    rehydrate,
)
from valeri_api.llm.router.roles import ROLE_INVESTIGATION, ROLE_INVESTIGATION_SYNTHESIS
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import TOOLS, dispatch

logger = logging.getLogger("valeri.investigation.nodes")

# The act node may dispatch ONLY these (read-only, SQL-backed) tools.
READ_ONLY_TOOLS = (
    "query_metric",
    "compare_periods",
    "list_signals",
    "explain_signal",
    "get_customer_360",
)
# Mutations the model may only PROPOSE — executed solely by execute_action after HITL approval.
PROPOSABLE_ACTIONS = ("create_task_draft",)

# How many recent tool results the act/critic prompts carry (cost lever, not a threshold).
PROMPT_RESULT_WINDOW = 6


SessionFactory = Callable[[], Session]


def _masking_context(state: InvestigationState) -> MaskingContext:
    """Rebuild the masking context from checkpointed state (survives restarts)."""
    return MaskingContext(
        pseudonyms=dict(state.get("pseudonyms", {})),
        customer_ids=dict(state.get("pseudonym_ids", {})),
    )


def _masking_updates(context: MaskingContext) -> dict[str, Any]:
    return {
        "pseudonyms": dict(context.pseudonyms),
        "pseudonym_ids": dict(context.customer_ids),
    }


def _resolve_refs(params: dict[str, Any], context: MaskingContext) -> dict[str, Any]:
    """Map pseudonym customer refs back to real ids — server-side, never the model."""
    resolved = dict(params)
    customer_ref = resolved.pop("customer_ref", None)
    if customer_ref:
        customer_id = context.customer_id_for(str(customer_ref))
        if customer_id is not None:
            resolved["customer_id"] = customer_id
    return resolved


def _tokens_since(session: Session, before_id: int) -> int:
    """Tokens spent by the LLM calls this node just made (from the audit trail)."""
    return session.execute(
        sql_text("SELECT COALESCE(SUM(tokens), 0) FROM audit.ai_log WHERE id > :id"),
        {"id": before_id},
    ).scalar()


def _max_ai_log_id(session: Session) -> int:
    return session.execute(sql_text("SELECT COALESCE(MAX(id), 0) FROM audit.ai_log")).scalar()


def build_nodes(
    session_factory: SessionFactory, client: LLMClient | None
) -> dict[str, Callable[[InvestigationState], dict[str, Any]]]:
    """The node callables, closed over the session factory + (optional) injected client."""

    # ── plan ──────────────────────────────────────────────────────────────────
    def plan_node(state: InvestigationState) -> dict[str, Any]:
        with session_factory() as session:
            before = _max_ai_log_id(session)
            payload = {"pitanje": state["question_masked"]}
            try:
                plan, _, _ = narrate_structured(
                    session,
                    payload,
                    PlanOutput,
                    system_prompt=PLAN_SYSTEM_PROMPT,
                    instruction="Rastavi pitanje istrage na konkretna potpitanja.",
                    client=client,
                    text_field=None,  # internal decomposition — no user-facing numbers
                    role=ROLE_INVESTIGATION,
                )
                sub_questions = plan.sub_questions
                output: dict[str, Any] = plan.model_dump()
            except NarrationFailed as failure:
                # Degrade gracefully: investigate the raw question as a single step.
                sub_questions = [state["question_masked"]]
                output = {"fallback": True, "reason": failure.reason}

            tokens = _tokens_since(session, before)
            record_step(
                session,
                state["investigation_id"],
                node="plan",
                input_payload=payload,
                output_payload=output,
            )
            session.commit()

        return {
            "plan": sub_questions,
            "tokens_used": state.get("tokens_used", 0) + int(tokens),
        }

    # ── act ───────────────────────────────────────────────────────────────────
    def act_node(state: InvestigationState) -> dict[str, Any]:
        with session_factory() as session:
            user = session.get(AppUser, state["user_id"])
            context = _masking_context(state)
            before = _max_ai_log_id(session)

            payload = {
                "pitanje": state["question_masked"],
                "potpitanja": state.get("plan", []),
                "dosadasnji_rezultati": state.get("tool_results", [])[-PROMPT_RESULT_WINDOW:],
                "vec_predlozene_akcije": state.get("proposed_actions", []),
            }

            updates: dict[str, Any] = {"act_count": state.get("act_count", 0) + 1}

            try:
                choice, _, _ = narrate_structured(
                    session,
                    payload,
                    ToolChoice,
                    system_prompt=ACT_SYSTEM_PROMPT,
                    instruction="Odaberi sljedeći alat (ili označi da imaš dovoljno podataka).",
                    client=client,
                    text_field=None,  # a tool choice renders no user-facing numbers
                    role=ROLE_INVESTIGATION,
                )
            except NarrationFailed as failure:
                # The model can't even pick a tool — record it and let the critic decide.
                record_step(
                    session,
                    state["investigation_id"],
                    node="act",
                    output_payload={"error": "tool_choice_failed", "reason": failure.reason},
                )
                session.commit()
                updates["tokens_used"] = state.get("tokens_used", 0) + int(
                    _tokens_since(session, before)
                )
                return updates

            tokens = _tokens_since(session, before)
            updates["tokens_used"] = state.get("tokens_used", 0) + int(tokens)

            # ── "I have enough" — no tool this step ──────────────────────────
            if choice.done or choice.tool is None:
                record_step(
                    session,
                    state["investigation_id"],
                    node="act",
                    input_payload=payload,
                    output_payload={"done": True, "reasoning": choice.reasoning},
                )
                session.commit()
                return updates

            tool_definition = TOOLS.get(choice.tool)

            # ── proposed mutation → NEVER dispatched here (HITL gate) ────────
            if (
                choice.is_action_proposal
                or choice.tool in PROPOSABLE_ACTIONS
                or (tool_definition is not None and tool_definition.mutates)
            ):
                proposal = {
                    "tool": choice.tool,
                    "params": choice.params,
                    "reasoning": choice.reasoning,
                }
                record_step(
                    session,
                    state["investigation_id"],
                    node="act",
                    tool=choice.tool,
                    input_payload=choice.params,
                    output_payload={"proposed_action": proposal},
                )
                session.commit()
                updates["proposed_actions"] = state.get("proposed_actions", []) + [proposal]
                return updates

            # ── unknown / not-allowed tool → recorded refusal, no dispatch ───
            if choice.tool not in READ_ONLY_TOOLS:
                entry = {
                    "tool": choice.tool,
                    "params": choice.params,
                    "ok": False,
                    "error": "alat nije dozvoljen istražnom agentu",
                }
                record_step(
                    session,
                    state["investigation_id"],
                    node="act",
                    tool=choice.tool,
                    input_payload=choice.params,
                    output_payload=entry,
                )
                session.commit()
                updates["tool_results"] = state.get("tool_results", []) + [entry]
                return updates

            # ── read-only dispatch (RBAC + validation + tool_call_log inside) ─
            resolved_params = _resolve_refs(choice.params, context)
            tool_context = ToolContext(session=session, user=user, llm_client=client)
            result = dispatch(tool_context, choice.tool, resolved_params)

            # Mask the output BEFORE it enters state (state feeds future prompts).
            masked_output = mask_customer_fields(result.output, context) if result.ok else None
            entry = {
                "tool": choice.tool,
                "params": choice.params,
                "ok": result.ok,
                "output": masked_output,
                "error": result.error,
            }
            record_step(
                session,
                state["investigation_id"],
                node="act",
                tool=choice.tool,
                input_payload=choice.params,
                output_payload=jsonable(entry),
            )
            session.commit()

            updates["tool_results"] = state.get("tool_results", []) + [jsonable(entry)]
            updates.update(_masking_updates(context))
            return updates

    # ── critic ────────────────────────────────────────────────────────────────
    def critic_node(state: InvestigationState) -> dict[str, Any]:
        with session_factory() as session:
            # Deterministic budget check FIRST — caps are never up to the model.
            budget = load_budget(session)
            cap = over_budget(dict(state), budget)
            if cap is not None:
                record_step(
                    session,
                    state["investigation_id"],
                    node="critic",
                    output_payload={"verdict": "dovoljno", "budget_exhausted": cap},
                )
                session.commit()
                return {"critic_verdict": "dovoljno", "budget_exhausted": cap}

            before = _max_ai_log_id(session)
            payload = {
                "pitanje": state["question_masked"],
                "potpitanja": state.get("plan", []),
                "rezultati": state.get("tool_results", [])[-PROMPT_RESULT_WINDOW:],
                "broj_koraka": state.get("act_count", 0),
            }
            try:
                verdict, _, _ = narrate_structured(
                    session,
                    payload,
                    CriticVerdict,
                    system_prompt=CRITIC_SYSTEM_PROMPT,
                    instruction="Provjeri da li su nalazi dovoljni i utemeljeni u podacima.",
                    client=client,
                    text_field=None,
                    role=ROLE_INVESTIGATION,
                )
                verdict_value = verdict.verdict
                output: dict[str, Any] = verdict.model_dump()
            except NarrationFailed as failure:
                # A broken critic must not loop the agent forever — synthesize what we have.
                verdict_value = "dovoljno"
                output = {"verdict": "dovoljno", "fallback": True, "reason": failure.reason}

            tokens = _tokens_since(session, before)
            record_step(
                session,
                state["investigation_id"],
                node="critic",
                input_payload=payload,
                output_payload=output,
            )
            session.commit()

        return {
            "critic_verdict": verdict_value,
            "tokens_used": state.get("tokens_used", 0) + int(tokens),
        }

    # ── execute_action (the graph INTERRUPTS BEFORE this node — HITL) ─────────
    def execute_action_node(state: InvestigationState) -> dict[str, Any]:
        with session_factory() as session:
            user = session.get(AppUser, state["user_id"])
            context = _masking_context(state)
            decision = state.get("hitl_decision")
            executed: list[dict[str, Any]] = []

            if decision == "approve":
                for proposal in state.get("proposed_actions", []):
                    resolved_params = _resolve_refs(proposal.get("params", {}), context)
                    tool_context = ToolContext(session=session, user=user, llm_client=client)
                    result = dispatch(tool_context, proposal["tool"], resolved_params)
                    entry = {
                        "tool": proposal["tool"],
                        "ok": result.ok,
                        "output": (
                            mask_customer_fields(result.output, context) if result.ok else None
                        ),
                        "error": result.error,
                    }
                    executed.append(jsonable(entry))
                    record_step(
                        session,
                        state["investigation_id"],
                        node="execute_action",
                        tool=proposal["tool"],
                        input_payload=proposal,
                        output_payload=jsonable(entry),
                    )
            else:
                # Reject (or missing decision = reject): nothing executes, visibly recorded.
                record_step(
                    session,
                    state["investigation_id"],
                    node="execute_action",
                    output_payload={
                        "decision": decision or "reject",
                        "skipped_actions": len(state.get("proposed_actions", [])),
                    },
                )
            session.commit()

        updates: dict[str, Any] = {"tool_results": state.get("tool_results", []) + executed}
        updates.update(_masking_updates(context))
        return updates

    # ── synthesize ────────────────────────────────────────────────────────────
    def synthesize_node(state: InvestigationState) -> dict[str, Any]:
        with session_factory() as session:
            context = _masking_context(state)
            before = _max_ai_log_id(session)

            payload = {
                "pitanje": state["question_masked"],
                "potpitanja": state.get("plan", []),
                "rezultati_alata": state.get("tool_results", []),
                "predlozene_akcije": state.get("proposed_actions", []),
                "odluka_o_akcijama": state.get("hitl_decision"),
                "budzet_prekoracen": state.get("budget_exhausted"),
            }
            allowed_numbers = collect_allowed_numbers(jsonable(payload))

            synthesis: SynthesisOutput | None = None
            source = "llm"
            try:
                synthesis, _, _ = narrate_structured(
                    session,
                    payload,
                    SynthesisOutput,
                    system_prompt=SYNTHESIZE_SYSTEM_PROMPT,
                    instruction=(
                        "Napiši završni izvještaj istrage isključivo iz priloženih rezultata."
                    ),
                    client=client,
                    text_field="narrative",  # the number contract on the main narrative
                    role=ROLE_INVESTIGATION_SYNTHESIS,
                )
                # Belt and suspenders: findings + next_step must also pass the contract.
                from valeri_api.llm.validators import check_number_contract

                extra_text = " ".join(
                    [finding.text for finding in synthesis.findings] + [synthesis.next_step]
                )
                violations = check_number_contract(extra_text, allowed_numbers)
                if violations:
                    logger.warning("synthesis findings/next_step invented numbers: %s", violations)
                    synthesis = None
            except NarrationFailed as failure:
                logger.warning("synthesis narration failed (%s); using template", failure.reason)
                synthesis = None

            tokens = _tokens_since(session, before)

            if synthesis is None:
                source = "template"
                report = _template_report(state, context)
            else:
                report = {
                    "narrative": rehydrate(synthesis.narrative, context),
                    "findings": [
                        {
                            "text": rehydrate(finding.text, context),
                            "confidence": finding.confidence,
                            "register": "analiza",
                        }
                        for finding in synthesis.findings
                    ],
                    "confidence": synthesis.confidence,
                    "next_step": rehydrate(synthesis.next_step, context),
                    "next_step_register": "preporuka",
                    "register": "analiza",
                    "narrative_source": "llm",
                }

            if state.get("budget_exhausted"):
                report["budget_exhausted"] = state["budget_exhausted"]
            report["trace_ref"] = f"investigation:{state['investigation_id']}:steps"

            record_step(
                session,
                state["investigation_id"],
                node="synthesize",
                output_payload={
                    "confidence": report["confidence"],
                    "narrative_source": source if synthesis is None else "llm",
                    "findings_count": len(report["findings"]),
                },
            )
            session.commit()

        return {
            "report": jsonable(report),
            "tokens_used": state.get("tokens_used", 0) + int(tokens),
        }

    return {
        "plan": plan_node,
        "act": act_node,
        "critic": critic_node,
        "execute_action": execute_action_node,
        "synthesize": synthesize_node,
    }


def _template_report(state: InvestigationState, context: MaskingContext) -> dict[str, Any]:
    """Deterministic fallback report — pure formatting of tool results (no LLM)."""
    successful = [r for r in state.get("tool_results", []) if r.get("ok")]
    findings = [
        {
            "text": rehydrate(
                f"Alat {result['tool']} je vratio podatke iz baze (vidi trag istrage).", context
            ),
            "confidence": 0.3,
            "register": "analiza",
        }
        for result in successful
    ] or [
        {
            "text": "Istraga nije prikupila dovoljno podataka za pouzdane nalaze.",
            "confidence": 0.1,
            "register": "analiza",
        }
    ]
    return {
        "narrative": (
            "Automatska sinteza nije uspjela — ovo je deterministički sažetak. "
            f"Istraga je izvršila {len(state.get('tool_results', []))} dohvata podataka; "
            "svi rezultati su u tragu istrage ispod."
        ),
        "findings": findings,
        "confidence": 0.3,
        "next_step": "Pregledajte trag istrage i po potrebi pokrenite novu, užu istragu.",
        "next_step_register": "preporuka",
        "register": "analiza",
        "narrative_source": "template",
    }


def route_after_critic(state: InvestigationState) -> str:
    """Where the graph goes after the critic (deterministic, no model involvement).

    Note: proposed actions ALWAYS route through execute_action — the graph interrupts
    before it, and the node itself reads the (post-resume) hitl_decision to decide
    whether to dispatch or skip. The critic route never re-runs after execute_action
    (its outgoing edge is static), so no re-entry guard is needed here.
    """
    if state.get("critic_verdict") == "treba_jos" and not state.get("budget_exhausted"):
        return "act"
    if state.get("proposed_actions"):
        return "execute_action"
    return "synthesize"
