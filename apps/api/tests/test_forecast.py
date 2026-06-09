"""C-CRM2 acceptance: revenue-vs-plan + the run-rate forecast (TDD).

These are numbers — every figure must equal an independent SQL/Python computation
(principle 1). No LLM involved.
"""

import calendar
import datetime
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session


def _sql_actual_mtd(engine: Engine, as_of: datetime.date) -> Decimal:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT COALESCE(SUM(total), 0)::numeric(14,2) FROM core.invoice "
                "WHERE date_trunc('month', date) = date_trunc('month', CAST(:as_of AS date)) "
                "AND date <= CAST(:as_of AS date)"
            ),
            {"as_of": as_of},
        ).scalar()


def test_revenue_vs_plan_matches_sql(seeded_db: Engine) -> None:
    """actual_mtd == SUM(invoice.total) this month; variance == actual − target."""
    from valeri_api.crm.forecast import revenue_forecast

    as_of = datetime.date.today()
    with Session(seeded_db) as session:
        result = revenue_forecast(session, as_of)

    actual = _sql_actual_mtd(seeded_db, as_of)
    assert Decimal(result.actual_mtd) == actual
    assert result.period == f"{as_of.year:04d}-{as_of.month:02d}"

    with seeded_db.connect() as conn:
        target = conn.execute(
            text("SELECT target_amount FROM app.revenue_target WHERE period = :p"),
            {"p": result.period},
        ).scalar()
    if target is not None:
        assert Decimal(result.target) == target
        assert Decimal(result.variance) == (actual - target).quantize(Decimal("0.01"))


def test_run_rate_forecast(seeded_db: Engine) -> None:
    """forecast == actual_mtd / days_elapsed × days_in_month (independent computation)."""
    from valeri_api.crm.forecast import revenue_forecast

    as_of = datetime.date.today()
    with Session(seeded_db) as session:
        result = revenue_forecast(session, as_of)

    actual = _sql_actual_mtd(seeded_db, as_of)
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    expected = (actual / Decimal(as_of.day) * Decimal(days_in_month)).quantize(Decimal("0.01"))

    assert result.days_elapsed == as_of.day
    assert result.days_in_month == days_in_month
    assert Decimal(result.forecast) == expected


def test_forecast_day_one_no_divide_by_zero(seeded_db: Engine) -> None:
    """On day 1 the run-rate divides by 1, never by 0."""
    from valeri_api.crm.forecast import revenue_forecast

    first_of_month = datetime.date.today().replace(day=1)
    with Session(seeded_db) as session:
        result = revenue_forecast(session, first_of_month)
    assert result.days_elapsed == 1  # divisor is at least 1
    # forecast = actual × days_in_month (since elapsed == 1).
    actual = _sql_actual_mtd(seeded_db, first_of_month)
    days = calendar.monthrange(first_of_month.year, first_of_month.month)[1]
    assert Decimal(result.forecast) == (actual * Decimal(days)).quantize(Decimal("0.01"))


def test_forecast_no_target_is_honest(seeded_db: Engine) -> None:
    """A period with no target → target/variance null, forecast still from actuals."""
    from valeri_api.crm.forecast import revenue_forecast

    # A far-future month has no seeded target.
    far = datetime.date.today().replace(day=15) + datetime.timedelta(days=400)
    with Session(seeded_db) as session:
        result = revenue_forecast(session, far)
    assert result.target is None
    assert result.variance is None
    assert result.forecast is not None  # computed from (likely zero) actuals
