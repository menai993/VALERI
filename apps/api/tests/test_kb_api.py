"""CI1 HTTP surface + RBAC (per docs/client-intelligence.md §5).

Capture is open to authenticated users; the knowledge panel is row-scoped to a
rep's own customers; mutations exclude finance (read-only). The capture pipeline
itself is tested with fakes in test_kb_capture.py — here we assert auth/RBAC and
the response envelopes.
"""

import json

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import FINANCE_EMAIL, OWNER_EMAIL


@pytest.mark.anyio
async def test_capture_requires_auth(seeded_db: Engine) -> None:
    client = make_client()
    try:
        # Narration is off in tests, so capture gates out → empty but 200 for an authed user.
        unauth = await client.post("/api/kb/capture", json={"text": "test"})
        assert unauth.status_code == 401
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_capture_returns_envelope(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.post("/api/kb/capture", json={"text": "Pozdrav!"})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"auto_saved", "proposed", "clarifications"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_pending_queue_endpoint(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/kb/pending")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"facts", "events", "relationships", "clarifications"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_knowledge_rbac(seeded_db: Engine, seed_data) -> None:
    """A rep is blocked from a customer outside their scope; the owner sees it."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_rep_id = rep_user["sales_rep_id"]

    with seeded_db.connect() as conn:
        owned = conn.execute(
            text(
                "SELECT cr.customer_id FROM core.customer_rep cr "
                "WHERE cr.sales_rep_id = :rid LIMIT 1"
            ),
            {"rid": rep_rep_id},
        ).scalar()
        other = conn.execute(
            text(
                "SELECT c.id FROM core.customer c WHERE c.id NOT IN "
                "(SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid) LIMIT 1"
            ),
            {"rid": rep_rep_id},
        ).scalar()

    rep_client = make_client()
    owner_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        await login(owner_client, OWNER_EMAIL)

        # Rep: own customer ok, foreign customer forbidden.
        assert (await rep_client.get(f"/api/customers/{owned}/knowledge")).status_code == 200
        assert (await rep_client.get(f"/api/customers/{other}/knowledge")).status_code == 403

        # Owner: any customer.
        owner_resp = await owner_client.get(f"/api/customers/{other}/knowledge")
        assert owner_resp.status_code == 200
        assert set(owner_resp.json()) == {"profile", "facts", "events", "relationships"}
    finally:
        await rep_client.aclose()
        await owner_client.aclose()


@pytest.mark.anyio
async def test_rep_cannot_link_clarification_out_of_scope(seeded_db: Engine, seed_data) -> None:
    """A rep answering a clarification cannot link a record onto a foreign customer."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_rep_id = rep_user["sales_rep_id"]

    with seeded_db.connect() as conn:
        foreign = conn.execute(
            text(
                "SELECT c.id FROM core.customer c WHERE c.id NOT IN "
                "(SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid) LIMIT 1"
            ),
            {"rid": rep_rep_id},
        ).scalar()
        opts = json.dumps([{"label": "link", "action": "link", "customer_id": foreign}])
        clar_id = conn.execute(
            text(
                "INSERT INTO app.clarification (kind, question, options, target_record_ref) "
                "VALUES ('entity', 'test?', CAST(:opts AS jsonb), 'mention:Nepoznati') RETURNING id"
            ),
            {"opts": opts},
        ).scalar()
        conn.commit()

    rep_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        resp = await rep_client.post(
            f"/api/kb/clarifications/{clar_id}/answer",
            json={"option": {"action": "link", "customer_id": foreign}},
        )
        assert resp.status_code == 403
    finally:
        await rep_client.aclose()
        with seeded_db.connect() as conn:
            conn.execute(text("DELETE FROM app.clarification WHERE id = :id"), {"id": clar_id})
            conn.commit()


@pytest.mark.anyio
async def test_finance_cannot_mutate(seeded_db: Engine) -> None:
    """Finance is read-only: confirm/reject/edit/answer are forbidden."""
    client = make_client()
    try:
        await login(client, FINANCE_EMAIL)
        confirm = await client.post("/api/kb/items/1/confirm", params={"item_type": "fact"})
        assert confirm.status_code == 403
        answer = await client.post(
            "/api/kb/clarifications/1/answer", json={"option": {"action": "pick_other"}}
        )
        assert answer.status_code == 403
    finally:
        await client.aclose()
