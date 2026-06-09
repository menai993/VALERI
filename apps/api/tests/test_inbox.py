"""P1 inbox summary: every count equals independent SQL; RBAC-aware per role.

The bell badge is a pure SQL aggregate (principle 1 — no LLM, no client math
beyond the server-provided total). Control rows are inserted directly and
cleaned up so the shared seed stays pristine.
"""

import datetime

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import FINANCE_EMAIL, OWNER_EMAIL


@pytest.fixture()
def inbox_rows(seeded_db: Engine, seed_data):
    """Plant 2 pending approvals, 1 pending clarification, 1 proposed fact,
    and 2 tasks due today (one per rep) — yields ids for cleanup."""
    rep_users = [u for u in seed_data.app_users if u["role"] == "sales_rep"]
    rep_a, rep_b = rep_users[0], rep_users[1]
    today = datetime.date.today()

    with seeded_db.connect() as conn:
        approval_ids = [
            conn.execute(
                text(
                    "INSERT INTO app.approval (kind, status, payload) "
                    "VALUES ('message', 'pending_approval', '{}') RETURNING id"
                )
            ).scalar_one()
            for _ in range(2)
        ]
        clar_id = conn.execute(
            text(
                "INSERT INTO app.clarification (kind, question, options, target_record_ref) "
                "VALUES ('entity', 'test?', '[]', 'mention:InboxTest') RETURNING id"
            )
        ).scalar_one()
        # One proposed fact INSIDE rep_a's scope, one OUTSIDE it (RBAC count scoping).
        in_scope = conn.execute(
            text("SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid LIMIT 1"),
            {"rid": rep_a["sales_rep_id"]},
        ).scalar_one()
        out_scope = conn.execute(
            text(
                "SELECT id FROM core.customer WHERE id NOT IN "
                "(SELECT customer_id FROM core.customer_rep WHERE sales_rep_id = :rid) LIMIT 1"
            ),
            {"rid": rep_a["sales_rep_id"]},
        ).scalar_one()
        fact_ids = [
            conn.execute(
                text(
                    "INSERT INTO app.client_fact "
                    "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, "
                    "status) VALUES (:cid, 'preference', :key, '{}', 'stated', 0.8, 'visoka', "
                    "'proposed') RETURNING id"
                ),
                {"cid": cid, "key": f"inbox_test_{cid}"},
            ).scalar_one()
            for cid in (in_scope, out_scope)
        ]
        task_ids = [
            conn.execute(
                text(
                    "INSERT INTO app.task (assignee_id, title, status, due_date) "
                    "VALUES (:rep, :title, 'open', :due) RETURNING id"
                ),
                {"rep": rep["sales_rep_id"], "title": f"Inbox test {rep['email']}", "due": today},
            ).scalar_one()
            for rep in (rep_a, rep_b)
        ]
        conn.commit()

    yield {"rep_a": rep_a, "rep_b": rep_b, "in_scope": in_scope, "out_scope": out_scope}

    with seeded_db.connect() as conn:
        conn.execute(text("DELETE FROM app.task WHERE id = ANY(:ids)"), {"ids": task_ids})
        conn.execute(text("DELETE FROM app.client_fact WHERE id = ANY(:ids)"), {"ids": fact_ids})
        conn.execute(text("DELETE FROM app.clarification WHERE id = :id"), {"id": clar_id})
        conn.execute(text("DELETE FROM app.approval WHERE id = ANY(:ids)"), {"ids": approval_ids})
        conn.commit()


def _sql_counts(engine: Engine, rep_id: int | None) -> dict:
    """The independent SQL the summary must equal."""
    with engine.connect() as conn:
        approvals = conn.execute(
            text("SELECT count(*) FROM app.approval WHERE status = 'pending_approval'")
        ).scalar_one()
        clars = conn.execute(
            text("SELECT count(*) FROM app.clarification WHERE status = 'pending'")
        ).scalar_one()
        proposed = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM app.client_fact WHERE status='proposed')"
                " + (SELECT count(*) FROM app.commercial_event WHERE status='proposed')"
                " + (SELECT count(*) FROM app.client_relationship WHERE status='proposed')"
            )
        ).scalar_one()
        task_filter = "" if rep_id is None else " AND assignee_id = :rep"
        due = conn.execute(
            text(
                "SELECT count(*) FROM app.task WHERE status IN ('open', 'in_progress') "
                "AND due_date <= CURRENT_DATE" + task_filter
            ),
            ({} if rep_id is None else {"rep": rep_id}),
        ).scalar_one()
    return {"approvals": approvals, "clars": clars, "proposed": proposed, "due": due}


