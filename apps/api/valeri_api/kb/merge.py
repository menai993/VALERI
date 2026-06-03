"""Merge/dedup + profile-summary maintenance (CI1).

A new fact about an existing (customer_id, fact_type, fact_key) supersedes the
old (status='superseded', superseded_by set) so there is always at most one
active fact per key — never a duplicate. The client_profile.summary is kept
current (Tier-1 narration over masked, qualitative inputs; template fallback).
Numbers stay in SQL — the summary only narrates qualitative facts.
"""

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.conversation.schemas import ChatAnswer
from valeri_api.kb.models import ClientFact, ClientProfile
from valeri_api.kb.prompts import PROFILE_SUMMARY_INSTRUCTION, PROFILE_SUMMARY_SYSTEM_PROMPT
from valeri_api.kb.resolution import conf_band_for
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, _scrub
from valeri_api.llm.router.roles import ROLE_KB_SUMMARY
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.kb.merge")


def merge_fact(
    session: Session,
    *,
    customer_id: int,
    fact_type: str,
    fact_key: str,
    value: dict[str, Any],
    source: str,
    confidence: float,
    evidence_text: str | None,
    source_message_id: int | None,
    source_user_id: int | None,
) -> ClientFact:
    """Insert an active fact, superseding any prior active fact for the same key."""
    prior = (
        session.query(ClientFact)
        .filter(
            ClientFact.customer_id == customer_id,
            ClientFact.fact_type == fact_type,
            ClientFact.fact_key == fact_key,
            ClientFact.status == "active",
        )
        .one_or_none()
    )

    fact = ClientFact(
        customer_id=customer_id,
        fact_type=fact_type,
        fact_key=fact_key,
        value=jsonable(value),
        source=source,
        source_message_id=source_message_id,
        source_user_id=source_user_id,
        evidence_text=evidence_text,
        confidence=Decimal(str(confidence)),
        conf_band=conf_band_for(confidence),
        status="active",
    )

    if prior is not None:
        # Free the (customer, type, key) active slot before inserting the new one
        # (the partial unique index allows only one active row per key).
        prior.status = "superseded"
        session.flush()
        session.add(fact)
        session.flush()
        prior.superseded_by = fact.id
        session.flush()
    else:
        session.add(fact)
        session.flush()
    return fact


# ── profile summary ─────────────────────────────────────────────────────────────


def refresh_profile_summary(
    session: Session, customer_id: int, *, client: LLMClient | None = None
) -> None:
    """Recompute and upsert client_profile.summary from active facts + recent events."""
    facts = session.execute(
        text(
            "SELECT fact_type, fact_key, value FROM app.client_fact "
            "WHERE customer_id = :cid AND status = 'active' ORDER BY id"
        ),
        {"cid": customer_id},
    ).all()
    events = session.execute(
        text(
            "SELECT kind, summary FROM app.commercial_event "
            "WHERE customer_id = :cid AND status = 'active' ORDER BY id DESC LIMIT 10"
        ),
        {"cid": customer_id},
    ).all()

    summary = _narrate_summary(session, customer_id, facts, events, client)

    existing = session.get(ClientProfile, customer_id)
    if existing is None:
        session.add(ClientProfile(customer_id=customer_id, summary=summary))
    else:
        existing.summary = summary
        session.execute(
            text("UPDATE app.client_profile SET updated_at = now() WHERE customer_id = :cid"),
            {"cid": customer_id},
        )
    session.flush()


def _template_summary(facts: list, events: list) -> str:
    """Deterministic Bosnian summary fallback (no LLM)."""
    return (
        f"VALERI je o ovom kupcu zabilježio {len(facts)} činjenica "
        f"i {len(events)} poslovnih događaja."
    )


def _narrate_summary(session: Session, customer_id: int, facts: list, events: list, client) -> str:
    """Tier-1 Bosnian summary over masked, qualitative inputs; template on failure."""
    if client is None:
        return _template_summary(facts, events)

    context = MaskingContext()
    pseudonym = context.register_customer(customer_id, "")  # identity never leaves
    payload = {
        "kupac": pseudonym,
        "cinjenice": [
            {"tip": f.fact_type, "kljuc": f.fact_key, "vrijednost": _scrub(f.value)} for f in facts
        ],
        "dogadjaji": [{"vrsta": e.kind, "sazetak": e.summary} for e in events],
    }
    try:
        answer, _, _ = narrate_structured(
            session,
            payload,
            ChatAnswer,
            system_prompt=PROFILE_SUMMARY_SYSTEM_PROMPT,
            instruction=PROFILE_SUMMARY_INSTRUCTION,
            client=client,
            text_field="text",  # the number contract still holds for any figure quoted
            register="analiza",
            role=ROLE_KB_SUMMARY,
        )
        return answer.text
    except NarrationFailed as failure:
        logger.info("profile summary narration failed (%s); using template", failure.reason)
        return _template_summary(facts, events)
