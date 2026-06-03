"""CI1 capture pipeline: graduated apply by stakes + PII masking.

Run on a rolled-back db_session with control customers inserted. The LLM is a
keyed fake; resolution is the real server-side pg_trgm/focus logic.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.fakes import FakeKbLLM
from valeri_api.kb.pipeline import mask_for_capture, run_capture
from valeri_api.llm.client import LLMResponse
from valeri_api.llm.masking import MaskingContext, pseudonym


class _GateOkExtractionFails:
    """Gate passes, but extraction always returns malformed JSON (hard failure)."""

    model = "fake-tier1"

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        body = '{"relevant": true}' if "filter relevantnosti" in system else "{ not valid json"
        return LLMResponse(text=body, model=self.model, tokens=50, latency_ms=30)


def _add_customer(session: Session, name: str, segment: str = "hotel") -> int:
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


# ── acceptance 1: stated deal → resolved, active commercial_event ───────────────


@pytest.mark.anyio
async def test_stated_deal_creates_resolved_event(db_session: Session) -> None:
    """A small, confidently-resolved deal auto-saves (resolved + evidence + confidence)."""
    customer_id = _add_customer(db_session, "Hotel Hills Sarajevo")
    extraction = {
        "facts": [],
        "events": [
            {
                "kind": "deal",
                "summary": "Mjesečna nabavka",
                "mentioned_name": "Hotel Hills Sarajevo",
                "value": 4200,  # below kb.high_stakes_value (10000) → may auto-save
                "categories": ["hemija"],
                "occurred_on": None,
                "source": "stated",
                "confidence": 0.9,
                "evidence_span": "Dogovorili smo nabavku, oko 4.200 KM",
            }
        ],
        "relationships": [],
        "confidence": 0.9,
    }
    response = run_capture(
        db_session,
        text_in="Dogovorili smo nabavku s Hotel Hills Sarajevo, oko 4.200 KM.",
        user_id=1,
        client=FakeKbLLM(extraction=extraction),
    )

    row = db_session.execute(
        text(
            "SELECT customer_id, value, source, status, evidence_text, confidence "
            "FROM app.commercial_event WHERE customer_id = :cid AND kind = 'deal'"
        ),
        {"cid": customer_id},
    ).one()
    assert row.customer_id == customer_id  # resolved to the right customer
    assert float(row.value) == 4200.0  # STATED value, stored as data
    assert row.source == "stated"
    assert row.status == "active"  # small + high-confidence + resolved → auto-saved
    assert "Dogovorili smo" in row.evidence_text  # raw message is the evidence
    assert float(row.confidence) == 0.9
    assert len(response.auto_saved) == 1


@pytest.mark.anyio
async def test_large_deal_goes_to_queue(db_session: Session) -> None:
    """A stated value ≥ kb.high_stakes_value is confirmed, not auto-saved — the
    threshold is enforced in code, not left to the model's stakes hint (§8.2)."""
    customer_id = _add_customer(db_session, "Hotel Evropa Veliki")
    extraction = {
        "facts": [],
        "events": [
            {
                "kind": "deal",
                "summary": "Godišnji ugovor",
                "mentioned_name": "Hotel Evropa Veliki",
                "value": 72000,  # ≥ high_stakes_value → high-stakes → confirm
                "categories": ["hemija"],
                "occurred_on": None,
                "source": "stated",
                "confidence": 0.95,
                "evidence_span": "Zaključio sam godišnji ugovor, oko 72.000 KM",
            }
        ],
        "relationships": [],
        "confidence": 0.95,
    }
    response = run_capture(
        db_session,
        text_in="Zaključio sam godišnji ugovor s Hotel Evropa Veliki, oko 72.000 KM.",
        user_id=1,
        client=FakeKbLLM(extraction=extraction),
    )

    status = db_session.execute(
        text("SELECT status FROM app.commercial_event WHERE customer_id = :cid AND kind = 'deal'"),
        {"cid": customer_id},
    ).scalar_one()
    assert status == "proposed"  # large stated value → confirmation queue
    assert response.auto_saved == []
    # No auto-save decision for a queued large deal.
    decisions = db_session.execute(
        text(
            "SELECT count(*) FROM app.decision d "
            "WHERE d.kind = 'kb_capture' AND d.payload->>'customer_id' = :cid"
        ),
        {"cid": str(customer_id)},
    ).scalar_one()
    assert decisions == 0


# ── acceptance 2: stated same_owner relationship → confirmation queue ───────────


