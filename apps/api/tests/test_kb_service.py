"""CI1 review operations: confirm/reject/edit + the clarification answer loop.

Each operation writes a reversible app.decision; answering a 'link' clarification
writes a customer_alias (the §8.5 learning loop) and re-links the proposed record.
Runs on a rolled-back db_session.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.fakes import FakeKbLLM
from valeri_api.kb.pipeline import run_capture
from valeri_api.kb.schemas import ClarificationAnswer, ItemEdit
from valeri_api.kb.service import (
    answer_clarification,
    confirm_item,
    edit_item,
    knowledge_for_customer,
    pending_queue,
    reject_item,
)

_FUPUPU = {
    "facts": [
        {
            "fact_type": "payment_late",
            "fact_key": "status",
            "value": {"status": "late"},
            "mentioned_name": "Fupupu",
            "source": "stated",
            "stakes": "high",
            "confidence": 0.86,
            "evidence_span": "kupac Fupupu kasni s plaćanjem",
        }
    ],
    "events": [],
    "relationships": [],
    "confidence": 0.86,
}


def _add_customer(session: Session, name: str) -> int:
    le_id = session.execute(
        text("INSERT INTO core.legal_entity (name) VALUES (:n) RETURNING id"),
        {"n": f"{name} d.o.o."},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO core.customer (legal_entity_id, name, segment) "
            "VALUES (:le, :n, 'kafić') RETURNING id"
        ),
        {"le": le_id, "n": name},
    ).scalar_one()


def _propose_fupupu(session: Session) -> tuple[int, int, int]:
    """Capture the ambiguous Fupupu fact; return (fupy_id, fact_id, clarification_id)."""
    fupy_id = _add_customer(session, "Fupy")
    run_capture(
        session,
        text_in="kupac Fupupu kasni s plaćanjem",
        user_id=1,
        client=FakeKbLLM(extraction=_FUPUPU),
    )
    fact_id = session.execute(
        text("SELECT id FROM app.client_fact WHERE fact_type = 'payment_late'")
    ).scalar_one()
    clar_id = session.execute(
        text("SELECT id FROM app.clarification WHERE target_record_ref = :ref"),
        {"ref": f"client_fact:{fact_id}"},
    ).scalar_one()
    return fupy_id, fact_id, clar_id


# ── confirm / reject / edit ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_confirm_activates_and_writes_decision(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Hotel Confirm Test")
    fact_id = db_session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status) "
            "VALUES (:cid, 'preference', 'isporuka', '{\"dan\":\"pon\"}', 'stated', 0.9, "
            "'visoka', 'proposed') RETURNING id"
        ),
        {"cid": customer_id},
    ).scalar_one()

    decision = confirm_item(db_session, item_type="fact", item_id=fact_id, user_id=1)

    status = db_session.execute(
        text("SELECT status FROM app.client_fact WHERE id = :id"), {"id": fact_id}
    ).scalar_one()
    assert status == "active"
    assert decision.kind == "approval"
    assert decision.actor == "user"
    assert decision.reversible is True


@pytest.mark.anyio
async def test_reject_marks_rejected_and_writes_decision(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Hotel Reject Test")
    fact_id = db_session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status) "
            "VALUES (:cid, 'preference', 'x', '{}', 'stated', 0.9, 'visoka', 'proposed') "
            "RETURNING id"
        ),
        {"cid": customer_id},
    ).scalar_one()

    decision = reject_item(db_session, item_type="fact", item_id=fact_id, user_id=1)
    status = db_session.execute(
        text("SELECT status FROM app.client_fact WHERE id = :id"), {"id": fact_id}
    ).scalar_one()
    assert status == "rejected"
    assert decision.kind == "rejection"


@pytest.mark.anyio
async def test_edit_changes_value_and_writes_decision(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Hotel Edit Test")
    fact_id = db_session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status) "
            "VALUES (:cid, 'preference', 'x', CAST(:val AS jsonb), 'stated', 0.9, 'visoka', "
            "'active') RETURNING id"
        ),
        {"cid": customer_id, "val": '{"a": 1}'},
    ).scalar_one()

    decision = edit_item(
        db_session,
        item_id=fact_id,
        edit=ItemEdit(item_type="fact", value={"a": 2}),
        user_id=1,
    )
    value = db_session.execute(
        text("SELECT value->>'a' FROM app.client_fact WHERE id = :id"), {"id": fact_id}
    ).scalar_one()
    assert value == "2"
    assert decision.kind == "kb_capture"
    assert decision.reversible is True


# ── the clarification answer loop (acceptance 4, second half) ───────────────────


@pytest.mark.anyio
async def test_answer_link_writes_alias_and_decision(db_session: Session) -> None:
    fupy_id, fact_id, clar_id = _propose_fupupu(db_session)

    decision = answer_clarification(
        db_session,
        clarification_id=clar_id,
        answer=ClarificationAnswer(option={"action": "link", "customer_id": fupy_id}),
        user_id=1,
    )

    # The fact re-links to Fupy and becomes active.
    fact = db_session.execute(
        text("SELECT customer_id, status FROM app.client_fact WHERE id = :id"),
        {"id": fact_id},
    ).one()
    assert fact.customer_id == fupy_id
    assert fact.status == "active"

    # A customer_alias 'Fupupu' → Fupy is learned (§8.5).
    alias_target = db_session.execute(
        text("SELECT customer_id FROM app.customer_alias WHERE lower(alias) = 'fupupu'")
    ).scalar_one()
    assert alias_target == fupy_id

    # The decision is reversible and shown; the clarification is answered.
    assert decision.kind == "approval"
    assert decision.reversible is True
    clar_status = db_session.execute(
        text("SELECT status FROM app.clarification WHERE id = :id"), {"id": clar_id}
    ).scalar_one()
    assert clar_status == "answered"


@pytest.mark.anyio
async def test_answer_reject_does_not_relink(db_session: Session) -> None:
    fupy_id, fact_id, clar_id = _propose_fupupu(db_session)

    answer_clarification(
        db_session,
        clarification_id=clar_id,
        answer=ClarificationAnswer(option={"action": "pick_other"}),
        user_id=1,
    )

    fact = db_session.execute(
        text("SELECT customer_id, status FROM app.client_fact WHERE id = :id"),
        {"id": fact_id},
    ).one()
    assert fact.customer_id is None  # stays unresolved — nothing landed on Fupy
    # No alias was learned from a rejection.
    aliases = db_session.execute(
        text("SELECT count(*) FROM app.customer_alias WHERE lower(alias) = 'fupupu'")
    ).scalar_one()
    assert aliases == 0


# ── read assembly ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_pending_queue_lists_proposed(db_session: Session) -> None:
    _fupy, fact_id, _clar = _propose_fupupu(db_session)
    queue = pending_queue(db_session)
    assert any(f.id == fact_id for f in queue.facts)
    assert queue.clarifications  # the entity clarification is pending


@pytest.mark.anyio
async def test_knowledge_returns_active_records(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Hotel Knowledge Test")
    db_session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status) "
            "VALUES (:cid, 'preference', 'kanal', '{\"k\":\"email\"}', 'stated', 0.9, "
            "'visoka', 'active')"
        ),
        {"cid": customer_id},
    )
    knowledge = knowledge_for_customer(db_session, customer_id)
    assert len(knowledge.facts) == 1
    assert knowledge.facts[0].register == "analiza"
    assert knowledge.facts[0].customer_id == customer_id
