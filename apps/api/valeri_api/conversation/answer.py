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
    "get_client_knowledge": "analiza",
    "create_task_draft": "akcija",
    "propose_rule_change": "preporuka",
    "start_investigation": "analiza",
    "describe_capabilities": "analiza",
}

REFUSAL_TEXT = (
    "Nemate pristup ovim podacima. Komercijalisti mogu vidjeti promet i signale "
    "samo za svoje kupce — pitajte za kupca iz vašeg portfelja."
)


def _friendly_error(tool_result: ToolResult) -> str:
    """A clean Bosnian message for a failed tool — never the raw error or internal ids."""
    err = (tool_result.error or "").lower()
    if "metrike" in err and ("nema" in err or "izračunate" in err or "izracunate" in err):
        return (
            "Za ovog kupca trenutno nemam izračunate metrike (promet, narudžbe). "
            "Mogu provjeriti da li uopšte ima zabilježenih narudžbi "
            "ili pokušajte ponovo malo kasnije."
        )
    if "requires parameters" in err or "from_date" in err or "to_date" in err or "period" in err:
        return (
            "Za ovu metriku mi treba vremenski period. Navedite period — npr. "
            "„zadnjih 60 dana“ ili „od 1.1. do 1.3.“."
        )
    if "nepoznata metrika" in err or "unknown" in err:
        return (
            "Ta metrika mi nije poznata. Mogu, na primjer: ukupan promet, promet po mjesecima, "
            "promet kupca, zadnju narudžbu i prosječni razmak narudžbi."
        )
    return (
        "Trenutno ne mogu dohvatiti te podatke. Pokušajte preciznije — navedite tačan naziv "
        "kupca i, ako treba, vremenski period."
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
        return _friendly_error(tool_result), "analiza", "template"

    # Investigations (M13) carry their own fixed confirmation message; rule proposals
    # (M10) carry an already-LLM-written description — neither needs re-narration
    # (CLAUDE.md cost conventions).
    if tool_result.tool == "start_investigation":
        return (
            _template_answer(tool_result.tool, tool_result.output),
            _TOOL_REGISTERS.get(tool_result.tool, "analiza"),
            "template",
        )
    if tool_result.tool == "propose_rule_change":
        return (
            _template_answer(tool_result.tool, tool_result.output),
            tool_result.output.get("register", "preporuka"),
            "template",
        )
    # Capability self-description is a fixed list (no numbers) — render deterministically.
    if tool_result.tool == "describe_capabilities":
        return _template_answer(tool_result.tool, tool_result.output), "analiza", "template"

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
            role="simple_qa",  # M12: Tier-1 by role
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
        if not rows:
            return f"Nema podataka za metriku '{output['metric']}' u traženom periodu."
        lines = [_format_metric_row(row) for row in rows[:12]]
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

    if tool == "get_client_knowledge":
        return _knowledge_answer(output)

    if tool == "create_task_draft":
        return (
            f"Zadatak '{output['title']}' je kreiran (status: {output['status']}) i dodijeljen "
            f"komercijalisti kupca. Zadatak je vidljiv u listi zadataka i može se odbaciti."
        )

    if tool == "propose_rule_change":
        effect = output.get("effect_estimate", {})
        radius = (
            f" Sakrilo bi {effect.get('total_signals')} signala u zadnjih "
            f"{effect.get('window_days')} dana."
            if effect.get("total_signals") is not None
            else ""
        )
        if output.get("applied"):
            return (
                f"Pravilo je primijenjeno (reverzibilno): {output['description']}{radius} "
                f"Možete ga poništiti u bilo kojem trenutku."
            )
        return (
            f"Predloženo pravilo: {output['description']}{radius} "
            f"Potrebna je vaša potvrda da se primijeni."
        )

    if tool == "start_investigation":
        return output.get("message", "Istraga je pokrenuta i obrađuje se u pozadini.")

    if tool == "describe_capabilities":
        caps = output.get("capabilities", [])
        metrics = [c for c in caps if c["kind"] == "metric"]
        tools = [c for c in caps if c["kind"] == "tool"]
        lines = ["Evo šta mogu odgovoriti i uraditi:"]
        if metrics:
            lines.append("Metrike (brojke iz baze):")
            lines += [f"- {c['description']}" for c in metrics]
        if tools:
            lines.append("Akcije i pretrage:")
            lines += [f"- {c['description']}" for c in tools]
        return "\n".join(lines)

    return f"Podaci iz baze: {output}"


def _format_metric_row(row: dict[str, Any]) -> str:
    """Readable Bosnian line for one series-metric row — verbatim SQL values only."""
    label = (
        row.get("name")
        or row.get("customer_name")
        or row.get("category")
        or (str(row["month"]) if row.get("month") is not None else None)
    )
    amount = row.get("revenue", row.get("value"))
    if label is not None and amount is not None:
        qty = f", količina {row['qty']}" if row.get("qty") is not None else ""
        return f"- {label}: {amount} KM{qty}"
    return f"- {row}"


def _knowledge_answer(output: dict[str, Any]) -> str:
    """Deterministic Bosnian rendering of the confirmed KB about one customer."""
    name = output.get("customer_name") or "kupac"
    facts = output.get("facts", [])
    events = output.get("events", [])
    relationships = output.get("relationships", [])

    if not (output.get("profile_summary") or facts or events or relationships):
        return f"Još nema zabilježenog znanja o kupcu {name}."

    lines = [f"Šta VALERI zna o kupcu {name}:"]
    if output.get("profile_summary"):
        lines.append(output["profile_summary"])
    for fact in facts[:5]:
        lines.append(
            f"- {fact['fact_type']}/{fact['fact_key']}: {fact['value']} "
            f"(pouzdanost: {fact['conf_band']})"
        )
    for event in events[:5]:
        stated = f" — {event['value']} KM" if event.get("value") is not None else ""
        lines.append(f"- {event['kind']}: {event['summary']}{stated}")
    for rel in relationships[:5]:
        lines.append(f"- veza ({rel['rel_type']}) s kupcem {rel.get('other_name') or 'nepoznat'}")
    return "\n".join(lines)
