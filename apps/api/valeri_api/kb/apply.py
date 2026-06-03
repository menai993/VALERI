"""Graduated apply by stakes (CI1, §8.2; same discipline as self-config).

  • resolved + low-stakes + high-confidence  → auto-save (status='active',
    reversible app.decision kind='kb_capture', actor='valeri', profile refreshed)
  • resolved + high-stakes OR low-confidence  → confirmation queue (status='proposed')
  • unresolved mention                        → status='proposed' + a clarification
  • relationships                             → always 'proposed' (consequential edge)

Nothing consequential is ever applied silently; every auto-save is reversible and
shown (the decision feed + the in-chat capture chip).
"""

import datetime
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.audit.serialization import jsonable
from valeri_api.kb.clarification import (
    build_entity_options,
    build_entity_question,
    raise_clarification,
)
from valeri_api.kb.merge import merge_fact, refresh_profile_summary
from valeri_api.kb.models import ClientFact, ClientRelationship, CommercialEvent
from valeri_api.kb.resolution import conf_band_for
from valeri_api.kb.schemas import (
    ExtractedEvent,
    ExtractedFact,
    ExtractedRelationship,
    ResolutionResult,
)
from valeri_api.kb.stakes import classify_stakes
from valeri_api.llm.client import LLMClient
from valeri_api.rules.engine import load_rule_config

logger = logging.getLogger("valeri.kb.apply")

# Events that are negative/consequential and must be confirmed (not auto-saved).
_HIGH_STAKES_EVENTS = ("complaint",)

# Where a fact's value might carry a monetary amount (so the high_stakes_value
# threshold is enforced for money facts, not just payment-prefixed ones).
_AMOUNT_KEYS = ("amount", "value", "iznos", "vrijednost")


def _autosave_confidence(session: Session) -> float:
    return float(load_rule_config(session, "kb")["fact_autosave_confidence"])


def _value_amount(value: dict | None) -> float | None:
    """Pull a numeric amount out of a fact value (None when it carries no money)."""
    if not isinstance(value, dict):
        return None
    for key in _AMOUNT_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, int | float) and not isinstance(candidate, bool):
            return float(candidate)
        if isinstance(candidate, str):
            try:
                return float(candidate.replace(",", "."))
            except ValueError:
                continue
    return None


def _disposition(
    item_type: str,
    record_id: int,
    customer_id: int | None,
    status: str,
    *,
    auto_saved: bool,
    clarification_id: int | None = None,
    decision_id: int | None = None,
) -> dict:
    return {
        "item_type": item_type,
        "record_id": record_id,
        "customer_id": customer_id,
        "status": status,
        "auto_saved": auto_saved,
        "clarification_id": clarification_id,
        "decision_id": decision_id,
    }


def _clarify_for_mention(
    session: Session, resolution: ResolutionResult, clarified: dict[str, int]
) -> int | None:
    """Raise ONE entity clarification per ambiguous mentioned name, deduped per capture.

    Several records (facts/events/an edge endpoint) that name the same ambiguous
    customer share a single clarification (targeting `mention:<name>`); answering it
    re-links every proposed record of that mention. This stops the queue from being
    spammed with identical questions.
    """
    if resolution.decision != "clarify":
        return None
    key = (resolution.mentioned_name or "").strip().lower()
    if key in clarified:
        return clarified[key]
    clarification = raise_clarification(
        session,
        kind="entity",
        question=build_entity_question(resolution),
        options=build_entity_options(resolution),
        target_record_ref=f"mention:{resolution.mentioned_name}",
    )
    clarified[key] = clarification.id
    return clarification.id


def apply_fact(
    session: Session,
    extracted: ExtractedFact,
    resolution: ResolutionResult,
    *,
    source_message_id: int | None,
    source_user_id: int | None,
    client: LLMClient | None = None,
    clarified: dict[str, int] | None = None,
) -> dict:
    """Apply one fact candidate by stakes."""
    clarified = {} if clarified is None else clarified
    resolved = resolution.decision == "auto"
    stakes = classify_stakes(
        session,
        item_type="fact",
        fact_type=extracted.fact_type,
        value_amount=_value_amount(extracted.value),
        extracted_stakes=extracted.stakes,
    )

    # Auto-save only a confidently-resolved, low-stakes, high-confidence fact.
    if resolved and stakes == "low" and extracted.confidence >= _autosave_confidence(session):
        fact = merge_fact(
            session,
            customer_id=resolution.customer_id,
            fact_type=extracted.fact_type,
            fact_key=extracted.fact_key,
            value=extracted.value,
            source=extracted.source,
            confidence=extracted.confidence,
            evidence_text=extracted.evidence_span,
            source_message_id=source_message_id,
            source_user_id=source_user_id,
        )
        decision = log_decision(
            session,
            kind="kb_capture",
            actor="valeri",
            summary=f"VALERI je zabilježio činjenicu: {extracted.fact_type}/{extracted.fact_key}",
            payload={
                "item_type": "fact",
                "record_id": fact.id,
                "customer_id": resolution.customer_id,
                "fact_type": extracted.fact_type,
                "fact_key": extracted.fact_key,
            },
            reversible=True,
        )
        refresh_profile_summary(session, resolution.customer_id, client=client)
        return _disposition(
            "fact",
            fact.id,
            resolution.customer_id,
            "active",
            auto_saved=True,
            decision_id=decision.id,
        )

    # Otherwise propose (confirmation queue), possibly with a clarification.
    fact = ClientFact(
        customer_id=resolution.customer_id,  # None when unresolved
        mentioned_name=resolution.mentioned_name if not resolved else None,
        fact_type=extracted.fact_type,
        fact_key=extracted.fact_key,
        value=jsonable(extracted.value),
        source=extracted.source,
        source_message_id=source_message_id,
        source_user_id=source_user_id,
        evidence_text=extracted.evidence_span,
        confidence=Decimal(str(extracted.confidence)),
        conf_band=conf_band_for(extracted.confidence),
        status="proposed",
    )
    session.add(fact)
    session.flush()
    clarification_id = _clarify_for_mention(session, resolution, clarified)
    return _disposition(
        "fact",
        fact.id,
        resolution.customer_id,
        "proposed",
        auto_saved=False,
        clarification_id=clarification_id,
    )


