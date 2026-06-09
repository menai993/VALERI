"""Read serializers (CI1): KB rows → the envelope-carrying API shapes.

Shared by the capture pipeline (CaptureResponse), the review queue, and the
client-360 knowledge panel. Customer names are rehydrated server-side for humans;
register tags follow §4.5 (facts/events = Analiza, suggested links = Preporuka).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.kb.models import ClientFact, ClientRelationship, CommercialEvent
from valeri_api.kb.schemas import KbItemRead, RelationshipRead


def _customer_name(session: Session, customer_id: int | None) -> str | None:
    if customer_id is None:
        return None
    return session.execute(
        text("SELECT name FROM core.customer WHERE id = :id"), {"id": customer_id}
    ).scalar()


def fact_to_read(session: Session, fact: ClientFact) -> KbItemRead:
    return KbItemRead(
        item_type="fact",
        id=fact.id,
        customer_id=fact.customer_id,
        customer_name=_customer_name(session, fact.customer_id),
        mentioned_name=fact.mentioned_name,
        title=f"{fact.fact_type} · {fact.fact_key}",
        detail=jsonable(fact.value),
        register="analiza",
        source=fact.source,
        confidence=str(jsonable(fact.confidence)),
        conf_band=fact.conf_band,
        status=fact.status,
        evidence_text=fact.evidence_text,
        source_message_id=fact.source_message_id,
        created_at=fact.created_at,
    )


def event_to_read(session: Session, event: CommercialEvent) -> KbItemRead:
    return KbItemRead(
        item_type="event",
        id=event.id,
        customer_id=event.customer_id,
        customer_name=_customer_name(session, event.customer_id),
        mentioned_name=event.mentioned_name,
        title=f"{event.kind} · {event.summary}",
        detail={
            "kind": event.kind,
            "value": str(jsonable(event.value)) if event.value is not None else None,
            "categories": jsonable(event.categories),
            "occurred_on": jsonable(event.occurred_on),
        },
        register="analiza",
        source=event.source,
        confidence=str(jsonable(event.confidence)),
        conf_band=event.conf_band,
        status=event.status,
        evidence_text=event.evidence_text,
        source_message_id=event.source_message_id,
        created_at=event.created_at,
    )


def relationship_to_read(session: Session, edge: ClientRelationship) -> RelationshipRead:
    return RelationshipRead(
        id=edge.id,
        from_customer_id=edge.from_customer_id,
        from_name=_customer_name(session, edge.from_customer_id),
        to_customer_id=edge.to_customer_id,
        to_name=_customer_name(session, edge.to_customer_id),
        rel_type=edge.rel_type,
        register="preporuka",  # a suggested link awaits confirmation
        source=edge.source,
        confidence=str(jsonable(edge.confidence)),
        conf_band=edge.conf_band,
        status=edge.status,
        evidence_text=edge.evidence_text,
        created_at=edge.created_at,
    )
