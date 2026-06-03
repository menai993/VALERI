"""Revenue-vs-plan + a simple run-rate forecast (C-CRM2).

Actual MTD revenue is a SQL SUM over core.invoice; the target is the company's
monthly plan (app.revenue_target). The forecast is a deterministic run-rate
projection computed in Python over the SQL MTD value — no model, no tunable.
"""

import calendar
import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.crm.schemas import RevenueForecast


def revenue_forecast(session: Session, as_of: datetime.date) -> RevenueForecast:
    """Revenue-vs-plan for the month of `as_of` + the run-rate forecast.

    actual_mtd  = SUM(invoice.total) for the month, up to and including as_of (SQL)
    target      = revenue_target for 'YYYY-MM' (None if unset)
    variance    = actual − target (None when no target)
    forecast    = actual_mtd / days_elapsed × days_in_month  (run-rate; day-1 safe)
    """
    period = f"{as_of.year:04d}-{as_of.month:02d}"

    actual_mtd: Decimal = session.execute(
        text(
            "SELECT COALESCE(SUM(total), 0)::numeric(14,2) FROM core.invoice "
            "WHERE date_trunc('month', date) = date_trunc('month', CAST(:as_of AS date)) "
            "AND date <= CAST(:as_of AS date)"
        ),
        {"as_of": as_of},
    ).scalar()

    target: Decimal | None = session.execute(
        text("SELECT target_amount FROM app.revenue_target WHERE period = :period"),
        {"period": period},
    ).scalar()

    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    days_elapsed = as_of.day  # day-of-month → at least 1, so never divides by zero

    # Run-rate projection of the partial month to month-end.
    forecast = (actual_mtd / Decimal(days_elapsed) * Decimal(days_in_month)).quantize(
        Decimal("0.01")
    )
    variance = (actual_mtd - target).quantize(Decimal("0.01")) if target is not None else None

    return RevenueForecast(
        period=period,
        actual_mtd=f"{actual_mtd:.2f}",
        target=f"{target:.2f}" if target is not None else None,
        variance=f"{variance:.2f}" if variance is not None else None,
        forecast=f"{forecast:.2f}",
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
    )
