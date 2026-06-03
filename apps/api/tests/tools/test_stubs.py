"""Tests for the M13 stub tool: stable contract, no side effects, still logged.

propose_rule_change graduated to a real tool in M10 — its tests live in
tests/tools/test_propose_rule_change.py.
"""

from tests.tools.conftest import tool_log_rows
from valeri_api.tools.catalog import dispatch


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
    before_inv = len(tool_log_rows(session, "start_investigation"))

    dispatch(owner_context, "start_investigation", {"question": "test"})

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
