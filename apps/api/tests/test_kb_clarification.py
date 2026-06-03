"""CI1 clarification (§8.6, the Fupupu case): a high-stakes fact about an ambiguous
name is NOT auto-attached — it stays proposed and raises one short question.

The answer round-trip (link → active + customer_alias + reversible decision) is in
test_kb_api.py, which exercises the service/endpoints.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.fakes import FakeKbLLM
from valeri_api.kb.pipeline import run_capture


def _add_customer(session: Session, name: str, segment: str = "kafić") -> int:
    le_id = session.execute(
        text("INSERT INTO core.legal_entity (name) VALUES (:n) RETURNING id"),
        {"n": f"{name} d.o.o."},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO core.customer (legal_entity_id, name, segment) "
            "VALUES (:le, :n, :seg) RETURNING id"
        ),
        {"le": le_id, "n": name, "seg": segment},
    ).scalar_one()


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


@pytest.mark.anyio
async def test_high_stakes_ambiguous_name_not_autoattached(db_session: Session) -> None:
    fupy_id = _add_customer(db_session, "Fupy")

    run_capture(
        db_session,
        text_in="kupac Fupupu kasni s plaćanjem",
        user_id=1,
        client=FakeKbLLM(extraction=_FUPUPU),
    )

    # The fact is stored PROPOSED and UNRESOLVED — nothing landed on Fupy.
    fact = db_session.execute(
        text(
            "SELECT id, customer_id, mentioned_name, status, evidence_text "
            "FROM app.client_fact WHERE fact_type = 'payment_late'"
        )
    ).one()
    assert fact.status == "proposed"
    assert fact.customer_id is None
    assert fact.mentioned_name == "Fupupu"
    assert "Fupupu" in fact.evidence_text

    on_fupy = db_session.execute(
        text("SELECT count(*) FROM app.client_fact WHERE customer_id = :cid"),
        {"cid": fupy_id},
    ).scalar_one()
    assert on_fupy == 0  # NOT auto-attached

    # A 'da li ste mislili…/novi kupac?' clarification was raised for that fact.
    clar = db_session.execute(
        text(
            "SELECT kind, question, options, target_record_ref, status "
            "FROM app.clarification WHERE target_record_ref = :ref"
        ),
        {"ref": f"client_fact:{fact.id}"},
    ).one()
    assert clar.kind == "entity"
    assert clar.status == "pending"
    assert "Fupy" in clar.question
    assert "novi kupac" in clar.question.lower()
    actions = {opt["action"] for opt in clar.options}
    assert {"link", "pick_other", "create_prospect"} <= actions
    link_option = next(opt for opt in clar.options if opt["action"] == "link")
    assert link_option["customer_id"] == fupy_id


@pytest.mark.anyio
async def test_low_confidence_fact_queued(db_session: Session) -> None:
    """A confidently-resolved but low-confidence fact is proposed, not auto-saved."""
    name = "Hotel Borac Jedinstveni"
    customer_id = _add_customer(db_session, name, segment="hotel")
    extraction = {
        "facts": [
            {
                "fact_type": "preference",
                "fact_key": "pakovanje",
                "value": {"pakovanje": "veliko"},
                "mentioned_name": name,
                "source": "inferred",
                "stakes": "low",
                "confidence": 0.5,  # below kb.fact_autosave_confidence (0.75)
                "evidence_span": "možda vole veća pakovanja",
            }
        ],
        "events": [],
        "relationships": [],
        "confidence": 0.5,
    }
    run_capture(
        db_session,
        text_in=f"{name} možda vole veća pakovanja.",
        user_id=1,
        client=FakeKbLLM(extraction=extraction),
    )
    status = db_session.execute(
        text(
            "SELECT status FROM app.client_fact "
            "WHERE customer_id = :cid AND fact_key = 'pakovanje'"
        ),
        {"cid": customer_id},
    ).scalar_one()
    assert status == "proposed"
