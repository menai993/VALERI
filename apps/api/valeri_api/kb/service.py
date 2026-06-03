"""KB review operations + read assembly (CI1).

Confirm / reject / edit a proposed record and answer a clarification — each writes
an append-only, reversible app.decision (principle 10). Answering a 'link'
clarification also writes a customer_alias (the §8.5 learning loop). Plus the
read assembly for the review queue and the client-360 knowledge panel.
"""

import datetime
import logging
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.audit.models import Decision
from valeri_api.audit.serialization import jsonable
from valeri_api.kb.merge import refresh_profile_summary
from valeri_api.kb.models import (
    Clarification,
    ClientFact,
    ClientProfile,
    ClientRelationship,
    CommercialEvent,
)
from valeri_api.kb.read import event_to_read, fact_to_read, relationship_to_read
from valeri_api.kb.schemas import (
    ClarificationAnswer,
    ClarificationRead,
    ItemEdit,
    KnowledgeResponse,
    PendingQueue,
    ProfileRead,
)
from valeri_api.llm.client import LLMClient

logger = logging.getLogger("valeri.kb.service")

_MODELS = {"fact": ClientFact, "event": CommercialEvent, "relationship": ClientRelationship}


class KbError(Exception):
    """A KB operation failed in an expected way (missing record, bad ref)."""


def _get_record(session: Session, item_type: str, item_id: int):
    model = _MODELS.get(item_type)
    if model is None:
        raise KbError(f"Nepoznat tip zapisa: {item_type}")
    record = session.get(model, item_id)
    if record is None:
        raise KbError(f"Zapis {item_type}:{item_id} ne postoji")
    return record


def _supersede_active_fact(session: Session, fact: ClientFact) -> None:
    """Free the (customer, type, key) active slot before activating `fact`."""
    if fact.customer_id is None:
        return
    others = (
        session.query(ClientFact)
        .filter(
            ClientFact.customer_id == fact.customer_id,
            ClientFact.fact_type == fact.fact_type,
            ClientFact.fact_key == fact.fact_key,
            ClientFact.status == "active",
            ClientFact.id != fact.id,
        )
        .all()
    )
    for other in others:
        other.status = "superseded"
        other.superseded_by = fact.id
    if others:
        session.flush()


# ── confirm / reject / edit ─────────────────────────────────────────────────────


def confirm_item(
    session: Session, *, item_type: str, item_id: int, user_id: int | None
) -> Decision:
    """Promote a proposed record to active; write a reversible approval decision."""
    record = _get_record(session, item_type, item_id)
    if item_type == "fact":
        _supersede_active_fact(session, record)
    record.status = "active"
    session.flush()

    decision = log_decision(
        session,
        kind="approval",
        actor="user",
        summary=f"Potvrđen zapis znanja: {item_type}:{item_id}",
        payload={"item_type": item_type, "record_id": item_id, "action": "confirm"},
        reversible=True,
    )
    _maybe_refresh(session, item_type, record)
    return decision


def reject_item(session: Session, *, item_type: str, item_id: int, user_id: int | None) -> Decision:
    """Reject a proposed record; write a reversible rejection decision."""
    record = _get_record(session, item_type, item_id)
    record.status = "rejected"
    session.flush()
    return log_decision(
        session,
        kind="rejection",
        actor="user",
        summary=f"Odbijen zapis znanja: {item_type}:{item_id}",
        payload={"item_type": item_type, "record_id": item_id, "action": "reject"},
        reversible=True,
    )


def edit_item(session: Session, *, item_id: int, edit: ItemEdit, user_id: int | None) -> Decision:
    """Edit a record's editable fields; write a reversible kb_capture decision."""
    record = _get_record(session, edit.item_type, item_id)
    changed: dict[str, Any] = {}
    if edit.customer_id is not None and hasattr(record, "customer_id"):
        record.customer_id = edit.customer_id
        changed["customer_id"] = edit.customer_id
    if edit.value is not None and isinstance(record, ClientFact):
        record.value = jsonable(edit.value)
        changed["value"] = edit.value
    if edit.fact_key is not None and isinstance(record, ClientFact):
        record.fact_key = edit.fact_key
        changed["fact_key"] = edit.fact_key
    if edit.summary is not None and isinstance(record, CommercialEvent):
        record.summary = edit.summary
        changed["summary"] = edit.summary
    session.flush()
    return log_decision(
        session,
        kind="kb_capture",
        actor="user",
        summary=f"Izmijenjen zapis znanja: {edit.item_type}:{item_id}",
        payload={"item_type": edit.item_type, "record_id": item_id, "changed": changed},
        reversible=True,
    )


