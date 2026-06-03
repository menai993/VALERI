"""Weekly owner report builder (M7).

Every number in the report is a SQL aggregate from sql/weekly_aggregates.sql
(principle 1). The LLM only narrates finished values, through the M6 discipline
(masking → number contract → ai_log → retry), with a deterministic Bosnian
template as the fallback for every section. Each section carries its fixed
register (D5) and its SQL data (evidence, principle 2).

The report is stored as one immutable app.owner_report snapshot per
Monday–Sunday week; regenerating the same week returns the existing snapshot.
"""

import datetime
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valeri_api.approvals.workflow import generate_customer_drafts
from valeri_api.audit.serialization import jsonable
from valeri_api.config import get_settings
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, rehydrate
from valeri_api.llm.prompts import REPORT_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.reports.models import OwnerReport
from valeri_api.reports.schemas import (
    OwnerReportSummary,
    ReportSectionNarrative,
    SummaryBullet,
    SummaryMetric,
)

logger = logging.getLogger("valeri.reports.builder")

# ── Report layout constants ───────────────────────────────────────────────────
# How many rows each section lists. These are presentation choices, NOT
# detection thresholds — those live in app.rule_config (CLAUDE.md).
TOP_N = 5

FOOTER = "Brojke iz baze · SQL"

_SQL_FILE = Path(__file__).parent / "sql" / "weekly_aggregates.sql"

# Whitelists of row fields each section may forward to the LLM (principle 6:
# masking by construction — customer identity is replaced by a pseudonym, and
# anything not listed here never reaches a prompt).
_DECLINE_PROMPT_FIELDS = ("value", "baseline", "delta_pct", "confidence")
_LOST_ARTICLE_PROMPT_FIELDS = (
    "article_name",
    "article_code",
    "avg_interval_d",
    "gap_days",
    "last_seen",
    "confidence",
)
_SLEEPING_PROMPT_FIELDS = (
    "last_order_date",
    "gap_days",
    "avg_order_interval_d",
    "order_count",
    "confidence",
)
# Task titles contain customer names and assignee names are employees — neither
# is forwarded; only the rule, status, dates and confidence are.
_TASK_PROMPT_FIELDS = ("rule", "task_status", "due_date", "owner_cc", "confidence")


def week_bounds(reference: datetime.date) -> tuple[datetime.date, datetime.date]:
    """The Monday–Sunday week containing the reference date."""
    week_start = reference - datetime.timedelta(days=reference.weekday())
    return week_start, week_start + datetime.timedelta(days=6)


def _load_queries() -> dict[str, str]:
    """Split weekly_aggregates.sql into named queries on '-- name:' markers."""
    queries: dict[str, str] = {}
    content = _SQL_FILE.read_text(encoding="utf-8")
    for block in content.split("-- name: ")[1:]:
        name, _, sql = block.partition("\n")
        queries[name.strip()] = sql.strip()
    return queries


# ── the builder ───────────────────────────────────────────────────────────────


