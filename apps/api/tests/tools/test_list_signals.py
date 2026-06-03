"""Contract / RBAC / logging tests for the list_signals tool (TDD, per /tool)."""

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_contract_rows_match_sql(owner_context) -> None:
    """The tool returns exactly the open signals SQL returns, with full envelopes."""
    session = owner_context.session
    result = dispatch(owner_context, "list_signals", {"limit": 200})
    assert result.ok, result.error
    items = result.output["items"]
    assert items, "the planted cases must produce signals"

    sql_ids = {
        row[0]
        for row in session.execute(
            text("SELECT id FROM app.signal WHERE status IN ('new', 'tasked')")
        )
    }
    assert {item["signal_id"] for item in items} == sql_ids

    # Every row carries the envelope, with values equal to the signal row.
    for item in items[:5]:
        signal = session.execute(
            text(
                "SELECT rule, confidence, conf_band, register, evidence "
                "FROM app.signal WHERE id = :id"
            ),
            {"id": item["signal_id"]},
        ).one()
        assert item["rule"] == signal.rule
        assert str(item["confidence"]) == str(signal.confidence)
        assert item["conf_band"] == signal.conf_band
        assert item["register"] == signal.register
        assert item["evidence"] == signal.evidence


def test_contract_rule_filter(owner_context) -> None:
    """The rule filter matches SQL."""
    session = owner_context.session
    result = dispatch(owner_context, "list_signals", {"rule": "customer_decline", "limit": 200})
    assert result.ok
    sql_count = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal "
            "WHERE rule = 'customer_decline' AND status IN ('new', 'tasked')"
        )
    ).scalar()
    assert len(result.output["items"]) == sql_count


def test_rbac_rep_sees_only_own(rep_context) -> None:
    """A rep's list contains only their own customers' signals."""
    session = rep_context.session
    own = rep_customer_ids(session, rep_context.user.sales_rep_id)

    result = dispatch(rep_context, "list_signals", {"limit": 200})
    assert result.ok, result.error
    returned_customers = {
        item["customer_id"] for item in result.output["items"] if item["customer_id"]
    }
    assert returned_customers <= own


def test_every_call_logged(owner_context) -> None:
    before = len(tool_log_rows(owner_context.session, "list_signals"))
    dispatch(owner_context, "list_signals", {})
    dispatch(owner_context, "list_signals", {"limit": "nije broj"})  # validation failure
    rows = tool_log_rows(owner_context.session, "list_signals")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
