"""CI2 GET /kb/graph: confirmed edges only; a rep's graph is scope-limited (D7)."""

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import OWNER_EMAIL


def _edge(conn, a: int, b: int, rel_type: str, status: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO app.client_relationship "
            "(from_customer_id, to_customer_id, rel_type, source, confidence, conf_band, status) "
            "VALUES (:a, :b, :rt, 'stated', 0.9, 'visoka', :st) RETURNING id"
        ),
        {"a": a, "b": b, "rt": rel_type, "st": status},
    ).scalar_one()


@pytest.mark.anyio
async def test_graph_confirmed_only(seeded_db: Engine) -> None:
    with seeded_db.connect() as conn:
        ids = conn.execute(text("SELECT id FROM core.customer ORDER BY id LIMIT 3")).scalars().all()
        a, b, c = ids[0], ids[1], ids[2]
        active_id = _edge(conn, a, b, "same_owner", "active")
        proposed_id = _edge(conn, a, c, "referral", "proposed")
        conn.commit()

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        body = (await client.get("/api/kb/graph", params={"customer_id": a})).json()
        rel_types = {e["rel_type"] for e in body["edges"]}
        to_ids = {e["to"] for e in body["edges"]}
        assert "same_owner" in rel_types  # confirmed edge present
        assert b in to_ids
        assert "referral" not in rel_types  # proposed edge excluded
        assert c not in to_ids
    finally:
        await client.aclose()
        with seeded_db.connect() as conn:
            conn.execute(
                text("DELETE FROM app.client_relationship WHERE id = ANY(:ids)"),
                {"ids": [active_id, proposed_id]},
            )
            conn.commit()


@pytest.mark.anyio
async def test_graph_rep_scope_limited(seeded_db: Engine, seed_data) -> None:
    """A rep's graph omits a confirmed edge to a customer outside their scope."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_rep_id = rep_user["sales_rep_id"]

    with seeded_db.connect() as conn:
        owned = conn.execute(
            text("SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid LIMIT 1"),
            {"rid": rep_rep_id},
        ).scalar()
        foreign = conn.execute(
            text(
                "SELECT id FROM core.customer WHERE id NOT IN "
                "(SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid) LIMIT 1"
            ),
            {"rid": rep_rep_id},
        ).scalar()
        edge_id = _edge(conn, owned, foreign, "same_owner", "active")
        conn.commit()

    rep_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        body = (await rep_client.get("/api/kb/graph", params={"customer_id": owned})).json()
        node_ids = {n["customer_id"] for n in body["nodes"]}
        assert foreign not in node_ids  # fail-closed: out-of-scope member omitted
        assert all(e["to"] != foreign and e["from"] != foreign for e in body["edges"])
    finally:
        await rep_client.aclose()
        with seeded_db.connect() as conn:
            conn.execute(
                text("DELETE FROM app.client_relationship WHERE id = :id"), {"id": edge_id}
            )
            conn.commit()