def _maybe_refresh(session: Session, item_type: str, record) -> None:
    if item_type in ("fact", "event") and getattr(record, "customer_id", None):
        refresh_profile_summary(session, record.customer_id, client=None)


# ── clarification answer (the §8.5 learning loop) ───────────────────────────────


def answer_clarification(
    session: Session,
    *,
    clarification_id: int,
    answer: ClarificationAnswer,
    user_id: int | None,
    client: LLMClient | None = None,
) -> Decision:
    """Apply a tappable clarification answer; write a reversible decision (+ alias on link)."""
    clarification = session.get(Clarification, clarification_id)
    if clarification is None:
        raise KbError(f"Razjašnjenje {clarification_id} ne postoji")

    ref_type, _, ref_id_str = clarification.target_record_ref.partition(":")
    option = answer.option
    action = option.get("action")

    decision = _apply_clarification_action(
        session, ref_type, ref_id_str, action, option, clarification
    )

    clarification.status = "answered"
    clarification.answer = jsonable(option)
    clarification.answered_by = user_id
    clarification.answered_at = datetime.datetime.now(datetime.UTC)
    session.flush()
    return decision


def _apply_clarification_action(
    session: Session,
    ref_type: str,
    ref_id_str: str,
    action: str | None,
    option: dict[str, Any],
    clarification: Clarification,
) -> Decision:
    # A 'mention:<name>' clarification covers EVERY proposed record of that mention;
    # legacy 'client_fact:<id>'/'commercial_event:<id>' refs target a single record.
    records = _clarification_records(session, ref_type, ref_id_str)
    if ref_type == "mention":
        mentioned = ref_id_str
    else:
        mentioned = records[0].mentioned_name if records else None

    if action in ("link", "create_prospect") and records:
        if action == "link":
            customer_id = int(option["customer_id"])
        else:
            customer_id = _create_prospect(session, mentioned or "Novi kupac")

        for record in records:
            record.customer_id = customer_id
            if isinstance(record, ClientFact):
                _supersede_active_fact(session, record)
            record.status = "active"
        session.flush()
        if mentioned:
            _write_alias(session, mentioned, customer_id)
        refresh_profile_summary(session, customer_id, client=None)

        verb = "Povezano" if action == "link" else "Kreiran novi kupac za"
        return log_decision(
            session,
            kind="approval",
            actor="user",
            summary=f"{verb}: „{mentioned}“ → kupac {customer_id} ({len(records)} zapis(a))",
            payload={
                "target": clarification.target_record_ref,
                "action": action,
                "customer_id": customer_id,
                "alias": mentioned,
                "records": len(records),
            },
            reversible=True,
        )

    # pick_other / no match: leave the records unresolved; remember the rejection.
    return log_decision(
        session,
        kind="rejection",
        actor="user",
        summary=f"Odbijen prijedlog povezivanja za {clarification.target_record_ref}",
        payload={"target": clarification.target_record_ref, "action": action or "dismiss"},
        reversible=True,
    )


def _clarification_records(session: Session, ref_type: str, ref_value: str) -> list:
    """The proposed, unresolved records a clarification covers."""
    if ref_type == "mention":
        facts = (
            session.query(ClientFact)
            .filter(
                func.lower(ClientFact.mentioned_name) == ref_value.lower(),
                ClientFact.status == "proposed",
                ClientFact.customer_id.is_(None),
            )
            .all()
        )
        events = (
            session.query(CommercialEvent)
            .filter(
                func.lower(CommercialEvent.mentioned_name) == ref_value.lower(),
                CommercialEvent.status == "proposed",
                CommercialEvent.customer_id.is_(None),
            )
            .all()
        )
        return [*facts, *events]
    if ref_type in ("client_fact", "commercial_event") and ref_value.isdigit():
        model = ClientFact if ref_type == "client_fact" else CommercialEvent
        record = session.get(model, int(ref_value))
        return [record] if record is not None else []
    return []


