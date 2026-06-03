"""Answer narration (M9): tool output → Bosnian reply + register.

Reuses the M6 discipline end-to-end: the tool output is masked (pseudonyms),
narrated by Tier-1, the number contract is checked, and a deterministic Bosnian
template is the fallback for every tool. The stored reply is rehydrated — chat
is for humans.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.conversation.schemas import ChatAnswer
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_customer_fields, rehydrate
from valeri_api.llm.prompts import CHAT_ANSWER_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.tools.catalog import ToolResult

logger = logging.getLogger("valeri.conversation.answer")

# Register semantics per tool for the deterministic fallbacks.
_TOOL_REGISTERS: dict[str, str] = {
    "query_metric": "analiza",
    "compare_periods": "analiza",
    "list_signals": "analiza",
    "explain_signal": "analiza",
    "get_customer_360": "analiza",
    "create_task_draft": "akcija",
    "propose_rule_change": "analiza",
    "start_investigation": "analiza",
}

HELP_TEXT = (
    "Mogu odgovoriti na pitanja o prometu, kupcima, artiklima i AI signalima, "
    'ili kreirati zadatak za kupca. Na primjer: "Koliki je promet u zadnjih 30 dana?", '
    '"Pokaži mi kupce u padu", "Kreiraj zadatak za <ime kupca>".'
)

REFUSAL_TEXT = (
    "Nemate pristup ovim podacima. Komercijalisti mogu vidjeti promet i signale "
    "samo za svoje kupce — pitajte za kupca iz vašeg portfelja."
)


def narrate_answer(
    session: Session,
    tool_result: ToolResult,
    context: MaskingContext,
    client: LLMClient | None = None,
) -> tuple[str, str, str]:
    """Narrate one tool result. Returns (rehydrated_text, register, source).

    source is "llm" or "template" — the reply text is ALWAYS validated or
    deterministic, never raw model output.
    """
    # Permission denials get a fixed refusal — no LLM needed, no data shown.
    if not tool_result.ok and tool_result.error_code == "forbidden":
        return REFUSAL_TEXT, "analiza", "template"
    if not tool_result.ok:
        return (
            f"Nije moguće dohvatiti podatke: {tool_result.error}",
            "analiza",
            "template",
        )

    # Stub tools (M10/M13) carry their own fixed Bosnian message — narrating it
    # with an LLM would only add cost (CLAUDE.md cost conventions).
    if tool_result.tool in ("propose_rule_change", "start_investigation"):
        return (
            _template_answer(tool_result.tool, tool_result.output),
            _TOOL_REGISTERS.get(tool_result.tool, "analiza"),
            "template",
        )

    # Mask the tool output (customer names → pseudonyms) before any prompt, and
    # tell the narrator which (masked) customers the question referenced so the
    # reply can mention them — by pseudonym only; rehydration restores names.
    masked_output = mask_customer_fields(tool_result.output, context)
    masked_payload = {
        "alat": tool_result.tool,
        "podaci": masked_output,
        "kupci_u_pitanju": sorted(context.pseudonyms.keys()),
    }

    try:
        answer, _, _ = narrate_structured(
            session,
            masked_payload,
            ChatAnswer,
            system_prompt=CHAT_ANSWER_SYSTEM_PROMPT,
            instruction=(
                "Odgovori korisniku na osnovu podataka koje je alat dohvatio iz baze. "
                "Svi brojevi su već izračunati — koristi ih doslovno."
            ),
            client=client,
        )
        return rehydrate(answer.text, context), answer.register, "llm"
    except NarrationFailed as failure:
        logger.warning("answer narration failed (%s); falling back to template", failure.reason)
        template = _template_answer(tool_result.tool, tool_result.output)
        return (
            rehydrate(template, context),
            _TOOL_REGISTERS.get(tool_result.tool, "analiza"),
            ("template"),
        )


# ── deterministic Bosnian fallbacks (pure formatting of tool/SQL values) ──────


def _template_answer(tool: str, output: dict[str, Any]) -> str:
    if tool == "query_metric":
        if output.get("value") is not None:
            return f"Vrijednost metrike '{output['metric']}': {output['value']}."
        rows = output.get("rows", [])
        lines = [f"- {row}" for row in rows[:12]]
        return f"Rezultat metrike '{output['metric']}':\n" + "\n".join(lines)

    if tool == "compare_periods":
        period_a, period_b = output["period_a"], output["period_b"]
        delta = output.get("delta_pct")
        delta_text = f" Promjena: {delta}%." if delta is not None else ""
        return (
            f"Period {period_a['from_date']} – {period_a['to_date']}: {period_a['value']} KM. "
            f"Period {period_b['from_date']} – {period_b['to_date']}: {period_b['value']} KM."
            f"{delta_text}"
        )

    if tool == "list_signals":
        items = output.get("items", [])
        if not items:
            return "Trenutno nema otvorenih AI signala."
        lines = [
            f"- {item['rule']}: {item.get('customer_name') or 'nepoznat kupac'} "
            f"(pouzdanost: {item['conf_band']})"
            for item in items[:10]
        ]
        return f"Otvoreni signali ({output['total_returned']}):\n" + "\n".join(lines)

    if tool == "explain_signal":
        evidence_lines = [f"  - {key}: {value}" for key, value in output["evidence"].items()]
        return (
            f"Signal {output['signal_id']} ({output['rule']}) za kupca "
            f"{output.get('customer_name') or 'nepoznat'}, pouzdanost {output['conf_band']}.\n"
            f"Dokaz iz baze:\n" + "\n".join(evidence_lines)
        )

    if tool == "get_customer_360":
        return (
            f"Kupac {output['customer_name']} ({output.get('segment') or '—'}): "
            f"promet 60 dana {output.get('turnover_60d')} KM, uobičajeno "
            f"{output.get('baseline_60d')} KM, zadnja narudžba {output.get('last_order_date')}, "
            f"prosječni razmak narudžbi {output.get('avg_order_interval_d')} dana."
        )

    if tool == "create_task_draft":
        return (
            f"Zadatak '{output['title']}' je kreiran (status: {output['status']}) i dodijeljen "
            f"komercijalisti kupca. Zadatak je vidljiv u listi zadataka i može se odbaciti."
        )

    if tool in ("propose_rule_change", "start_investigation"):
        return output.get("message", "Ova funkcionalnost stiže u kasnijem milestone-u.")

    return f"Podaci iz baze: {output}"
