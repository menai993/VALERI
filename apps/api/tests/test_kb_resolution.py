"""CI1 entity resolution (§8.1–8.2): deterministic pg_trgm + alias + focus.

Resolution is server-side and never the model. These run on a rolled-back
db_session with control customers inserted so they don't depend on seed names.
"""

import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.kb.resolution import resolve_mention


def _add_customer(session: Session, name: str, segment: str = "kafić") -> int:
    """Insert a customer under a throwaway legal entity; return its id."""
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


@pytest.mark.anyio
async def test_trgm_ranks_close_customer(db_session: Session) -> None:
    """'Fupupu' resolves to the close customer 'Fupy' but stays a CLARIFY (medium match)."""
    _add_customer(db_session, "Fupy")

    result = resolve_mention(db_session, "Fupupu")

    names = [c.name for c in result.candidates]
    assert "Fupy" in names, names
    fupy = next(c for c in result.candidates if c.name == "Fupy")
    assert 0.0 < fupy.similarity < 0.8  # close but not confident
    assert fupy.segment == "kafić"  # a distinguishing detail is returned
    assert result.decision == "clarify"
    assert result.customer_id is None


@pytest.mark.anyio
async def test_alias_short_circuits(db_session: Session) -> None:
    """A confirmed customer_alias resolves directly — no clarification."""
    customer_id = _add_customer(db_session, "Fupy")
    db_session.execute(
        text(
            "INSERT INTO app.customer_alias (alias, customer_id, source, confidence) "
            "VALUES ('Fupupu', :cid, 'stated', 0.99)"
        ),
        {"cid": customer_id},
    )

    result = resolve_mention(db_session, "Fupupu")

    assert result.decision == "auto"
    assert result.customer_id == customer_id
    assert result.reason == "alias"


@pytest.mark.anyio
async def test_focus_breaks_ties(db_session: Session) -> None:
    """When two customers match closely, the one currently in focus wins (auto)."""
    first = _add_customer(db_session, "Kafić Centar")
    second = _add_customer(db_session, "Kafić Centar Dva")

    # Without focus: the exact-ish match leads; with focus on the second, it wins.
    focused = resolve_mention(db_session, "Kafić Centar", context_customer_id=second)
    assert focused.decision == "auto"
    assert focused.customer_id == second
    assert focused.reason == "focus"
    assert first != second  # sanity


@pytest.mark.anyio
async def test_no_candidate_is_none(db_session: Session) -> None:
    """A name with no reasonable match resolves to 'none' (offer new prospect later)."""
    _add_customer(db_session, "Fupy")
    result = resolve_mention(db_session, "Zzzqwx Nepostojeći")
    assert result.decision == "none"
    assert result.candidates == []


@pytest.mark.anyio
async def test_exact_name_auto_resolves(db_session: Session) -> None:
    """An exact, unique name auto-resolves with high similarity."""
    customer_id = _add_customer(db_session, "Hotel Behar Jedinstven")
    result = resolve_mention(db_session, "Hotel Behar Jedinstven")
    assert result.decision == "auto"
    assert result.customer_id == customer_id
    assert result.candidates[0].similarity >= 0.8
    assert isinstance(result.candidates[0].last_order, (datetime.date, type(None)))
