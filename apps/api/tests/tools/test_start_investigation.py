"""Contract / RBAC / logging tests for start_investigation (M13, replaces the stub).

The tool queues a real app.investigation (the worker runs it later); nothing
executes inline, nothing external happens. The unknown-tool dispatch test lives
here too (moved from the deleted test_stubs.py).
"""

from sqlalchemy import text

from tests.tools.conftest import tool_log_rows
from valeri_api.tools.catalog import dispatch

QUESTION = "Zašto pada promet u hotelskom segmentu zadnja tri mjeseca?"


def test_creates_queued_investigation(owner_context) -> None:
    """The tool creates a queued investigation linked to the asking user."""
    session = owner_context.session

    result = dispatch(owner_context, "start_investigation", {"question": QUESTION})
    assert result.ok, result.error
    assert result.output["status"] == "queued"
    assert result.output["register"] == "analiza"
    investigation_id = result.output["investigation_id"]

    row = session.execute(
        text(
            "SELECT question, status, trigger, created_by, thread_id "
            "FROM app.investigation WHERE id = :id"
        ),
        {"id": investigation_id},
    ).one()
    assert row.question == QUESTION
    assert row.status == "queued"
    assert row.trigger == "user"
    assert row.created_by == owner_context.user.id
    assert row.thread_id  # the LangGraph checkpoint thread is assigned at creation


def test_links_to_signal_when_given(owner_context) -> None:
    """'Istraži' on a signal carries the signal_id through to the investigation."""
    session = owner_context.session
    signal_id = session.execute(text("SELECT id FROM app.signal ORDER BY id LIMIT 1")).scalar()

    result = dispatch(
        owner_context,
        "start_investigation",
        {"question": QUESTION, "signal_id": signal_id},
    )
    assert result.ok, result.error

    linked = session.execute(
        text("SELECT signal_id FROM app.investigation WHERE id = :id"),
        {"id": result.output["investigation_id"]},
    ).scalar()
    assert linked == signal_id


def test_rbac_owner_admin_only(rep_context, finance_context) -> None:
    """Investigations are owner-level analysis: reps and finance are refused."""
    for context in (rep_context, finance_context):
        result = dispatch(context, "start_investigation", {"question": QUESTION})
        assert not result.ok
        assert result.error_code == "forbidden"

    # Nothing was created by the denied calls.
    count = rep_context.session.execute(text("SELECT COUNT(*) FROM app.investigation")).scalar()
    assert count == 0


def test_every_call_logged(owner_context, finance_context) -> None:
    """Success and denial both land in tool_call_log (the audit trail is total)."""
    session = owner_context.session
    before = len(tool_log_rows(session, "start_investigation"))

    dispatch(owner_context, "start_investigation", {"question": QUESTION})
    dispatch(finance_context, "start_investigation", {"question": QUESTION})

    rows = tool_log_rows(session, "start_investigation")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]


def test_unknown_tool_logged_and_rejected(owner_context) -> None:
    """Dispatching a tool that doesn't exist fails safely and is still logged."""
    session = owner_context.session
    result = dispatch(owner_context, "drop_database", {})
    assert not result.ok
    assert result.error_code == "unknown_tool"

    rows = tool_log_rows(session, "drop_database")
    assert len(rows) == 1
    assert rows[0].ok is False
