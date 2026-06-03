"""Contract / RBAC / logging tests for the explain_signal tool (TDD, per /tool)."""

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_contract_evidence_matches_sql(owner_context) -> None:
    """The explained signal carries exactly the SQL evidence + its task + customer."""
    session = owner_context.session
    signal = session.execute(
        text(
            "SELECT s.id, s.rule, s.evidence, s.confidence, s.conf_band, s.customer_id, "
            "       c.name AS customer_name, t.id AS task_id, t.title AS task_title "
            "FROM app.signal s "
            "JOIN core.customer c ON c.id = s.customer_id "
            "LEFT JOIN app.task t ON t.signal_id = s.id "
            "WHERE s.rule = 'customer_decline' LIMIT 1"
        )
    ).one()

    result = dispatch(owner_context, "explain_signal", {"signal_id": signal.id})
    assert result.ok, result.error
    output = result.output

    assert output["signal_id"] == signal.id
    assert output["rule"] == signal.rule
    assert output["evidence"] == signal.evidence  # verbatim SQL evidence, never rewritten
    assert str(output["confidence"]) == str(signal.confidence)
    assert output["conf_band"] == signal.conf_band
    assert output["customer_name"] == signal.customer_name
    assert output["task_id"] == signal.task_id
    assert output["task_title"] == signal.task_title


def test_unknown_signal(owner_context) -> None:
    result = dispatch(owner_context, "explain_signal", {"signal_id": 99999999})
    assert not result.ok


def test_rbac_rep_blocked_from_foreign_signal(rep_context) -> None:
    """A rep cannot explain another rep's customer's signal."""
    session = rep_context.session
    own = rep_customer_ids(session, rep_context.user.sales_rep_id)

    foreign_signal = session.execute(
        text("SELECT id FROM app.signal WHERE NOT (customer_id = ANY(:own)) LIMIT 1"),
        {"own": sorted(own)},
    ).scalar()
    assert foreign_signal is not None, "other reps' customers must have signals too"

    result = dispatch(rep_context, "explain_signal", {"signal_id": foreign_signal})
    assert not result.ok
    assert result.error_code == "forbidden"

    # An own signal works (if any exists for this rep).
    own_signal = session.execute(
        text("SELECT id FROM app.signal WHERE customer_id = ANY(:own) LIMIT 1"),
        {"own": sorted(own)},
    ).scalar()
    if own_signal is not None:
        allowed = dispatch(rep_context, "explain_signal", {"signal_id": own_signal})
        assert allowed.ok, allowed.error


def test_every_call_logged(owner_context, rep_context) -> None:
    session = owner_context.session
    signal_id = session.execute(text("SELECT id FROM app.signal LIMIT 1")).scalar()

    before = len(tool_log_rows(session, "explain_signal"))
    dispatch(owner_context, "explain_signal", {"signal_id": signal_id})
    dispatch(owner_context, "explain_signal", {"signal_id": 99999999})  # not found
    rows = tool_log_rows(session, "explain_signal")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
