"""Contract / RBAC / logging tests for describe_capabilities (CSA introspection)."""

from tests.tools.conftest import tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_returns_capabilities_no_numbers(owner_context) -> None:
    result = dispatch(owner_context, "describe_capabilities", {})
    assert result.ok, result.error
    caps = result.output["capabilities"]
    assert caps, "owner should see capabilities"
    # No numeric/business value leaks — each item is name/description/params only.
    for cap in caps:
        assert set(cap) >= {"kind", "name", "description", "params"}
        assert cap["kind"] in ("metric", "tool")
        assert "value" not in cap and "revenue" not in cap
    names = {c["name"] for c in caps}
    assert "top_articles" in names  # the new metric is discoverable


def test_rep_sees_fewer_metrics_than_owner(rep_context, owner_context) -> None:
    rep_out = dispatch(rep_context, "describe_capabilities", {}).output
    rep = {c["name"] for c in rep_out["capabilities"]}
    owner_out = dispatch(owner_context, "describe_capabilities", {}).output
    owner = {c["name"] for c in owner_out["capabilities"]}
    assert "top_articles" in owner and "top_articles" not in rep  # company-wide hidden from rep
    assert rep < owner


def test_every_call_logged(owner_context) -> None:
    session = owner_context.session
    before = len(tool_log_rows(session, "describe_capabilities"))
    dispatch(owner_context, "describe_capabilities", {})
    rows = tool_log_rows(session, "describe_capabilities")
    assert len(rows) == before + 1
    assert rows[-1].ok is True and rows[-1].latency_ms is not None
