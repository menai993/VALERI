"""Synchronous bounded chat agent (CSA Phase 2): act → collect → synthesize.

For multi-step questions (comparisons, multi-metric, data-grounded "why") the
router tags intent='analysis' and this loop runs a few READ-ONLY tool calls and
synthesizes ONE Bosnian answer. It reuses the M13 agent's discipline — PII
masking, the safe-tool dispatcher, the number contract — WITHOUT the async graph,
Postgres checkpointing, or HITL gate (those stay for the deep 'Istraži' agent).

Numbers come only from tool/SQL results: the act step merely PICKS tools;
synthesis narrates the collected results under the number contract.
"""

import datetime
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.conversation.answer import _template_answer
from valeri_api.conversation.schemas import ChatAgentAnswer
from valeri_api.investigation.prompts import ACT_SYSTEM_PROMPT
from valeri_api.investigation.schemas import ToolChoice
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_customer_fields, rehydrate
from valeri_api.llm.prompts import CHAT_AGENT_SYNTH_SYSTEM_PROMPT
from valeri_api.llm.router.roles import ROLE_SIMPLE_QA
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.rules.engine import load_rule_config
from valeri_api.semantic.registry import load_registry
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import TOOLS, dispatch

logger = logging.getLogger("valeri.conversation.agent")

# The chat agent dispatches ONLY read-only, SQL-backed tools — no mutations, no
# rule changes, no async investigation hand-off (those have their own gated paths).
_READ_ONLY_TOOLS = frozenset(
    {
        "query_metric",
        "compare_periods",
        "list_signals",
        "explain_signal",
        "get_customer_360",
        "get_client_knowledge",
    }
)
_RESULT_WINDOW = 6
_DEFAULT_CAPS = {"max_steps": 4, "max_seconds": 30}


def _conf_band(confidence: float) -> str:
    """0–1 confidence → Bosnian band (same fixed cutoffs as the KB)."""
    if confidence >= 0.75:
        return "visoka"
    if confidence >= 0.5:
        return "srednja"
    return "niska"


def _caps(session: Session) -> dict[str, int]:
    """Loop caps from app.rule_config (rule='chat_agent'); code defaults if unseeded."""
    try:
        config = load_rule_config(session, "chat_agent")
    except LookupError:
        return dict(_DEFAULT_CAPS)
    return {
        "max_steps": int(config.get("max_steps", _DEFAULT_CAPS["max_steps"])),
        "max_seconds": int(config.get("max_seconds", _DEFAULT_CAPS["max_seconds"])),
    }


def _resolve_refs(params: dict[str, Any], context: MaskingContext) -> dict[str, Any]:
    """Map a pseudonym customer_ref the model produced back to a real id (server-side)."""
    resolved = dict(params)
    ref = resolved.pop("customer_ref", None)
    if ref:
        customer_id = context.customer_id_for(str(ref))
        if customer_id is not None:
            resolved["customer_id"] = customer_id
    return resolved


def run_chat_agent(
    session: Session,
    user: AppUser,
    masked_question: str,
    context: MaskingContext,
    *,
    message_id: int | None = None,
    prior_context: dict[str, Any] | None = None,
    client: LLMClient | None = None,
) -> tuple[str, str, list[dict[str, Any]], str]:
    """Run the bounded act→synthesize loop. Returns (text, register, tool_calls, source)."""
    caps = _caps(session)
    started = time.monotonic()
    registry = load_registry()
    results: list[dict[str, Any]] = []  # masked tool results (feed the prompts)
    tool_calls: list[dict[str, Any]] = []  # the record the conversation layer logs/streams

    step = 0
    while step < caps["max_steps"] and (time.monotonic() - started) < caps["max_seconds"]:
        step += 1
        payload = {
            "danas": str(datetime.date.today()),  # relative periods resolve against today
            "pitanje": masked_question,
            "prethodni_kontekst": prior_context or {},
            "dosadasnji_rezultati": results[-_RESULT_WINDOW:],
        }
        try:
            choice, _, _ = narrate_structured(
                session,
                payload,
                ToolChoice,
                system_prompt=ACT_SYSTEM_PROMPT,
                instruction=(
                    "Odaberi sljedeći alat koji prikuplja podatke potrebne za odgovor, "
                    'ili postavi "done": true ako već imaš dovoljno.'
                ),
                client=client,
                text_field=None,  # a tool choice renders no user-facing numbers
                role=ROLE_SIMPLE_QA,
            )
        except NarrationFailed:
            break

        if choice.done or not choice.tool:
            break

        # Read-only only: a mutation / out-of-scope tool is recorded and skipped.
        tool_def = TOOLS.get(choice.tool)
        if choice.tool not in _READ_ONLY_TOOLS or (tool_def is not None and tool_def.mutates):
            tool_calls.append(
                {"tool": choice.tool, "ok": False, "error_code": "not_allowed_in_analysis"}
            )
            continue

        params = _resolve_refs(choice.params, context)
        # Honesty gate: never dispatch query_metric with an unregistered metric.
        if choice.tool == "query_metric" and params.get("metric") not in registry:
            tool_calls.append({"tool": choice.tool, "ok": False, "error_code": "unknown_metric"})
            continue

        tool_context = ToolContext(
            session=session, user=user, message_id=message_id, llm_client=client
        )
        result = dispatch(tool_context, choice.tool, params)
        masked_output = mask_customer_fields(result.output, context) if result.ok else None
        results.append(
            {
                "tool": choice.tool,
                "params": choice.params,
                "ok": result.ok,
                "output": masked_output,
                "error": result.error,
            }
        )
        tool_calls.append(
            {
                "tool": choice.tool,
                "params": params,
                "ok": result.ok,
                "error_code": result.error_code,
            }
        )

    ok_results = [r for r in results if r["ok"]]
    if not ok_results:
        # Nothing usable — honest, number-free reply (never fabricate).
        return (
            "Nisam uspio prikupiti podatke potrebne za ovo pitanje. Pokušajte preciznije — "
            "navedite metriku, kupca i/ili period.",
            "analiza",
            tool_calls,
            "template",
        )

    synth_payload = {"pitanje": masked_question, "rezultati": ok_results}
    try:
        answer, _, _ = narrate_structured(
            session,
            synth_payload,
            ChatAgentAnswer,
            system_prompt=CHAT_AGENT_SYNTH_SYSTEM_PROMPT,
            instruction=(
                "Sintetiziraj odgovor na pitanje na osnovu prikupljenih rezultata alata. "
                "Svi brojevi su već izračunati — koristi ih doslovno."
            ),
            client=client,
            role=ROLE_SIMPLE_QA,
        )
        # Principle 3: a synthesized analysis is a conclusion — surface its confidence band.
        text = f"{answer.text}\n\nPouzdanost: {_conf_band(answer.confidence)}."
        return rehydrate(text, context), answer.register, tool_calls, "llm"
    except NarrationFailed as failure:
        logger.warning("chat-agent synthesis failed (%s); using template", failure.reason)
        parts = [_template_answer(r["tool"], r["output"]) for r in ok_results]
        return rehydrate("\n\n".join(parts), context), "analiza", tool_calls, "template"