@pytest.mark.anyio
async def test_summary_counts_match_sql_for_owner(seeded_db: Engine, inbox_rows) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        body = (await client.get("/api/inbox/summary")).json()
        sql = _sql_counts(seeded_db, rep_id=None)

        assert body["pending_approvals"] == sql["approvals"] >= 2
        assert body["pending_clarifications"] == sql["clars"] >= 1
        assert body["proposed_kb_items"] == sql["proposed"] >= 1
        assert body["tasks_due_today"] == sql["due"] >= 2
        # P2: alerts are derived ops conditions (owner/admin only).
        from sqlalchemy.orm import Session as _S

        from valeri_api.ops.runs import derive_alerts

        with _S(seeded_db) as _session:
            expected_alerts = len(derive_alerts(_session))
        assert body["alerts"] == expected_alerts
        assert body["total"] == (
            body["pending_approvals"]
            + body["pending_clarifications"]
            + body["proposed_kb_items"]
            + body["tasks_due_today"]
            + body["alerts"]
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_summary_rbac_rep_and_finance(seeded_db: Engine, inbox_rows) -> None:
    """A rep sees approvals=0 and only THEIR due tasks; finance sees approvals=0, tasks=0."""
    rep_a = inbox_rows["rep_a"]
    rep_client = make_client()
    finance_client = make_client()
    try:
        await login(rep_client, rep_a["email"])
        rep_body = (await rep_client.get("/api/inbox/summary")).json()
        rep_sql = _sql_counts(seeded_db, rep_id=rep_a["sales_rep_id"])
        assert rep_body["pending_approvals"] == 0  # not an approver
        assert rep_body["tasks_due_today"] == rep_sql["due"] >= 1  # own tasks only

        # Proposed KB counts are scoped like /kb/pending: the out-of-scope fact
        # is invisible to the rep (counts must match the queue they open).
        with seeded_db.connect() as conn:
            rep_proposed = conn.execute(
                text(
                    "SELECT (SELECT count(*) FROM app.client_fact WHERE status='proposed' "
                    "        AND (customer_id IS NULL OR customer_id IN "
                    "             (SELECT customer_id FROM core.customer_rep "
                    "              WHERE sales_rep_id = :rid)))"
                    " + (SELECT count(*) FROM app.commercial_event WHERE status='proposed' "
                    "        AND (customer_id IS NULL OR customer_id IN "
                    "             (SELECT customer_id FROM core.customer_rep "
                    "              WHERE sales_rep_id = :rid)))"
                    " + (SELECT count(*) FROM app.client_relationship WHERE status='proposed' "
                    "        AND (from_customer_id IN (SELECT customer_id FROM core.customer_rep "
                    "                                  WHERE sales_rep_id = :rid) "
                    "          OR to_customer_id IN (SELECT customer_id FROM core.customer_rep "
                    "                                WHERE sales_rep_id = :rid)))"
                ),
                {"rid": rep_a["sales_rep_id"]},
            ).scalar_one()
        assert rep_body["proposed_kb_items"] == rep_proposed
        # The owner's global count includes the out-of-scope fact the rep can't see.
        owner_sql = _sql_counts(seeded_db, rep_id=None)
        assert owner_sql["proposed"] > rep_proposed

        assert rep_body["alerts"] == 0  # ops alerts are an owner/admin concern (D1)

        await login(finance_client, FINANCE_EMAIL)
        fin_body = (await finance_client.get("/api/inbox/summary")).json()
        assert fin_body["pending_approvals"] == 0
        assert fin_body["tasks_due_today"] == 0  # finance has no task queue
        assert fin_body["alerts"] == 0
    finally:
        await rep_client.aclose()
        await finance_client.aclose()


@pytest.mark.anyio
async def test_summary_requires_auth(seeded_db: Engine) -> None:
    client = make_client()
    try:
        assert (await client.get("/api/inbox/summary")).status_code == 401
    finally:
        await client.aclose()
