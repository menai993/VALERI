"""Contract / RBAC / logging tests for the query_metric tool (TDD, per /tool)."""

import datetime
from decimal import Decimal

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_contract_numbers_equal_sql(owner_context) -> None:
    """Every number the tool returns equals the same SQL run directly (to the cent)."""
    session = owner_context.session
    today = datetime.date.today()
    from_date = today - datetime.timedelta(days=30)

    # Company-wide turnover for the last 30 days.
    result = dispatch(
        owner_context,
        "query_metric",
        {"metric": "turnover", "from_date": str(from_date), "to_date": str(today)},
    )
    assert result.ok, result.error

    sql_value = session.execute(
        text(
            "SELECT COALESCE(SUM(l.line_total), 0) FROM core.invoice_line l "
            "JOIN core.invoice i ON i.id = l.invoice_id "
            "WHERE i.date > :a AND i.date <= :b"
        ),
        {"a": from_date, "b": today},
    ).scalar()
    assert Decimal(str(result.output["value"])) == sql_value

    # Per-customer 60-day turnover from the derived metrics table.
    customer_id = session.execute(
        text("SELECT customer_id FROM core.customer_metrics WHERE turnover_60d > 0 LIMIT 1")
    ).scalar()
    result = dispatch(
        owner_context,
        "query_metric",
        {"metric": "customer_turnover_60d", "customer_id": customer_id},
    )
    assert result.ok, result.error
    sql_value = session.execute(
        text("SELECT turnover_60d FROM core.customer_metrics WHERE customer_id = :id"),
        {"id": customer_id},
    ).scalar()
    assert Decimal(str(result.output["value"])) == sql_value


def test_rbac_rep_blocked_from_company_wide(rep_context) -> None:
    """A rep cannot run company-wide metrics (finance data, D2); own-customer metrics pass."""
    session = rep_context.session
    today = datetime.date.today()

    # Company-wide turnover (no customer scope) → blocked.
    blocked = dispatch(
        rep_context,
        "query_metric",
        {
            "metric": "turnover",
            "from_date": str(today - datetime.timedelta(days=30)),
            "to_date": str(today),
        },
    )
    assert not blocked.ok
    assert blocked.error_code == "forbidden"

    # The rep's own customer → allowed.
    own = rep_customer_ids(session, rep_context.user.sales_rep_id)
    own_customer = sorted(own)[0]
    allowed = dispatch(
        rep_context,
        "query_metric",
        {"metric": "customer_turnover_60d", "customer_id": own_customer},
    )
    assert allowed.ok, allowed.error

    # Another rep's customer → blocked.
    foreign_customer = session.execute(
        text("SELECT id FROM core.customer WHERE NOT (id = ANY(:own)) LIMIT 1"),
        {"own": sorted(own)},
    ).scalar()
    foreign = dispatch(
        rep_context,
        "query_metric",
        {"metric": "customer_turnover_60d", "customer_id": foreign_customer},
    )
    assert not foreign.ok
    assert foreign.error_code == "forbidden"


def test_unknown_metric_rejected(owner_context) -> None:
    """Only registry metrics can run — no free-form SQL ever."""
    result = dispatch(owner_context, "query_metric", {"metric": "drop_tables"})
    assert not result.ok


def test_every_call_logged(owner_context, rep_context) -> None:
    """One tool_call_log row per call — success AND failure."""
    session = owner_context.session
    today = datetime.date.today()

    before = len(tool_log_rows(session, "query_metric"))

    # One success (owner) + one RBAC failure (rep, company-wide) + one bad metric.
    dispatch(
        owner_context,
        "query_metric",
        {
            "metric": "turnover",
            "from_date": str(today - datetime.timedelta(days=7)),
            "to_date": str(today),
        },
    )
    dispatch(
        rep_context,
        "query_metric",
        {
            "metric": "turnover",
            "from_date": str(today - datetime.timedelta(days=7)),
            "to_date": str(today),
        },
    )
    dispatch(owner_context, "query_metric", {"metric": "ne_postoji"})

    rows = tool_log_rows(session, "query_metric")
    assert len(rows) == before + 3
    assert [row.ok for row in rows[-3:]] == [True, False, False]
    assert all(row.latency_ms is not None for row in rows[-3:])
