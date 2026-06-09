"""CI2 get_client_knowledge tool: confirmed KB with evidence + confidence, for the
investigation agent to cite. Read-only, RBAC-checked, proposed records excluded.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.graph_helpers import add_customer, add_edge
from valeri_api.auth.models import AppUser
from valeri_api.investigation.nodes import READ_ONLY_TOOLS
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import TOOLS, dispatch


def _owner() -> AppUser:
    return AppUser(id=1, name="O", email="o@x.ba", role="owner", password_hash="x")


def _rep(sales_rep_id: int) -> AppUser:
    return AppUser(
        id=2,
        name="R",
        email="r@x.ba",
        role="sales_rep",
        password_hash="x",
        sales_rep_id=sales_rep_id,
    )


def _add_fact(session: Session, cid: int, key: str, status: str) -> None:
    session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status, "
            " evidence_text) "
            "VALUES (:cid, 'preference', :key, CAST(:v AS jsonb), 'stated', 0.9, 'visoka', "
            ":status, 'najbolje ponedjeljkom')"
        ),
        {"cid": cid, "key": key, "v": '{"dan": "pon"}', "status": status},
    )


@pytest.mark.anyio
async def test_returns_confirmed_kb_with_evidence(db_session: Session) -> None:
    cid = add_customer(db_session, "Hotel Znanje")
    other = add_customer(db_session, "Hotel Vlasnik")
    _add_fact(db_session, cid, "isporuka", "active")
    _add_fact(db_session, cid, "pakovanje", "proposed")  # must be excluded
    db_session.execute(
        text(
            "INSERT INTO app.commercial_event "
            "(customer_id, kind, summary, value, source, confidence, conf_band, status, "
            " evidence_text) "
            "VALUES (:cid, 'deal', 'Godišnji ugovor', 5000, 'stated', 0.9, 'visoka', 'active', "
            "'zaključili ugovor')"
        ),
        {"cid": cid},
    )
    add_edge(db_session, cid, other, "same_owner", status="active")

    context = ToolContext(session=db_session, user=_owner())
    result = dispatch(context, "get_client_knowledge", {"customer_id": cid})

    assert result.ok, result.error
    out = result.output
    assert len(out["facts"]) == 1  # the proposed fact is excluded
    assert out["facts"][0]["evidence"] == "najbolje ponedjeljkom"
    assert out["facts"][0]["confidence"] == "0.900"
    assert len(out["events"]) == 1
    assert out["events"][0]["kind"] == "deal"
    assert out["events"][0]["evidence"] == "zaključili ugovor"
    assert len(out["relationships"]) == 1
    assert out["relationships"][0]["other_customer_id"] == other
    assert out["relationships"][0]["rel_type"] == "same_owner"


@pytest.mark.anyio
async def test_rbac_blocks_out_of_scope(db_session: Session) -> None:
    cid = add_customer(db_session, "Hotel Tudji")
    # A rep linked to a non-existent/irrelevant rep id sees no customers → forbidden.
    context = ToolContext(session=db_session, user=_rep(999999))
    result = dispatch(context, "get_client_knowledge", {"customer_id": cid})
    assert result.ok is False
    assert result.error_code == "forbidden"


@pytest.mark.anyio
async def test_registered_for_agent() -> None:
    assert "get_client_knowledge" in TOOLS
    assert "get_client_knowledge" in READ_ONLY_TOOLS
    assert TOOLS["get_client_knowledge"].mutates is False
