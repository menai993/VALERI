"""Tests for the M10/M13 stub tools: stable contract, no side effects, still logged."""

from sqlalchemy import text

from tests.tools.conftest import tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_propose_rule_change_stub(owner_context) -> None:
    """The stub answers 'not available until M10' and mutates nothing."""
    session = owner_context.session
    result = dispatch(
        owner_context, "propose_rule_change", {"reason": "Sezonski kupac, ne treba signal"}
    )
    assert result.ok
    assert result.output["available"] is False
    assert result.output["milestone"] == "M10"

    # No learned rule / decision side effects.
    assert session.execute(text("SELECT COUNT(*) FROM app.learned_rule")).scalar() == 0


def test_start_investigation_stub(owner_context) -> None:
    """The stub answers 'not available until M13' and mutates nothing."""
    result = dispatch(
        owner_context, "start_investigation", {"question": "Zašto pada promet u maju?"}
    )
    assert result.ok
    assert result.output["available"] is False
    assert result.output["milestone"] == "M13"


def test_stub_calls_are_logged(owner_context) -> None:
    """Even no-op stubs leave an audit trail."""
    session = owner_context.session
    before_rule = len(tool_log_rows(session, "propose_rule_change"))
    before_inv = len(tool_log_rows(session, "start_investigation"))

    dispatch(owner_context, "propose_rule_change", {"reason": "test"})
    dispatch(owner_context, "start_investigation", {"question": "test"})

    assert len(tool_log_rows(session, "propose_rule_change")) == before_rule + 1
    assert len(tool_log_rows(session, "start_investigation")) == before_inv + 1


def test_unknown_tool_logged_and_rejected(owner_context) -> None:
    """Dispatching a tool that doesn't exist fails safely and is still logged."""
    session = owner_context.session
    result = dispatch(owner_context, "drop_database", {})
    assert not result.ok
    assert result.error_code == "unknown_tool"

    rows = tool_log_rows(session, "drop_database")
    assert len(rows) == 1
    assert rows[0].ok is False