def _write_alias(session: Session, alias: str, customer_id: int) -> None:
    """Learn the alias so the same mention resolves directly next time (§8.5)."""
    session.execute(
        text(
            "INSERT INTO app.customer_alias (alias, customer_id, source, confidence) "
            "VALUES (:alias, :cid, 'stated', 0.95) "
            "ON CONFLICT (alias) DO UPDATE SET customer_id = excluded.customer_id"
        ),
        {"alias": alias, "cid": customer_id},
    )


def _create_prospect(session: Session, name: str) -> int:
    """Create a minimal prospect customer (its own legal entity), status='prospect'."""
    le_id = session.execute(
        text("INSERT INTO core.legal_entity (name) VALUES (:n) RETURNING id"),
        {"n": name},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO core.customer (legal_entity_id, name, status) "
            "VALUES (:le, :n, 'prospect') RETURNING id"
        ),
        {"le": le_id, "n": name},
    ).scalar_one()


# ── read assembly: review queue + knowledge ────────────────────────────────────


def _scope_clause(customer_ids: set[int] | None, column: str = "customer_id") -> tuple[str, dict]:
    if customer_ids is None:
        return "", {}
    return f" AND ({column} = ANY(:scope) OR {column} IS NULL)", {"scope": sorted(customer_ids)}


def pending_queue(session: Session, *, customer_ids: set[int] | None = None) -> PendingQueue:
    """Proposed facts/events/relationships + pending clarifications (rep-scoped)."""
    facts = (
        session.query(ClientFact)
        .filter(ClientFact.status == "proposed")
        .order_by(ClientFact.id.desc())
        .all()
    )
    events = (
        session.query(CommercialEvent)
        .filter(CommercialEvent.status == "proposed")
        .order_by(CommercialEvent.id.desc())
        .all()
    )
    rels = (
        session.query(ClientRelationship)
        .filter(ClientRelationship.status == "proposed")
        .order_by(ClientRelationship.id.desc())
        .all()
    )
    clars = (
        session.query(Clarification)
        .filter(Clarification.status == "pending")
        .order_by(Clarification.id.desc())
        .all()
    )

    def visible(customer_id: int | None) -> bool:
        return customer_ids is None or customer_id is None or customer_id in customer_ids

    return PendingQueue(
        facts=[fact_to_read(session, f) for f in facts if visible(f.customer_id)],
        events=[event_to_read(session, e) for e in events if visible(e.customer_id)],
        relationships=[
            relationship_to_read(session, r)
            for r in rels
            if visible(r.from_customer_id) or visible(r.to_customer_id)
        ],
        clarifications=[ClarificationRead.model_validate(c) for c in clars],
    )


def knowledge_for_customer(session: Session, customer_id: int) -> KnowledgeResponse:
    """Profile + active facts + active events + relationships for one customer."""
    profile = session.get(ClientProfile, customer_id)
    facts = (
        session.query(ClientFact)
        .filter(ClientFact.customer_id == customer_id, ClientFact.status == "active")
        .order_by(ClientFact.id.desc())
        .all()
    )
    events = (
        session.query(CommercialEvent)
        .filter(CommercialEvent.customer_id == customer_id, CommercialEvent.status == "active")
        .order_by(CommercialEvent.occurred_on.desc().nullslast(), CommercialEvent.id.desc())
        .all()
    )
    rels = (
        session.query(ClientRelationship)
        .filter(
            (
                (ClientRelationship.from_customer_id == customer_id)
                | (ClientRelationship.to_customer_id == customer_id)
            ),
            ClientRelationship.status.in_(("active", "proposed")),
        )
        .order_by(ClientRelationship.id.desc())
        .all()
    )
    return KnowledgeResponse(
        profile=ProfileRead.model_validate(profile) if profile is not None else None,
        facts=[fact_to_read(session, f) for f in facts],
        events=[event_to_read(session, e) for e in events],
        relationships=[relationship_to_read(session, r) for r in rels],
    )
