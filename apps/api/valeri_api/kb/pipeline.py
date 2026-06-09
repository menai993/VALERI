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
from valeri_api.llm.schemas import NarrationFailed

logger = logging.getLogger("valeri.kb.pipeline")

# Contact PII patterns scrubbed from free text before the model (principle 6).
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s\-/().]{6,}\d)(?!\w)")
_PII_TOKEN = "[kontakt]"
_PERSON_TOKEN = "[osoba]"

# A person's name introduced by a role/title word — redacted before the model.
# (A business name like "kupac Fupupu" is preceded by a business word, not these,
# so it survives for resolution per §8.6.)
_PERSON_INDICATOR_RE = re.compile(
    r"(?i)\b("
    r"direktor(?:ica)?|gospodin|gospođa|gđa|gdin|gosp\.?|vlasni(?:k|ca)|"
    r"menadžer(?:ica)?|šef(?:ica)?|kontakt(?:\s+osoba)?|kontakt-osoba|"
    r"osoba|nabavlja(?:č|čica)|šefica nabavke|direktor nabavke"
    r")\s+([A-ZČĆŽŠĐ][^\s,.;:!?]*(?:\s+[A-ZČĆŽŠĐ][^\s,.;:!?]*){0,2})"
)


def _redact_person_names(text: str) -> str:
    """Redact a Title-Case name that follows a person indicator (director/contact/…)."""
    return _PERSON_INDICATOR_RE.sub(lambda m: f"{m.group(1)} {_PERSON_TOKEN}", text)


def mask_for_capture(session: Session, raw_text: str, context: MaskingContext) -> str:
    """Pseudonymise KNOWN customers and strip personal PII; keep unknown business names.

    Unlike the chat masker, this does NOT blanket-redact unresolved capitalised names
    — an unknown business name (e.g. 'Fupupu') must survive so it can be captured and
    resolved (§8.6). What IS always removed: e-mail, phone, and a person's name when
    it follows a role/title indicator (a decision-maker/contact). Bare person names
    with no indicator are an inherent NER limit (documented; the realistic capture
    vector — "direktor X", "kontakt Y" — is covered).
    """
    masked = raw_text
    for matched_text, customer_id, real_name in resolve_entities(session, raw_text):
        alias = context.register_customer(customer_id, real_name)
        masked = masked.replace(matched_text, alias)
    masked = _EMAIL_RE.sub(_PII_TOKEN, masked)
    masked = _PHONE_RE.sub(_PII_TOKEN, masked)
    masked = _redact_person_names(masked)
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
    # A hard extraction failure is not fatal: capture nothing, but DON'T raise — so
    # the caller still commits the audit.ai_log rows the failed attempts wrote
    # (principle 7: the audit is append-only and must survive a failed capture).
    try:
        result = extract_candidates(
            session,
            masked_text=masked_text,
            raw_text=text_in,
            customer_focus=focus_pseudonym,
            message_id=message_id,
            client=client,
        )
    except NarrationFailed as failure:
        logger.info("kb extraction failed (%s); nothing captured, audit preserved", failure.reason)
        return CaptureResponse()

    dispositions: list[dict] = []
    # One clarification per ambiguous mentioned name across this whole capture.
    clarified: dict[str, int] = {}

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
                clarified=clarified,
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
                clarified=clarified,
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
                clarified=clarified,
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
