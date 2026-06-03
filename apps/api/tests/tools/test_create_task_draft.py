"""Contract / RBAC / logging / decision tests for create_task_draft (TDD, per /tool).

This is the catalog's only mutation in M9: it must create the task, append the
task_log lifecycle events, AND write a reversible app.decision (the /tool
mutation contract).
"""

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_mutation_creates_task_log_and_decision(owner_context) -> None:
    """Task + task_log('created') + reversible decision, assignee = customer's rep (SQL)."""
    session = owner_context.session
    customer_id = session.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()

    result = dispatch(
        owner_context,
        "create_task_draft",
        {
            "customer_id": customer_id,
            "title": "Nazvati kupca radi nove ponude",
            "body": "Dogovoriti sastanak sljedeće sedmice.",
        },
    )
    assert result.ok, result.error
    task_id = result.output["task_id"]

    # The task exists with the correct assignee (the customer's current rep, from SQL).
    task = session.execute(
        text("SELECT title, assignee_id, status, register FROM app.task WHERE id = :id"),
        {"id": task_id},
    ).one()
    expected_rep = session.execute(
        text(
            "SELECT sales_rep_id FROM ("
            "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id"
            "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
            ") cur WHERE customer_id = :id"
        ),
        {"id": customer_id},
    ).scalar()
    assert task.title == "Nazvati kupca radi nove ponude"
    assert task.assignee_id == expected_rep
    assert task.status == "open"
    assert task.register == "akcija"  # a user-requested action, visible as such

    # task_log lifecycle events exist.
    events = [
        row[0]
        for row in session.execute(
            text("SELECT event FROM audit.task_log WHERE task_id = :id ORDER BY id"),
            {"id": task_id},
        )
    ]
    assert "created" in events

    # The reversible decision was written (the /tool mutation contract).
    decision = session.execute(
        text(
            "SELECT kind, actor, reversible, payload FROM app.decision " "ORDER BY id DESC LIMIT 1"
        )
    ).one()
    assert decision.actor == "user"
    assert decision.reversible is True
    assert decision.payload["task_id"] == task_id


def test_rbac_rep_own_customer_only(rep_context) -> None:
    """A rep can create tasks for their own customers only; finance has no access."""
    session = rep_context.session
    own = rep_customer_ids(session, rep_context.user.sales_rep_id)

    own_customer = sorted(own)[0]
    allowed = dispatch(
        rep_context,
        "create_task_draft",
        {"customer_id": own_customer, "title": "Provjeriti zadnju narudžbu kupca"},
    )
    assert allowed.ok, allowed.error

    foreign_customer = session.execute(
        text("SELECT id FROM core.customer WHERE NOT (id = ANY(:own)) LIMIT 1"),
        {"own": sorted(own)},
    ).scalar()
    blocked = dispatch(
        rep_context,
        "create_task_draft",
        {"customer_id": foreign_customer, "title": "Ne bi smjelo proći"},
    )
    assert not blocked.ok
    assert blocked.error_code == "forbidden"


def test_rbac_finance_blocked(finance_context) -> None:
    """Finance does not manage tasks — the role gate rejects before anything runs."""
    session = finance_context.session
    customer_id = session.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()

    result = dispatch(
        finance_context,
        "create_task_draft",
        {"customer_id": customer_id, "title": "Finansije ne kreiraju zadatke"},
    )
    assert not result.ok
    assert result.error_code == "forbidden"

    # Nothing was created.
    count = session.execute(
        text("SELECT COUNT(*) FROM app.task WHERE title = 'Finansije ne kreiraju zadatke'")
    ).scalar()
    assert count == 0


def test_every_call_logged(owner_context, finance_context) -> None:
    session = owner_context.session
    customer_id = session.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()

    before = len(tool_log_rows(session, "create_task_draft"))
    dispatch(
        owner_context,
        "create_task_draft",
        {"customer_id": customer_id, "title": "Logovani zadatak"},
    )
    dispatch(
        finance_context, "create_task_draft", {"customer_id": customer_id, "title": "Odbijeno"}
    )
    rows = tool_log_rows(session, "create_task_draft")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
