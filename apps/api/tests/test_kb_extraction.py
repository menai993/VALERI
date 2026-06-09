"""CI1 extraction (Tier-1, structured): typed candidates, reject+retry, provenance.

Uses fakes — no real gateway. Extraction receives already-masked text and emits
qualitative candidates only (never a computed number). Each pass logs one
app.kb_extraction row and writes audit.ai_log (incl. rejected attempts).
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.fakes import FakeKbLLM, ScriptedFakeLLMClient
from valeri_api.kb.extraction import extract_candidates
from valeri_api.kb.gate import is_relevant

_DEAL_EXTRACTION = {
    "facts": [
        {
            "fact_type": "intent",
            "fact_key": "category_expansion",
            "value": {"category": "hemija"},
            "mentioned_name": "Kupac-abc123",
            "source": "stated",
            "stakes": "low",
            "confidence": 0.85,
            "evidence_span": "kreću i s hemijom od idućeg mjeseca",
        }
    ],
    "events": [
        {
            "kind": "deal",
            "summary": "Godišnji ugovor",
            "mentioned_name": "Kupac-abc123",
            "value": 72000,
            "categories": ["hemija"],
            "occurred_on": None,
            "source": "stated",
            "confidence": 0.9,
            "evidence_span": "Zaključio sam godišnji ugovor, oko 72.000 KM",
        }
    ],
    "relationships": [],
    "confidence": 0.88,
}


def _ai_log_count(session: Session) -> int:
    return session.execute(text("SELECT count(*) FROM audit.ai_log")).scalar_one()


@pytest.mark.anyio
async def test_extraction_returns_typed_candidates(db_session: Session) -> None:
    client = FakeKbLLM(extraction=_DEAL_EXTRACTION)
    result = extract_candidates(
        db_session,
        masked_text="Zaključio sam godišnji ugovor s Kupac-abc123, oko 72.000 KM.",
        raw_text="Zaključio sam godišnji ugovor s Hotel Hills, oko 72.000 KM.",
        client=client,
    )
    assert len(result.events) == 1
    assert result.events[0].kind == "deal"
    assert float(result.events[0].value) == 72000.0
    assert result.events[0].source == "stated"
    assert len(result.facts) == 1
    assert result.facts[0].fact_type == "intent"


@pytest.mark.anyio
async def test_malformed_extraction_rejected_and_retried(db_session: Session) -> None:
    """Bad JSON then good → one valid result; the rejected attempt is logged."""
    before = _ai_log_count(db_session)
    client = ScriptedFakeLLMClient(["{ not valid json", json.dumps(_DEAL_EXTRACTION)])
    result = extract_candidates(db_session, masked_text="…", raw_text="…", client=client)
    assert len(result.events) == 1
    assert len(client.captured) == 2  # it retried after the reject
    assert _ai_log_count(db_session) - before >= 2  # reject + accept both logged


@pytest.mark.anyio
async def test_extraction_logs_kb_extraction_and_ai_log(db_session: Session) -> None:
    before_ai = _ai_log_count(db_session)
    before_kx = db_session.execute(text("SELECT count(*) FROM app.kb_extraction")).scalar_one()

    extract_candidates(
        db_session,
        masked_text="Kupac-abc123 je zadovoljan.",
        raw_text="Hotel Hills je zadovoljan.",
        client=FakeKbLLM(extraction=_DEAL_EXTRACTION),
    )

    after_kx = db_session.execute(text("SELECT count(*) FROM app.kb_extraction")).scalar_one()
    assert after_kx - before_kx == 1
    assert _ai_log_count(db_session) - before_ai >= 1
    # The provenance row keeps the REAL utterance (on-prem), and the model id.
    row = db_session.execute(
        text("SELECT raw_text, model FROM app.kb_extraction ORDER BY id DESC LIMIT 1")
    ).one()
    assert row.raw_text == "Hotel Hills je zadovoljan."
    assert row.model == "fake-tier1"


@pytest.mark.anyio
async def test_extraction_sends_only_masked_text(db_session: Session) -> None:
    """The LLM sees the masked text — never the real customer name."""
    client = FakeKbLLM(extraction=_DEAL_EXTRACTION)
    extract_candidates(
        db_session,
        masked_text="Kupac-abc123 širi nabavku.",
        raw_text="Hotel Hills širi nabavku.",
        client=client,
    )
    sent = client.captured[-1]["user"]
    assert "Kupac-abc123" in sent
    assert "Hotel Hills" not in sent


@pytest.mark.anyio
async def test_relevance_gate_skips_pure_question(db_session: Session) -> None:
    """A pure question gates out (no extraction should follow in the pipeline)."""
    assert (
        is_relevant(db_session, "Koliki je promet ovog mjeseca?", client=FakeKbLLM(relevant=False))
        is False
    )
    assert (
        is_relevant(db_session, "Hotel posluje slabije.", client=FakeKbLLM(relevant=True)) is True
    )
