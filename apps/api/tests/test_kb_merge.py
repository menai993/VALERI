"""CI1 merge/dedup: a repeated fact supersedes rather than duplicates (acceptance 3)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.fakes import FakeKbLLM
from valeri_api.kb.pipeline import run_capture


def _add_customer(session: Session, name: str) -> int:
    le_id = session.execute(
        text("INSERT INTO core.legal_entity (name) VALUES (:n) RETURNING id"),
        {"n": f"{name} d.o.o."},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO core.customer (legal_entity_id, name, segment) "
            "VALUES (:le, :n, 'hotel') RETURNING id"
        ),
        {"le": le_id, "n": name},
    ).scalar_one()


def _fact_extraction(name: str, channel: str) -> dict:
    return {
        "facts": [
            {
                "fact_type": "preference",
                "fact_key": "kanal",
                "value": {"kanal": channel},
                "mentioned_name": name,
                "source": "stated",
                "stakes": "low",
                "confidence": 0.9,
                "evidence_span": f"najviše komuniciraju putem {channel}",
            }
        ],
        "events": [],
        "relationships": [],
        "confidence": 0.9,
    }


@pytest.mark.anyio
async def test_repeated_fact_supersedes(db_session: Session) -> None:
    name = "Hotel Neretva Jedini"
    customer_id = _add_customer(db_session, name)

    run_capture(
        db_session,
        text_in=f"{name} najviše komuniciraju putem email.",
        user_id=1,
        client=FakeKbLLM(extraction=_fact_extraction(name, "email")),
    )
    run_capture(
        db_session,
        text_in=f"{name} sada najviše komuniciraju putem telefon.",
        user_id=1,
        client=FakeKbLLM(extraction=_fact_extraction(name, "telefon")),
    )

    rows = db_session.execute(
        text(
            "SELECT status, value->>'kanal' AS kanal, superseded_by FROM app.client_fact "
            "WHERE customer_id = :cid AND fact_type = 'preference' AND fact_key = 'kanal' "
            "ORDER BY id"
        ),
        {"cid": customer_id},
    ).all()

    # Two rows total: the old superseded, the new active — never a duplicate.
    assert len(rows) == 2
    active = [r for r in rows if r.status == "active"]
    superseded = [r for r in rows if r.status == "superseded"]
    assert len(active) == 1
    assert len(superseded) == 1
    assert active[0].kanal == "telefon"  # latest wins
    assert superseded[0].kanal == "email"
    assert superseded[0].superseded_by is not None  # points at the new fact
