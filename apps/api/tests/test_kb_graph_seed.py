"""CI2 demo seed: the graph edges are off by default and, when enabled, connect the
right planted cases (so a scan surfaces group/twin/referral signals out of the box).

Pure generation test — no scan/DB, so it can't ripple into the shared seed fixture.
The graph rules themselves are covered by test_group_risk / test_behavioral_twin /
test_referral_risk.
"""

import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.seed.config import SeedConfig
from valeri_api.seed.generate import generate

_RNG = 20260601


@pytest.mark.anyio
async def test_graph_seed_off_by_default() -> None:
    data = generate(SeedConfig(rng_seed=_RNG, as_of=datetime.date.today()))
    assert data.client_relationships == []  # shared test seed stays graph-free


@pytest.mark.anyio
async def test_graph_seed_plants_confirmed_edges_on_the_right_cases() -> None:
    data = generate(SeedConfig(rng_seed=_RNG, as_of=datetime.date.today(), with_kb_graph=True))
    rels = data.client_relationships
    by_type = {r["rel_type"]: r for r in rels}

    assert set(by_type) == {"same_owner", "behavioral_twin", "referral"}
    for rel in rels:
        assert rel["status"] == "active"  # CONFIRMED (the graph rules only read active)
        assert rel["source"] == "stated"
        assert str(rel["confidence"]) == "0.900"

    decline_ids = {d["customer_id"] for d in data.manifest["declines"]}
    sleeping_ids = {s["customer_id"] for s in data.manifest["sleeping"]}

    # same_owner links two declining objects → group_risk fires together.
    so = by_type["same_owner"]
    assert {so["from_customer_id"], so["to_customer_id"]} <= decline_ids

    # behavioral_twin links two sleeping (churned) customers → twin early warning.
    tw = by_type["behavioral_twin"]
    assert {tw["from_customer_id"], tw["to_customer_id"]} <= sleeping_ids

    # referral: a sleeping (quiet) referrer points at another customer.
    ref = by_type["referral"]
    assert ref["from_customer_id"] in sleeping_ids
    assert ref["to_customer_id"] not in sleeping_ids


@pytest.mark.anyio
async def test_graph_seed_loads_into_db(db_session: Session) -> None:
    """The loader persists the demo edges as confirmed client_relationship rows."""
    from valeri_api.seed.loader import load, reset

    data = generate(SeedConfig(rng_seed=_RNG, as_of=datetime.date.today(), with_kb_graph=True))
    reset(db_session)
    load(data, db_session)
    db_session.flush()

    rows = db_session.execute(
        text("SELECT rel_type, status, source FROM app.client_relationship ORDER BY id")
    ).all()
    assert {r.rel_type for r in rows} == {"same_owner", "behavioral_twin", "referral"}
    assert all(r.status == "active" and r.source == "stated" for r in rows)