def apply_event(
    session: Session,
    extracted: ExtractedEvent,
    resolution: ResolutionResult,
    *,
    source_message_id: int | None,
    source_user_id: int | None,
    client: LLMClient | None = None,
    clarified: dict[str, int] | None = None,
) -> dict:
    """Apply one commercial-event candidate by stakes.

    A small deal auto-saves; a complaint, or a stated value at/above
    kb.high_stakes_value, goes to the confirmation queue (the threshold is enforced
    here, not left to the model's own stakes hint).
    """
    clarified = {} if clarified is None else clarified
    resolved = resolution.decision == "auto"
    value_amount = float(extracted.value) if extracted.value is not None else None
    high_stakes = (
        extracted.kind in _HIGH_STAKES_EVENTS
        or classify_stakes(session, item_type="event", value_amount=value_amount) == "high"
    )

    occurred = extracted.occurred_on or datetime.date.today()
    value = Decimal(str(extracted.value)) if extracted.value is not None else None

    if resolved and not high_stakes and extracted.confidence >= _autosave_confidence(session):
        event = CommercialEvent(
            customer_id=resolution.customer_id,
            kind=extracted.kind,
            summary=extracted.summary,
            value=value,
            categories=jsonable(extracted.categories) if extracted.categories else None,
            occurred_on=occurred,
            source=extracted.source,
            source_message_id=source_message_id,
            source_user_id=source_user_id,
            evidence_text=extracted.evidence_span,
            confidence=Decimal(str(extracted.confidence)),
            conf_band=conf_band_for(extracted.confidence),
            status="active",
        )
        session.add(event)
        session.flush()
        decision = log_decision(
            session,
            kind="kb_capture",
            actor="valeri",
            summary=f"VALERI je zabilježio događaj: {extracted.kind} — {extracted.summary}",
            payload={
                "item_type": "event",
                "record_id": event.id,
                "customer_id": resolution.customer_id,
                "kind": extracted.kind,
            },
            reversible=True,
        )
        refresh_profile_summary(session, resolution.customer_id, client=client)
        return _disposition(
            "event",
            event.id,
            resolution.customer_id,
            "active",
            auto_saved=True,
            decision_id=decision.id,
        )

    event = CommercialEvent(
        customer_id=resolution.customer_id,
        mentioned_name=resolution.mentioned_name if not resolved else None,
        kind=extracted.kind,
        summary=extracted.summary,
        value=value,
        categories=jsonable(extracted.categories) if extracted.categories else None,
        occurred_on=occurred,
        source=extracted.source,
        source_message_id=source_message_id,
        source_user_id=source_user_id,
        evidence_text=extracted.evidence_span,
        confidence=Decimal(str(extracted.confidence)),
        conf_band=conf_band_for(extracted.confidence),
        status="proposed",
    )
    session.add(event)
    session.flush()
    clarification_id = _clarify_for_mention(session, resolution, clarified)
    return _disposition(
        "event",
        event.id,
        resolution.customer_id,
        "proposed",
        auto_saved=False,
        clarification_id=clarification_id,
    )


def apply_relationship(
    session: Session,
    extracted: ExtractedRelationship,
    from_resolution: ResolutionResult,
    to_resolution: ResolutionResult,
    *,
    source_message_id: int | None,
    source_user_id: int | None,
    clarified: dict[str, int] | None = None,
) -> dict:
    """A relationship is consequential — always proposed (await confirm), never auto-applied."""
    clarified = {} if clarified is None else clarified
    from_id = from_resolution.customer_id if from_resolution.decision == "auto" else None
    to_id = to_resolution.customer_id if to_resolution.decision == "auto" else None

    # An edge needs both endpoints; store with whatever resolved and clarify the rest.
    edge = ClientRelationship(
        from_customer_id=from_id or 0,
        to_customer_id=to_id or 0,
        rel_type=extracted.rel_type,
        source=extracted.source,
        source_message_id=source_message_id,
        source_user_id=source_user_id,
        evidence_text=extracted.evidence_span,
        confidence=Decimal(str(extracted.confidence)),
        conf_band=conf_band_for(extracted.confidence),
        status="proposed",
    )
    # Only persist a real edge when both ends resolved; otherwise raise a clarification
    # and leave the edge unsaved (it would violate the FK with id 0).
    if from_id and to_id:
        session.add(edge)
        session.flush()
        return _disposition("relationship", edge.id, from_id, "proposed", auto_saved=False)

    # An endpoint is ambiguous — ask which customer (deduped per mentioned name).
    unresolved = to_resolution if to_id is None else from_resolution
    clarification_id = _clarify_for_mention(session, unresolved, clarified)
    return _disposition(
        "relationship", 0, None, "unresolved", auto_saved=False, clarification_id=clarification_id
    )