@pytest.mark.anyio
async def test_same_owner_relationship_goes_to_queue(db_session: Session) -> None:
    hills = _add_customer(db_session, "Hotel Hills Centar")
    _add_customer(db_session, "Hotel Europe Glavni")
    extraction = {
        "facts": [],
        "events": [],
        "relationships": [
            {
                "rel_type": "same_owner",
                "from_name": "Hotel Hills Centar",
                "to_name": "Hotel Europe Glavni",
                "source": "stated",
                "confidence": 0.8,
                "evidence_span": "Isti su vlasnik kao Hotel Europe",
            }
        ],
        "confidence": 0.8,
    }
    run_capture(
        db_session,
        text_in="Hotel Hills Centar ima istog vlasnika kao Hotel Europe Glavni.",
        user_id=1,
        client=FakeKbLLM(extraction=extraction),
    )

    edge = db_session.execute(
        text(
            "SELECT status FROM app.client_relationship "
            "WHERE from_customer_id = :f AND rel_type = 'same_owner'"
        ),
        {"f": hills},
    ).one()
    assert edge.status == "proposed"  # consequential → NOT auto-applied

    # No kb_capture decision was written for the (un-applied) relationship.
    applied = db_session.execute(
        text(
            "SELECT count(*) FROM app.decision d "
            "WHERE d.kind = 'kb_capture' AND d.payload->>'item_type' = 'relationship'"
        )
    ).scalar_one()
    assert applied == 0


# ── acceptance 5: auto-save is a reversible, shown decision ─────────────────────


@pytest.mark.anyio
async def test_autosave_writes_reversible_decision(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Restoran Sunce Plus")
    before = db_session.execute(
        text("SELECT count(*) FROM app.decision WHERE kind = 'kb_capture'")
    ).scalar_one()
    extraction = {
        "facts": [
            {
                "fact_type": "preference",
                "fact_key": "isporuka",
                "value": {"dan": "ponedjeljak"},
                "mentioned_name": "Restoran Sunce Plus",
                "source": "stated",
                "stakes": "low",
                "confidence": 0.9,
                "evidence_span": "najbolje im je isporuka ponedjeljkom",
            }
        ],
        "events": [],
        "relationships": [],
        "confidence": 0.9,
    }
    run_capture(
        db_session,
        text_in="Restoran Sunce Plus — najbolje im je isporuka ponedjeljkom.",
        user_id=1,
        client=FakeKbLLM(extraction=extraction),
    )

    decision = db_session.execute(
        text(
            "SELECT actor, reversible, payload FROM app.decision "
            "WHERE kind = 'kb_capture' ORDER BY id DESC LIMIT 1"
        )
    ).one()
    assert decision.actor == "valeri"
    assert decision.reversible is True
    assert decision.payload["customer_id"] == customer_id
    after = db_session.execute(
        text("SELECT count(*) FROM app.decision WHERE kind = 'kb_capture'")
    ).scalar_one()
    assert after == before + 1

    # The living profile summary was refreshed.
    summary = db_session.execute(
        text("SELECT summary FROM app.client_profile WHERE customer_id = :cid"),
        {"cid": customer_id},
    ).scalar()
    assert summary  # non-empty


# ── acceptance 6: personal PII masked before the model ──────────────────────────


@pytest.mark.anyio
async def test_pii_masked_before_model(db_session: Session) -> None:
    customer_id = _add_customer(db_session, "Klinika Vita Nova")
    context = MaskingContext()
    masked = mask_for_capture(
        db_session,
        "Klinika Vita Nova, kontakt marko@vita.ba, tel +387 61 234 567 — posluju dobro.",
        context,
    )
    assert pseudonym(customer_id) in masked  # known customer → pseudonym
    assert "Klinika Vita Nova" not in masked
    assert "marko@vita.ba" not in masked  # e-mail stripped
    assert "234 567" not in masked  # phone stripped


@pytest.mark.anyio
async def test_person_name_masked_before_model(db_session: Session) -> None:
    """A person's name introduced by a role/title is redacted; a business name stays."""
    _add_customer(db_session, "Hotel Centar Glavni")
    context = MaskingContext()
    masked = mask_for_capture(
        db_session,
        "Direktor Marko Marković iz Hotel Centar Glavni kaže da kupac Fupupu kasni.",
        context,
    )
    assert "Marko Marković" not in masked  # personal name redacted
    assert "[osoba]" in masked
    assert "Fupupu" in masked  # unknown business name kept for resolution (§8.6)


@pytest.mark.anyio
async def test_capture_survives_extraction_failure_and_keeps_audit(db_session: Session) -> None:
    """A hard extraction failure captures nothing but does NOT raise, so the caller
    commits the audit.ai_log rows the failed attempts wrote (principle 7)."""
    before = db_session.execute(text("SELECT count(*) FROM audit.ai_log")).scalar_one()

    response = run_capture(
        db_session,
        text_in="Hotel posluje slabije ovih dana.",
        user_id=1,
        client=_GateOkExtractionFails(),
    )

    # Nothing captured, and crucially no exception propagated.
    assert response.auto_saved == []
    assert response.proposed == []
    assert response.clarifications == []
    # The rejected extraction attempts are recorded in the audit log (not rolled back).
    after = db_session.execute(text("SELECT count(*) FROM audit.ai_log")).scalar_one()
    assert after - before >= 1


@pytest.mark.anyio
async def test_irrelevant_message_captures_nothing(db_session: Session) -> None:
    """The gate skips a pure question → no extraction, no records."""
    response = run_capture(
        db_session,
        text_in="Koliki je promet ovog mjeseca?",
        user_id=1,
        client=FakeKbLLM(relevant=False),
    )
    assert response.auto_saved == []
    assert response.proposed == []
    assert response.clarifications == []
