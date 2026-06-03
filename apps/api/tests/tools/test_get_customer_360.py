"""Contract / RBAC / logging tests for the get_customer_360 tool (TDD, per /tool)."""

from decimal import Decimal

from sqlalchemy import text

from tests.tools.conftest import rep_customer_ids, tool_log_rows
from valeri_api.tools.catalog import dispatch


def test_contract_numbers_equal_sql(owner_context) -> None:
    """The 360 header metrics equal core.customer_metrics (SQL) exactly."""
    session = owner_context.session
    row = session.execute(
        text(
            "SELECT customer_id, turnover_60d, turnover_6m_avg_60d, avg_order_interval_d "
            "FROM core.customer_metrics WHERE turnover_60d > 0 LIMIT 1"
        )
    ).one()

    result = dispatch(owner_context, "get_customer_360", {"customer_id": row.customer_id})
    assert result.ok, result.error
    output = result.output

    assert output["customer_id"] == row.customer_id
    assert Decimal(str(output["turnover_60d"])) == row.turnover_60d
    assert Decimal(str(output["baseline_60d"])) == row.turnover_6m_avg_60d
    assert len(output["monthly_turnover"]) == 12
    assert output["basket"], "an active customer has basket categories"

    # Spot-check one monthly value against SQL.
    last_month = output["monthly_turnover"][-1]
    sql_month = session.execute(
        text(
            "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
            "WHERE customer_id = :id AND to_char(date, 'YYYY-MM') = :month"
        ),
        {"id": row.customer_id, "month": last_month["month"]},
    ).scalar()
    assert Decimal(str(last_month["revenue"])) == sql_month


def test_unknown_customer(owner_context) -> None:
    result = dispatch(owner_context, "get_customer_360", {"customer_id": 99999999})
    assert not result.ok


def test_rbac_rep_scope(rep_context) -> None:
    """A rep can load their own customer's 360 but not a foreign one."""
    session = rep_context.session
    own = rep_customer_ids(session, rep_context.user.sales_rep_id)

    own_customer = sorted(own)[0]
    allowed = dispatch(rep_context, "get_customer_360", {"customer_id": own_customer})
    assert allowed.ok, allowed.error

    foreign_customer = session.execute(
        text("SELECT id FROM core.customer WHERE NOT (id = ANY(:own)) LIMIT 1"),
        {"own": sorted(own)},
    ).scalar()
    blocked = dispatch(rep_context, "get_customer_360", {"customer_id": foreign_customer})
    assert not blocked.ok
    assert blocked.error_code == "forbidden"


def test_every_call_logged(owner_context, rep_context) -> None:
    session = owner_context.session
    customer_id = session.execute(
        text("SELECT customer_id FROM core.customer_metrics LIMIT 1")
    ).scalar()

    before = len(tool_log_rows(session, "get_customer_360"))
    dispatch(owner_context, "get_customer_360", {"customer_id": customer_id})
    dispatch(owner_context, "get_customer_360", {"customer_id": 99999999})  # not found
    rows = tool_log_rows(session, "get_customer_360")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