def build_weekly_report(
    session: Session,
    week_end: datetime.date,
    client: LLMClient | None = None,
) -> OwnerReport:
    """Build (or return) the stored weekly report for the week containing week_end.

    Idempotent per week: an existing snapshot is returned unchanged. Customer-
    facing message drafts (D3) are generated along the way as approval-gated
    rows; the report itself is an internal action and never requires approval.
    """
    week_start, week_end = week_bounds(week_end)

    existing = session.execute(
        select(OwnerReport).where(
            OwnerReport.week_start == week_start, OwnerReport.week_end == week_end
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    queries = _load_queries()
    params: dict[str, Any] = {"week_start": week_start, "week_end": week_end, "top_n": TOP_N}

    kpi = dict(session.execute(text(queries["kpi"]), params).mappings().one())
    declines = [dict(r) for r in session.execute(text(queries["top_declines"]), params).mappings()]
    lost = [dict(r) for r in session.execute(text(queries["lost_articles"]), params).mappings()]
    sleeping = [
        dict(r) for r in session.execute(text(queries["sleeping_customers"]), params).mappings()
    ]
    task_stats = dict(session.execute(text(queries["task_stats"]), params).mappings().one())
    top_tasks = [dict(r) for r in session.execute(text(queries["top_tasks"]), params).mappings()]

    # Customer-facing drafts (D3) — created first so section 7 can list them.
    generate_customer_drafts(session, week_start, week_end, client=client)
    pending_drafts = [
        dict(r) for r in session.execute(text(queries["pending_drafts"]), params).mappings()
    ]

    # C-CRM2 inputs: opportunity-source attribution + the revenue-vs-plan forecast.
    opp_sources = [
        dict(r) for r in session.execute(text(queries["opportunity_source"]), params).mappings()
    ]
    opp_stats = dict(session.execute(text(queries["opportunity_stats"]), params).mappings().one())

    narration_active = client is not None or get_settings().llm_narration_enabled

    sections = [
        _kpi_section(session, kpi, week_start, week_end, narration_active, client),
        _decline_section(session, declines, narration_active, client),
        _lost_article_section(session, lost, narration_active, client),
        _sleeping_section(session, sleeping, narration_active, client),
        _tasks_section(session, task_stats, top_tasks, narration_active, client),
        _suppressed_section(session, week_start, week_end),
        _opportunity_source_section(session, opp_sources, opp_stats, narration_active, client),
        _revenue_plan_section(session, week_end, narration_active, client),
        _drafts_section(pending_drafts),
    ]

    report = OwnerReport(
        week_start=week_start,
        week_end=week_end,
        payload=jsonable({"week_start": week_start, "week_end": week_end, "sections": sections}),
    )
    session.add(report)
    session.flush()
    logger.info("weekly owner report built for %s — %s (id=%d)", week_start, week_end, report.id)
    return report


def extract_summary(report: OwnerReport) -> OwnerReportSummary:
    """The dashboard summary block: a pure extraction from the stored payload.

    No recomputation and no LLM — values and narratives pass through exactly as
    stored (principle 1).
    """
    sections = {section["key"]: section for section in report.payload["sections"]}
    kpi = sections["kpi_pregled"]["data"]

    metrics = [
        SummaryMetric(label="Promet sedmice (KM)", value=kpi["week_revenue"], register="analiza"),
        SummaryMetric(label="Kupci u padu", value=kpi["n_declines"], register="analiza"),
        SummaryMetric(label="Izgubljeni artikli", value=kpi["n_lost_articles"], register="analiza"),
        SummaryMetric(label="Otvoreni zadaci", value=kpi["open_tasks"], register="preporuka"),
    ]
    bullets = [
        SummaryBullet(text=section["narrative"], register=section["register"])
        for section in report.payload["sections"]
        if not section["data"].get("placeholder")
    ]
    return OwnerReportSummary(
        week_start=report.week_start,
        week_end=report.week_end,
        metrics=metrics,
        bullets=bullets,
    )


# ── section builders ──────────────────────────────────────────────────────────


def _section(
    key: str, title: str, register: str, narrative: str, source: str, data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "register": register,
        "narrative": narrative,
        "narrative_source": source,
        "data": data,
    }


def _narrate_or_template(
    session: Session,
    masked_payload: dict[str, Any],
    context: MaskingContext,
    instruction: str,
    template: str,
    narration_active: bool,
    client: LLMClient | None,
) -> tuple[str, str]:
    """LLM narration through the M6 discipline, falling back to the template.

    The stored narrative is rehydrated (real names) — the report is for humans.
    """
    if narration_active:
        try:
            narrative, _, _ = narrate_structured(
                session,
                masked_payload,
                ReportSectionNarrative,
                system_prompt=REPORT_SYSTEM_PROMPT,
                instruction=instruction,
                client=client,
                role="report_narration",  # M12: Tier-1 by role
            )
            return rehydrate(narrative.text, context), "llm"
        except NarrationFailed as failure:
            logger.warning(
                "report section narration failed (%s); falling back to template", failure.reason
            )
    return template, "template"


def _mask_items(
    items: list[dict[str, Any]], fields: tuple[str, ...], context: MaskingContext
) -> list[dict[str, Any]]:
    """Build prompt-safe rows: whitelisted fields + pseudonym + segment only."""
    masked = []
    for item in items:
        row: dict[str, Any] = {f: item[f] for f in fields if item.get(f) is not None}
        if item.get("segment"):
            row["segment"] = item["segment"]
        if item.get("customer_id") is not None:
            row["kupac"] = context.register_customer(
                item["customer_id"], item.get("customer_name") or ""
            )
        masked.append(row)
    return masked


_EMPTY_NARRATIVE = "Nema novih nalaza u ovoj sekciji za ovu sedmicu."


def _kpi_section(
    session: Session,
    kpi: dict[str, Any],
    week_start: datetime.date,
    week_end: datetime.date,
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """① KPI pregled — week revenue vs prior week, signal/task counts (analiza)."""
    # KPI aggregates carry no customer identity at all — nothing to mask.
    masked_payload = {
        "sekcija": "KPI pregled sedmice",
        "period": {"od": week_start, "do": week_end},
        "podaci": kpi,
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        MaskingContext(),
        instruction="Napiši kratak KPI pregled sedmičnog izvještaja za vlasnika firme.",
        template=_template_kpi(kpi),
        narration_active=narration_active,
        client=client,
    )
    return _section("kpi_pregled", "KPI pregled", "analiza", narrative, source, kpi)


def _decline_section(
    session: Session,
    items: list[dict[str, Any]],
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """② Najveći padovi — top declines by lost value (analiza)."""
    data = {"items": items}
    if not items:
        return _section(
            "najveci_padovi", "Najveći padovi", "analiza", _EMPTY_NARRATIVE, "template", data
        )
    context = MaskingContext()
    masked_payload = {
        "sekcija": "Najveći padovi prometa kupaca",
        "stavke": _mask_items(items, _DECLINE_PROMPT_FIELDS, context),
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        context,
        instruction="Napiši narativ o najvećim padovima prometa kupaca ove sedmice.",
        template=_template_declines(items),
        narration_active=narration_active,
        client=client,
    )
    return _section("najveci_padovi", "Najveći padovi", "analiza", narrative, source, data)


def _lost_article_section(
    session: Session,
    items: list[dict[str, Any]],
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """③ Izgubljeni artikli — top lost articles (analiza)."""
    data = {"items": items}
    if not items:
        return _section(
            "izgubljeni_artikli",
            "Izgubljeni artikli",
            "analiza",
            _EMPTY_NARRATIVE,
            "template",
            data,
        )
    context = MaskingContext()
    masked_payload = {
        "sekcija": "Izgubljeni artikli kod kupaca",
        "stavke": _mask_items(items, _LOST_ARTICLE_PROMPT_FIELDS, context),
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        context,
        instruction="Napiši narativ o artiklima koje kupci više ne naručuju.",
        template=_template_lost_articles(items),
        narration_active=narration_active,
        client=client,
    )
    return _section("izgubljeni_artikli", "Izgubljeni artikli", "analiza", narrative, source, data)


def _sleeping_section(
    session: Session,
    items: list[dict[str, Any]],
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """④ Uspavani kupci — customers who stopped ordering (analiza)."""
    data = {"items": items}
    if not items:
        return _section(
            "uspavani_kupci", "Uspavani kupci", "analiza", _EMPTY_NARRATIVE, "template", data
        )
    context = MaskingContext()
    masked_payload = {
        "sekcija": "Uspavani kupci (prestali naručivati)",
        "stavke": _mask_items(items, _SLEEPING_PROMPT_FIELDS, context),
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        context,
        instruction="Napiši narativ o kupcima koji su prestali naručivati.",
        template=_template_sleeping(items),
        narration_active=narration_active,
        client=client,
    )
    return _section("uspavani_kupci", "Uspavani kupci", "analiza", narrative, source, data)


def _tasks_section(
    session: Session,
    stats: dict[str, Any],
    items: list[dict[str, Any]],
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """⑤ Zadaci sedmice — task stats + top tasks (preporuka)."""
    data = {"stats": stats, "items": items}
    if not items:
        return _section(
            "zadaci_sedmice", "Zadaci sedmice", "preporuka", _EMPTY_NARRATIVE, "template", data
        )
    context = MaskingContext()
    masked_payload = {
        "sekcija": "Zadaci sedmice za komercijaliste",
        "statistika": stats,
        "stavke": _mask_items(items, _TASK_PROMPT_FIELDS, context),
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        context,
        instruction="Napiši narativ o zadacima kreiranim ove sedmice i preporuči fokus.",
        template=_template_tasks(stats, items),
        narration_active=narration_active,
        client=client,
    )
    return _section("zadaci_sedmice", "Zadaci sedmice", "preporuka", narrative, source, data)


def _suppressed_section(
    session: Session, week_start: datetime.date, week_end: datetime.date
) -> dict[str, Any]:
    """⑥ Nedavno potisnuto — what learned rules hid this week + open Na provjeri flags.

    Template-only narrative: this is a counting summary of suppression activity —
    the SQL numbers ARE the message, so no LLM call is spent here (cost lever).
    """
    rows = [
        dict(row)
        for row in session.execute(
            text(
                "SELECT lr.id AS learned_rule_id, lr.description, lr.status, "
                "       s.rule, c.name AS customer_name, COUNT(h.id) AS hits "
                "FROM app.suppression_hit h "
                "JOIN app.learned_rule lr ON lr.id = h.learned_rule_id "
                "LEFT JOIN app.signal s ON s.id = h.signal_id "
                "LEFT JOIN core.customer c ON c.id = s.customer_id "
                "WHERE h.suppressed_at >= :week_start "
                "  AND h.suppressed_at < CAST(:week_end AS date) + 1 "
                "GROUP BY lr.id, lr.description, lr.status, s.rule, c.name "
                "ORDER BY COUNT(h.id) DESC"
            ),
            {"week_start": week_start, "week_end": week_end},
        ).mappings()
    ]

    # Rules with an open Na provjeri flag (raised by the auditor, not yet resolved).
    na_provjeri_count = session.execute(
        text(
            "SELECT COUNT(DISTINCT d.payload->>'learned_rule_id') FROM app.decision d "
            "WHERE d.kind = 'reactivation' AND (d.payload->>'review')::boolean "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM app.decision r "
            "  WHERE r.id > d.id AND r.kind IN ('approval', 'undo') "
            "  AND r.payload->>'learned_rule_id' = d.payload->>'learned_rule_id')"
        )
    ).scalar()

    total_hits = sum(row["hits"] for row in rows)
    data = {
        "items": jsonable(rows),
        "total_hits": total_hits,
        "na_provjeri_count": na_provjeri_count,
    }

    if not rows:
        narrative = "Nema potisnutih signala ove sedmice."
    else:
        narrative = (
            f"Ove sedmice VALERI je potisnuo {total_hits} signala po {len(rows)} "
            f"naučenih pravila — detalji su u kartici 'Šta je VALERI naučio'."
        )
    if na_provjeri_count:
        narrative += (
            f" Na provjeri: {na_provjeri_count} — potisnuti obrazac se značajno promijenio."
        )

    return _section(
        "nedavno_potisnuto", "Nedavno potisnuto", "analiza", narrative, "template", data
    )


# Opportunity-source rows carry no customer identity (source/counts/values only) —
# nothing to mask; the prompt receives finished SQL numbers.
_OPP_SOURCE_PROMPT_FIELDS = ("source", "count", "value", "weighted_value")


def _opportunity_source_section(
    session: Session,
    sources: list[dict[str, Any]],
    stats: dict[str, Any],
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """⑦ Prilike po izvoru — opportunity-source attribution + average value (C-CRM2)."""
    data = {"items": jsonable(sources), "stats": jsonable(stats)}
    if not sources:
        return _section(
            "prilike_po_izvoru",
            "Prilike po izvoru",
            "analiza",
            "Nema evidentiranih prilika za ovaj period.",
            "template",
            data,
        )
    masked_payload = {
        "sekcija": "Prilike po izvoru i prosječna vrijednost prilike",
        "izvori": [{f: row[f] for f in _OPP_SOURCE_PROMPT_FIELDS} for row in jsonable(sources)],
        "prosjecna_vrijednost": jsonable(stats)["avg_value"],
        "ukupno_prilika": jsonable(stats)["total_count"],
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        MaskingContext(),  # no customer identity in this section
        instruction="Napiši kratak narativ o prilikama po izvoru i prosječnoj vrijednosti prilike.",
        template=_template_opportunity_sources(sources, stats),
        narration_active=narration_active,
        client=client,
    )
    return _section("prilike_po_izvoru", "Prilike po izvoru", "analiza", narrative, source, data)


def _revenue_plan_section(
    session: Session,
    week_end: datetime.date,
    narration_active: bool,
    client: LLMClient | None,
) -> dict[str, Any]:
    """⑧ Prihod vs plan — revenue-vs-plan + run-rate forecast (C-CRM2)."""
    from valeri_api.crm.forecast import revenue_forecast

    forecast = revenue_forecast(session, week_end).model_dump(mode="json")
    masked_payload = {
        "sekcija": "Prihod naspram plana i projekcija",
        "podaci": forecast,
    }
    narrative, source = _narrate_or_template(
        session,
        masked_payload,
        MaskingContext(),  # company-level figures only, no identity
        instruction="Napiši kratak narativ o prihodu naspram plana i projekciji za mjesec.",
        template=_template_revenue_plan(forecast),
        narration_active=narration_active,
        client=client,
    )
    return _section("prihod_vs_plan", "Prihod vs plan", "analiza", narrative, source, forecast)


def _drafts_section(items: list[dict[str, Any]]) -> dict[str, Any]:
    """⑦ Prijedlozi poruka — customer-facing drafts awaiting approval (akcija)."""
    rows = [
        {
            "approval_id": item["approval_id"],
            "task_id": item["task_id"],
            "kind": item["kind"],
            "status": item["approval_status"],
            "customer_name": item["customer_name"],
            "rule": item["rule"],
            "message": (item["payload"] or {}).get("message"),
            "source": (item["payload"] or {}).get("source"),
        }
        for item in items
    ]
    if rows:
        narrative = (
            "Pripremljeni su prijedlozi poruka za kupce — čekaju odobrenje vlasnika. "
            "Nijedna poruka se ne šalje bez odobrenja."
        )
    else:
        narrative = "Nema pripremljenih prijedloga poruka ove sedmice."
    # No LLM here: the messages themselves were narrated (and gated) in the
    # approval workflow; this section just lists them with their status.
    return _section(
        "prijedlozi_poruka", "Prijedlozi poruka", "akcija", narrative, "template", {"items": rows}
    )


# ── deterministic Bosnian templates (the fallback; pure formatting of SQL values) ──


def _template_kpi(kpi: dict[str, Any]) -> str:
    delta = ""
    if kpi.get("revenue_delta_pct") is not None:
        delta = f" (promjena {kpi['revenue_delta_pct']}% u odnosu na prethodnu sedmicu)"
    return (
        f"Promet ove sedmice iznosi {kpi['week_revenue']} KM{delta}; "
        f"prethodna sedmica: {kpi['prior_week_revenue']} KM. "
        f"Novih signala: {kpi['new_signals']}; novih zadataka: {kpi['new_tasks']}; "
        f"ukupno otvorenih zadataka: {kpi['open_tasks']}.\n\n{FOOTER}"
    )


def _template_declines(items: list[dict[str, Any]]) -> str:
    lines = [
        f"- {item['customer_name']}: promet {item['value']} KM, "
        f"uobičajeno {item['baseline']} KM ({item['delta_pct']}%)"
        for item in items
    ]
    return "Najveći padovi prometa ove sedmice:\n" + "\n".join(lines) + f"\n\n{FOOTER}"


def _template_lost_articles(items: list[dict[str, Any]]) -> str:
    lines = [
        f"- {item['customer_name']}: \"{item['article_name']}\" ({item['article_code']}) — "
        f"zadnja narudžba {item['last_seen']}, prije {item['gap_days']} dana"
        for item in items
    ]
    return "Izgubljeni artikli ove sedmice:\n" + "\n".join(lines) + f"\n\n{FOOTER}"


def _template_sleeping(items: list[dict[str, Any]]) -> str:
    lines = [
        f"- {item['customer_name']}: zadnja narudžba {item['last_order_date']}, "
        f"prije {item['gap_days']} dana (uobičajeni razmak {item['avg_order_interval_d']} dana)"
        for item in items
    ]
    return "Uspavani kupci:\n" + "\n".join(lines) + f"\n\n{FOOTER}"


def _template_tasks(stats: dict[str, Any], items: list[dict[str, Any]]) -> str:
    header = (
        f"Zadaci kreirani ove sedmice: {stats['total']} "
        f"(otvoreno {stats['open']}, u toku {stats['in_progress']}, "
        f"završeno {stats['done']}, odbačeno {stats['dismissed']})."
    )
    lines = [f"- {item['title']} (rok: {item['due_date']})" for item in items]
    body = header
    if lines:
        body += "\nNajvažniji zadaci:\n" + "\n".join(lines)
    return f"{body}\n\n{FOOTER}"


def _template_opportunity_sources(sources: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    stats = jsonable(stats)
    header = (
        f"Ukupno prilika: {stats['total_count']}, "
        f"prosječna vrijednost prilike {stats['avg_value']} KM."
    )
    lines = [
        f"- {row['source']}: {row['count']} prilika, "
        f"vrijednost {row['value']} KM (ponderisano {row['weighted_value']} KM)"
        for row in jsonable(sources)
    ]
    return f"{header}\nPo izvoru:\n" + "\n".join(lines) + f"\n\n{FOOTER}"


def _template_revenue_plan(forecast: dict[str, Any]) -> str:
    target = forecast["target"]
    if target is None:
        plan_line = "Plan za ovaj mjesec nije postavljen."
    else:
        plan_line = (
            f"Plan: {target} KM; ostvareno do sada: {forecast['actual_mtd']} KM "
            f"(odstupanje {forecast['variance']} KM)."
        )
    body = (
        f"{plan_line} Projekcija za kraj mjeseca (run-rate): "
        f"{forecast['forecast']} KM, na osnovu {forecast['days_elapsed']} od "
        f"{forecast['days_in_month']} dana."
    )
    return f"{body}\n\n{FOOTER}"
