"""P1: manual tasks (POST /tasks), the due filter/sort, and customer fields on rows.

Manual tasks are USER data (signal_id NULL, no AI envelope) and still hit the
append-only task_log; the due filter is pure SQL; AI-task rows carry the
customer joined via their signal.
"""

import datetime

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import FINANCE_EMAIL, OWNER_EMAIL


def _cleanup_tasks(engine: Engine, task_ids: list[int]) -> None:
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM audit.task_log WHERE task_id = ANY(:ids)"), {"ids": task_ids}
        )
        conn.execute(text("DELETE FROM app.task WHERE id = ANY(:ids)"), {"ids": task_ids})
        conn.commit()


# ── POST /tasks (manual) ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_manual_task_created_with_task_log(seeded_db: Engine, seed_data) -> None:
    rep = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    client = make_client()
    created_ids: list[int] = []
    try:
        await login(client, OWNER_EMAIL)
        response = await client.post(
            "/api/tasks",
            json={
                "title": "Ručni zadatak — nazvati kupca",
                "body": "Dogovoriti termin obilaska.",
                "assignee_id": rep["sales_rep_id"],
                "due_date": datetime.date.today().isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        task = response.json()
        created_ids.append(task["id"])

        assert task["signal_id"] is None  # manual: not AI output
        assert task["rule"] is None and task["confidence"] is None  # no AI envelope
        assert task["assignee_id"] == rep["sales_rep_id"]

        with seeded_db.connect() as conn:
            events = (
                conn.execute(
                    text("SELECT event FROM audit.task_log WHERE task_id = :id"),
                    {"id": task["id"]},
                )
                .scalars()
                .all()
            )
        assert "created" in events  # append-only lifecycle starts at creation
    finally:
        await client.aclose()
        _cleanup_tasks(seeded_db, created_ids)


@pytest.mark.anyio
async def test_manual_task_rbac(seeded_db: Engine, seed_data) -> None:
    """A rep is forced to self-assign; finance may not create tasks at all."""
    rep_users = [u for u in seed_data.app_users if u["role"] == "sales_rep"]
    rep, other = rep_users[0], rep_users[1]
    rep_client = make_client()
    finance_client = make_client()
    created_ids: list[int] = []
    try:
        await login(rep_client, rep["email"])
        spoofed = await rep_client.post(
            "/api/tasks",
            json={"title": "Pokušaj tuđeg zadatka", "assignee_id": other["sales_rep_id"]},
        )
        assert spoofed.status_code == 201
        task = spoofed.json()
        created_ids.append(task["id"])
        assert task["assignee_id"] == rep["sales_rep_id"]  # forced onto self

        await login(finance_client, FINANCE_EMAIL)
        forbidden = await finance_client.post(
            "/api/tasks", json={"title": "Finance ne smije", "assignee_id": rep["sales_rep_id"]}
        )
        assert forbidden.status_code == 403
    finally:
        await rep_client.aclose()
        await finance_client.aclose()
        _cleanup_tasks(seeded_db, created_ids)


# ── due filter + customer fields ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_due_filter_and_sort(seeded_db: Engine, seed_data) -> None:
    """due=today / due=overdue rows equal SQL; results are due-date ordered."""
    rep = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    today = datetime.date.today()
    created_ids: list[int] = []
    with seeded_db.connect() as conn:
        for title, due in (
            ("P1 overdue", today - datetime.timedelta(days=3)),
            ("P1 today", today),
            ("P1 future", today + datetime.timedelta(days=5)),
        ):
            created_ids.append(
                conn.execute(
                    text(
                        "INSERT INTO app.task (assignee_id, title, status, due_date) "
                        "VALUES (:rep, :t, 'open', :d) RETURNING id"
                    ),
                    {"rep": rep["sales_rep_id"], "t": title, "d": due},
                ).scalar_one()
            )
        conn.commit()

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)

        due_today = (await client.get("/api/tasks", params={"due": "today"})).json()["items"]
        with seeded_db.connect() as conn:
            sql_today = conn.execute(
                text(
                    "SELECT count(*) FROM app.task WHERE status IN ('open','in_progress') "
                    "AND due_date <= CURRENT_DATE"
                )
            ).scalar_one()
        assert len(due_today) == sql_today
        titles = [t["title"] for t in due_today]
        assert "P1 overdue" in titles and "P1 today" in titles and "P1 future" not in titles
        # due-date ordered: the overdue task comes before today's.
        assert titles.index("P1 overdue") < titles.index("P1 today")

        overdue = (await client.get("/api/tasks", params={"due": "overdue"})).json()["items"]
        overdue_titles = [t["title"] for t in overdue]
        assert "P1 overdue" in overdue_titles and "P1 today" not in overdue_titles

        bad = await client.get("/api/tasks", params={"due": "yesterday"})
        assert bad.status_code == 422
    finally:
        await client.aclose()
        _cleanup_tasks(seeded_db, created_ids)


@pytest.mark.anyio
async def test_task_rows_carry_customer_via_signal(seeded_db: Engine) -> None:
    """An AI task exposes customer_id/customer_name from its signal; manual rows are NULL-safe."""
    with seeded_db.connect() as conn:
        customer = conn.execute(
            text("SELECT id, name FROM core.customer ORDER BY id LIMIT 1")
        ).one()
        signal_id = conn.execute(
            text(
                "INSERT INTO app.signal (rule, customer_id, evidence, confidence, conf_band, "
                "status) VALUES ('customer_decline', :cid, '{}', 0.8, 'visoka', 'tasked') "
                "RETURNING id"
            ),
            {"cid": customer.id},
        ).scalar_one()
        task_id = conn.execute(
            text(
                "INSERT INTO app.task (signal_id, title, status) "
                "VALUES (:sid, 'P1 kupac join', 'open') RETURNING id"
            ),
            {"sid": signal_id},
        ).scalar_one()
        conn.commit()

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        task = (await client.get(f"/api/tasks/{task_id}")).json()
        assert task["customer_id"] == customer.id
        assert task["customer_name"] == customer.name
    finally:
        await client.aclose()
        with seeded_db.connect() as conn:
            conn.execute(text("DELETE FROM audit.task_log WHERE task_id = :id"), {"id": task_id})
            conn.execute(text("DELETE FROM app.task WHERE id = :id"), {"id": task_id})
            conn.execute(text("DELETE FROM app.signal WHERE id = :id"), {"id": signal_id})
            conn.commit()
