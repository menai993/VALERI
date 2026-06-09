"""Data-aware fallback narration (Ask VALERI): the reply when no tool fits.

When the intent router returns 'help' (a greeting, an unclear or out-of-scope
message) or picks no tool, VALERI must not repeat one canned sentence. Instead it
narrates a short, warm reply grounded in a small, SQL-computed, RBAC-scoped context
bundle (open signals, the user's open tasks, a couple of at-risk customers, and —
for non-reps — a headline turnover figure). The LLM only narrates these finished
numbers; it never computes one (principle 1). PII is masked before the prompt and
rehydrated for the human (principle 6). This path performs no mutations.
"""

import datetime
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import visible_customer_ids
from valeri_api.auth.models import AppUser
from valeri_api.conversation.schemas import ChatAnswer
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_customer_fields, rehydrate
from valeri_api.llm.prompts import GENERAL_ASSISTANT_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.conversation.assistant")

# What VALERI can do — guides the model toward a concrete next step (and the
# deterministic fallback's capability hint). Kept number-free on purpose.
CAPABILITIES = [
    "promet i poređenje perioda (cijela firma ili pojedini kupac)",
    "kupci u padu i otvoreni AI signali",
    "izgubljeni artikli i kontekst kupca",
    "šta VALERI zna o kupcu (zabilježene činjenice, dogovori, veze)",
    "kreiranje zadatka za kupca",
]


def narrate_assistant(
    session: Session,
    user: AppUser,
    context: MaskingContext,
    client: LLMClient | None = None,
) -> tuple[str, str, str]:
    """Narrate the data-aware fallback. Returns (rehydrated_text, register, source).

    source is "llm" (validated) or "template" (deterministic) — never raw output.
    """
    bundle = _context_bundle(session, user)

    masked_payload = {
        "kontekst": mask_customer_fields(bundle, context),
        "mogucnosti": CAPABILITIES,
    }

    try:
        answer, _, _ = narrate_structured(
            session,
            masked_payload,
            ChatAnswer,
            system_prompt=GENERAL_ASSISTANT_SYSTEM_PROMPT,
            instruction=(
                "Odgovori korisniku na osnovu priloženog konteksta (sve brojke su već "
                "izračunate u bazi — koristi ih doslovno). Završi jednim kratkim potpitanjem."
            ),
            client=client,
            role="simple_qa",  # M12: Tier-1 by role
        )
        return rehydrate(answer.text, context), answer.register, "llm"
    except NarrationFailed as failure:
        logger.warning("assistant narration failed (%s); falling back to template", failure.reason)
        return rehydrate(_assistant_template(bundle), context), "analiza", "template"


# ── the SQL-computed context bundle (numbers from SQL only, RBAC-scoped) ───────


def _context_bundle(session: Session, user: AppUser) -> dict[str, Any]:
    """Small, finished facts about the user's current picture. All values from SQL."""
    scope = visible_customer_ids(user, session)
    scoped = scope is not None
    scope_ids = sorted(scope) if scoped else []

    # "Open" = still active (not dismissed/suppressed/resolved); 'tasked' signals
    # already became a task but remain part of the live picture.
    open_signals = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal "
            "WHERE status IN ('new', 'tasked') "
            "  AND (CAST(:scoped AS boolean) IS FALSE "
            "       OR customer_id = ANY(CAST(:ids AS bigint[])))"
        ),
        {"scoped": scoped, "ids": scope_ids},
    ).scalar()

    # Open tasks: a rep sees their own queue; owner/admin see all. Finance has no
    # task surface, so this stays 0 for them (assignee filter never matches).
    if user.role == "sales_rep":
        open_tasks = session.execute(
            text(
                "SELECT COUNT(*) FROM app.task "
                "WHERE status IN ('open', 'in_progress') AND assignee_id = :rep"
            ),
            {"rep": user.sales_rep_id},
        ).scalar()
    elif user.role in ("owner", "admin"):
        open_tasks = session.execute(
            text("SELECT COUNT(*) FROM app.task WHERE status IN ('open', 'in_progress')")
        ).scalar()
    else:
        open_tasks = 0

    at_risk = [
        {"customer_id": row.customer_id, "customer_name": row.name}
        for row in session.execute(
            text(
                "SELECT DISTINCT s.customer_id, c.name "
                "FROM app.signal s JOIN core.customer c ON c.id = s.customer_id "
                "WHERE s.rule = 'customer_decline' AND s.status IN ('new', 'tasked') "
                "  AND (CAST(:scoped AS boolean) IS FALSE "
                "       OR s.customer_id = ANY(CAST(:ids AS bigint[]))) "
                "ORDER BY s.customer_id LIMIT 3"
            ),
            {"scoped": scoped, "ids": scope_ids},
        )
    ]

    bundle: dict[str, Any] = {
        "otvoreni_signali": open_signals,
        "otvoreni_zadaci": open_tasks,
        "kupci_u_padu": at_risk,
    }

    # Company-wide turnover is finance-grade — only non-reps see it (RBAC).
    if not scoped:
        today = datetime.date.today()
        from_date = today - datetime.timedelta(days=30)
        bundle["promet_30d"] = session.execute(
            text(
                "SELECT COALESCE(SUM(l.line_total), 0) FROM core.invoice_line l "
                "JOIN core.invoice i ON i.id = l.invoice_id "
                "WHERE i.date > :a AND i.date <= :b"
            ),
            {"a": from_date, "b": today},
        ).scalar()

    return bundle


# ── deterministic fallback (no LLM) — still names the real counts ──────────────

_CAPABILITY_HINT = (
    "Mogu pomoći s prometom, kupcima u padu, AI signalima, izgubljenim artiklima, "
    "kontekstom kupca i kreiranjem zadataka. Šta vas zanima?"
)


def _assistant_template(bundle: dict[str, Any]) -> str:
    """A varied-but-deterministic reply built from the SQL bundle (never the old static line)."""
    parts = [
        f"Trenutno: {bundle['otvoreni_signali']} otvorenih AI signala "
        f"i {bundle['otvoreni_zadaci']} otvorenih zadataka."
    ]
    if bundle.get("promet_30d") is not None:
        parts.append(f"Promet u zadnjih 30 dana: {bundle['promet_30d']} KM.")
    at_risk = bundle.get("kupci_u_padu", [])
    if at_risk:
        names = ", ".join(item["customer_name"] for item in at_risk)
        parts.append(f"Kupci u padu koje vrijedi pogledati: {names}.")
    parts.append(_CAPABILITY_HINT)
    return " ".join(parts)
