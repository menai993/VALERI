"""Knowledge-base API (CI1) — per docs/client-intelligence.md §5.

Capture/notes run the extraction pipeline; pending is the review queue; confirm/
reject/edit/answer are RBAC-gated mutations that each write a reversible
app.decision. A sales_rep is row-scoped to its own customers (fail-closed);
finance is read-only (excluded from mutations). PII is masked before the model
inside the pipeline.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser, require_roles, visible_customer_ids
from valeri_api.auth.models import AppUser
from valeri_api.db import get_session
from valeri_api.kb import service
from valeri_api.kb.graph import graph_for_customer
from valeri_api.kb.models import Clarification, ClientFact, CommercialEvent
from valeri_api.kb.pipeline import run_capture
from valeri_api.kb.schemas import (
    CaptureRequest,
    CaptureResponse,
    ClarificationAnswer,
    ItemEdit,
    KnowledgeResponse,
    NoteCreate,
    PendingQueue,
)
from valeri_api.kb.service import KbError

router = APIRouter()

# Mutations: owner/admin/sales_rep (rep row-scoped); finance is read-only.
Editor = Annotated[AppUser, Depends(require_roles("owner", "admin", "sales_rep"))]


def _not_found(error: KbError) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": str(error)})


def _assert_customer_visible(user: AppUser, session: Session, customer_id: int) -> None:
    scope = visible_customer_ids(user, session)
    if scope is not None and customer_id not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": f"Nemate pristup kupcu {customer_id}"},
        )


@router.post("/kb/capture", response_model=CaptureResponse)
def capture(
    body: CaptureRequest,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> CaptureResponse:
    """Run extraction on free text; return what was auto-saved / proposed / asked."""
    if body.customer_id is not None:
        _assert_customer_visible(user, session, body.customer_id)
    response = run_capture(
        session,
        text_in=body.text,
        user_id=user.id,
        customer_focus_id=body.customer_id,
    )
    session.commit()
    return response


@router.post("/kb/notes", response_model=CaptureResponse)
def add_note(
    body: NoteCreate,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> CaptureResponse:
    """Log a note about a customer and capture knowledge from it."""
    _assert_customer_visible(user, session, body.customer_id)
    response = run_capture(
        session,
        text_in=body.text,
        user_id=user.id,
        customer_focus_id=body.customer_id,
    )
    session.commit()
    return response


@router.get("/kb/pending", response_model=PendingQueue)
def pending(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> PendingQueue:
    """The confirmation queue: proposed records + pending clarifications (rep-scoped)."""
    return service.pending_queue(session, customer_ids=visible_customer_ids(user, session))


@router.post("/kb/items/{item_id}/confirm")
def confirm(
    item_id: int,
    item_type: str,
    session: Annotated[Session, Depends(get_session)],
    user: Editor,
) -> dict:
    """Confirm a proposed fact/event/relationship → active (writes a decision)."""
    _guard_item_scope(user, session, item_type, item_id)
    try:
        decision = service.confirm_item(
            session, item_type=item_type, item_id=item_id, user_id=user.id
        )
    except KbError as error:
        raise _not_found(error) from error
    session.commit()
    return {"ok": True, "decision_id": decision.id}


@router.post("/kb/items/{item_id}/reject")
def reject(
    item_id: int,
    item_type: str,
    session: Annotated[Session, Depends(get_session)],
    user: Editor,
) -> dict:
    """Reject a proposed record (writes a decision)."""
    _guard_item_scope(user, session, item_type, item_id)
    try:
        decision = service.reject_item(
            session, item_type=item_type, item_id=item_id, user_id=user.id
        )
    except KbError as error:
        raise _not_found(error) from error
    session.commit()
    return {"ok": True, "decision_id": decision.id}


@router.patch("/kb/items/{item_id}")
def edit(
    item_id: int,
    body: ItemEdit,
    session: Annotated[Session, Depends(get_session)],
    user: Editor,
) -> dict:
    """Edit a record's editable fields (writes a decision)."""
    _guard_item_scope(user, session, body.item_type, item_id)
    try:
        decision = service.edit_item(session, item_id=item_id, edit=body, user_id=user.id)
    except KbError as error:
        raise _not_found(error) from error
    session.commit()
    return {"ok": True, "decision_id": decision.id}


@router.post("/kb/clarifications/{clarification_id}/answer")
def answer(
    clarification_id: int,
    body: ClarificationAnswer,
    session: Annotated[Session, Depends(get_session)],
    user: Editor,
) -> dict:
    """Answer a clarification (link / new prospect / not-a-match) — writes a decision."""
    _guard_clarification_scope(user, session, clarification_id, body)
    try:
        decision = service.answer_clarification(
            session, clarification_id=clarification_id, answer=body, user_id=user.id
        )
    except KbError as error:
        raise _not_found(error) from error
    session.commit()
    return {"ok": True, "decision_id": decision.id}


@router.get("/customers/{customer_id}/knowledge", response_model=KnowledgeResponse)
def customer_knowledge(
    customer_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> KnowledgeResponse:
    """The 'Šta VALERI zna' panel: profile + active facts + events + relationships."""
    _assert_customer_visible(user, session, customer_id)
    return service.knowledge_for_customer(session, customer_id)


@router.get("/kb/graph")
def kb_graph(
    customer_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    depth: int = 1,
) -> dict:
    """The relationship map (CI2): confirmed nodes + edges around a customer.

    A rep's graph omits members outside their scope (fail-closed, D7)."""
    _assert_customer_visible(user, session, customer_id)
    graph = graph_for_customer(session, customer_id, depth=depth)
    scope = visible_customer_ids(user, session)
    if scope is not None:
        graph["nodes"] = [n for n in graph["nodes"] if n["customer_id"] in scope]
        graph["edges"] = [e for e in graph["edges"] if e["from"] in scope and e["to"] in scope]
    return graph


def _guard_item_scope(user: AppUser, session: Session, item_type: str, item_id: int) -> None:
    """A rep may only act on items about their own customers (or unresolved ones)."""
    scope = visible_customer_ids(user, session)
    if scope is None:
        return
    try:
        record = service._get_record(session, item_type, item_id)
    except KbError:
        return  # the handler will 404
    customer_id = getattr(record, "customer_id", None) or getattr(record, "from_customer_id", None)
    if customer_id is not None and customer_id not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Zapis je izvan vašeg opsega"},
        )


def _guard_clarification_scope(
    user: AppUser, session: Session, clarification_id: int, body: ClarificationAnswer
) -> None:
    """A rep may only answer clarifications for their own records, and only link to
    a customer in their scope (so a rep can't re-link a record onto a foreign customer)."""
    scope = visible_customer_ids(user, session)
    if scope is None:
        return
    clarification = session.get(Clarification, clarification_id)
    if clarification is None:
        return  # the handler will 404

    # The target record must be in scope (unresolved records have no owner yet).
    ref_type, _, ref_id = clarification.target_record_ref.partition(":")
    if ref_type in ("client_fact", "commercial_event") and ref_id.isdigit():
        model = ClientFact if ref_type == "client_fact" else CommercialEvent
        record = session.get(model, int(ref_id))
        owner = getattr(record, "customer_id", None) if record is not None else None
        if owner is not None and owner not in scope:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Razjašnjenje je izvan vašeg opsega"},
            )

    # A chosen link target must be a customer the rep can see.
    chosen = body.option.get("customer_id")
    if chosen is not None and int(chosen) not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Kupac je izvan vašeg opsega"},
        )
