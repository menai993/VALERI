"""Capture orchestrator (CI1): one utterance → typed, resolved, applied knowledge.

  mask (known customers → pseudonyms; contact PII stripped) → relevance gate
  (Tier-1) → extraction (Tier-1, structured) → server-side resolution (pseudonym
  map-back / pg_trgm / focus) → apply by stakes (auto-save | confirmation queue |
  clarification).

Runs on every chat message (async, via the chat hook) and synchronously on
POST /kb/capture and /kb/notes. Numbers for analysis stay in SQL; the LLM only
extracts/narrates. Unknown business-name tokens are deliberately KEPT visible
(so a new customer can be captured/resolved, §8.6) while contact PII is removed.
"""

import logging
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.conversation.resolution import resolve_entities
from valeri_api.kb.apply import apply_event, apply_fact, apply_relationship
from valeri_api.kb.extraction import extract_candidates
from valeri_api.kb.gate import is_relevant
from valeri_api.kb.models import Clarification, ClientFact, ClientRelationship, CommercialEvent
from valeri_api.kb.read import event_to_read, fact_to_read, relationship_to_read
from valeri_api.kb.resolution import resolve_mention
from valeri_api.kb.schemas import CaptureResponse, ClarificationRead, ResolutionResult
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext

logger = logging.getLogger("valeri.kb.pipeline")

# Contact PII patterns scrubbed from free text before the model (principle 6).
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s\-/().]{6,}\d)(?!\w)")
_PII_TOKEN = "[kontakt]"


def mask_for_capture(session: Session, raw_text: str, context: MaskingContext) -> str:
    """Pseudonymise KNOWN customers and strip contact PII; keep unknown names visible.

    Unlike the chat masker, this does NOT redact unresolved capitalised names — an
    unknown business name (e.g. 'Fupupu') must survive so it can be captured and
    resolved (§8.6). Personal contact data (e-mail/phone) is always removed.
    """
    masked = raw_text
    for matched_text, customer_id, real_name in resolve_entities(session, raw_text):
        alias = context.register_customer(customer_id, real_name)
        masked = masked.replace(matched_text, alias)
    masked = _EMAIL_RE.sub(_PII_TOKEN, masked)
    masked = _PHONE_RE.sub(_PII_TOKEN, masked)
    return masked


def _resolve_mention_or_focus(
    session: Session,
    mentioned_name: str | None,
    context: MaskingContext,
    customer_focus_id: int | None,
) -> ResolutionResult:
    """Map an extracted mention back to a customer id (server-side, never the model).

    A pseudonym the model echoed maps straight back; an unknown literal name goes
    through pg_trgm resolution; an empty mention falls back to the focus customer.
    """
    if mentioned_name:
        mapped = context.customer_id_for(mentioned_name)
        if mapped is not None:
            return ResolutionResult(
                mentioned_name=mentioned_name,
                decision="auto",
                customer_id=mapped,
                reason="pseudonym",
            )
        return resolve_mention(session, mentioned_name, context_customer_id=customer_focus_id)
    if customer_focus_id is not None:
        return ResolutionResult(
            mentioned_name="", decision="auto", customer_id=customer_focus_id, reason="focus"
        )
    return ResolutionResult(mentioned_name="", decision="none", reason="no_mention")


def run_capture(
    session: Session,
    *,
    text_in: str,
    user_id: int | None,
    message_id: int | None = None,
    customer_focus_id: int | None = None,
    client: LLMClient | None = None,
) -> CaptureResponse:
    """The full capture pipeline for one utterance. Returns what was saved/proposed."""
    context = MaskingContext()
    focus_pseudonym = None
    if customer_focus_id is not None:
        real_name = session.execute(
            text("SELECT name FROM core.customer WHERE id = :id"), {"id": customer_focus_id}
        ).scalar()
        if real_name is not None:
            focus_pseudonym = context.register_customer(customer_focus_id, real_name)

    masked_text = mask_for_capture(session, text_in, context)

    # ── relevance gate (cost lever) ───────────────────────────────────────────
    if not is_relevant(session, masked_text, client=client):
        return CaptureResponse()

    # ── extraction ────────────────────────────────────────────────────────────
    result = extract_candidates(
        session,
        masked_text=masked_text,
        raw_text=text_in,
        customer_focus=focus_pseudonym,
        message_id=message_id,
        client=client,
    )

    dispositions: list[dict] = []

    for fact in result.facts:
        resolution = _resolve_mention_or_focus(
            session, fact.mentioned_name, context, customer_focus_id
        )
        dispositions.append(
            apply_fact(
                session,
                fact,
                resolution,
                source_message_id=message_id,
                source_user_id=user_id,
                client=client,
            )
        )

    for event in result.events:
        resolution = _resolve_mention_or_focus(
            session, event.mentioned_name, context, customer_focus_id
        )
        dispositions.append(
            apply_event(
                session,
                event,
                resolution,
                source_message_id=message_id,
                source_user_id=user_id,
                client=client,
            )
        )

    for rel in result.relationships:
        from_resolution = _resolve_mention_or_focus(
            session, rel.from_name, context, customer_focus_id
        )
        to_resolution = _resolve_mention_or_focus(session, rel.to_name, context, None)
        dispositions.append(
            apply_relationship(
                session,
                rel,
                from_resolution,
                to_resolution,
                source_message_id=message_id,
                source_user_id=user_id,
            )
        )

    return _build_response(session, dispositions)


def _build_response(session: Session, dispositions: list[dict]) -> CaptureResponse:
    """Turn apply dispositions into the CaptureResponse (auto-saved / proposed / clarifications)."""
    response = CaptureResponse()
    clarification_ids: list[int] = []

    for disposition in dispositions:
        record_id = disposition["record_id"]
        item_type = disposition["item_type"]
        if disposition["clarification_id"]:
            clarification_ids.append(disposition["clarification_id"])
        if not record_id:
            continue

        if item_type == "fact":
            item = fact_to_read(session, session.get(ClientFact, record_id))
        elif item_type == "event":
            item = event_to_read(session, session.get(CommercialEvent, record_id))
        else:
            item = relationship_to_read(session, session.get(ClientRelationship, record_id))

        if disposition["auto_saved"]:
            response.auto_saved.append(item)
        else:
            response.proposed.append(item)

    if clarification_ids:
        rows = (
            session.query(Clarification)
            .filter(Clarification.id.in_(clarification_ids))
            .order_by(Clarification.id)
            .all()
        )
        response.clarifications = [ClarificationRead.model_validate(c) for c in rows]

    return response
