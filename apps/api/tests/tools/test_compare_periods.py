"""Contract / RBAC / logging tests for the compare_periods tool (TDD, per /tool)."""

import datetime
from decimal import Decimal

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def _sql_turnover(session, from_date, to_date, customer_id=None) -> Decimal:
    return session.execute(
        text(
            "SELECT COALESCE(SUM(l.line_total), 0) FROM core.invoice_line l "
            "JOIN core.invoice i ON i.id = l.invoice_id "
            "WHERE i.date > :a AND i.date <= :b "
            "AND (CAST(:c AS bigint) IS NULL OR i.customer_id = :c)"
        ),
        {"a": from_date, "b": to_date, "c": customer_id},
    ).scalar()


def test_contract_numbers_equal_sql(owner_context) -> None:
    """Both period totals AND the delta equal direct SQL (the delta is SQL-computed)."""
    session = owner_context.session
    today = datetime.date.today()
    result = dispatch(
        owner_context,
        "compare_periods",
        {
            "period_a_from": str(today - datetime.timedelta(days=30)),
            "period_a_to": str(today),
            "period_b_from": str(today - datetime.timedelta(days=60)),
            "period_b_to": str(today - datetime.timedelta(days=30)),
        },
    )
    assert result.ok, result.error

    sql_a = _sql_turnover(session, today - datetime.timedelta(days=30), today)
    sql_b = _sql_turnover(
        session, today - datetime.timedelta(days=60), today - datetime.timedelta(days=30)
    )
    assert Decimal(str(result.output["period_a"]["value"])) == sql_a
    assert Decimal(str(result.output["period_b"]["value"])) == sql_b

    # The delta itself must equal the SQL-computed delta (never recomputed in Python).
    sql_delta = session.execute(
        text("SELECT CASE WHEN :b > 0 THEN ROUND((CAST(:a AS numeric) / :b - 1) * 100, 1) END"),
        {"a": sql_a, "b": sql_b},
    ).scalar()
    if sql_delta is None:
        assert result.output["delta_pct"] is None
    else:
        assert Decimal(str(result.output["delta_pct"])) == sql_delta


def test_contract_per_customer(owner_context) -> None:
    """Per-customer comparison numbers equal SQL."""
    session = owner_context.session
    today = datetime.date.today()
    customer_id = session.execute(
        text("SELECT customer_id FROM core.customer_metrics WHERE turnover_60d > 0 LIMIT 1")
    ).scalar()

    result = dispatch(
        owner_context,
        "compare_periods",
        {
            "customer_id": customer_id,
            "period_a_from": str(today - datetime.timedelta(days=60)),
            "period_a_to": str(today),
            "period_b_from": str(today - datetime.timedelta(days=120)),
            "period_b_to": str(today - datetime.timedelta(days=60)),
        },
    )
    assert result.ok, result.error
    sql_a = _sql_turnover(session, today - datetime.timedelta(days=60), today, customer_id)
    assert Decimal(str(result.output["period_a"]["value"])) == sql_a


def test_rbac_rep_blocked_company_wide_allowed_own(rep_context) -> None:
    """Reps: company-wide comparison blocked (D2); own customer allowed."""
    session = rep_context.session
    today = datetime.date.today()
    base_params = {
        "period_a_from": str(today - datetime.timedelta(days=30)),
        "period_a_to": str(today),
        "period_b_from": str(today - datetime.timedelta(days=60)),
        "period_b_to": str(today - datetime.timedelta(days=30)),
    }

    blocked = dispatch(rep_context, "compare_periods", base_params)
    assert not blocked.ok
    assert blocked.error_code == "forbidden"

    own_customer = sorted(rep_customer_ids(session, rep_context.user.sales_rep_id))[0]
    allowed = dispatch(rep_context, "compare_periods", {**base_params, "customer_id": own_customer})
    assert allowed.ok, allowed.error


def test_every_call_logged(owner_context, rep_context) -> None:
    """Success and RBAC-denied calls both land in tool_call_log."""
    session = owner_context.session
    today = datetime.date.today()
    params = {
        "period_a_from": str(today - datetime.timedelta(days=7)),
        "period_a_to": str(today),
        "period_b_from": str(today - datetime.timedelta(days=14)),
        "period_b_to": str(today - datetime.timedelta(days=7)),
    }

    before = len(tool_log_rows(session, "compare_periods"))
    dispatch(owner_context, "compare_periods", params)
    dispatch(rep_context, "compare_periods", params)  # blocked

    rows = tool_log_rows(session, "compare_periods")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
