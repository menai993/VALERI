"""Typed convenience wrappers over registered metrics (ad-hoc turnover queries).

These exist so application code gets a typed Python API; the SQL itself lives in
the semantic registry (single source of truth). Numbers always come from SQL.
"""

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.semantic.query_builder import run_metric


def turnover(
    session: Session,
    from_date: datetime.date,
    to_date: datetime.date,
    customer_id: int | None = None,
    article_id: int | None = None,
    category_id: int | None = None,
    segment: str | None = None,
) -> Decimal:
    """Total turnover in (from_date, to_date], optionally filtered."""
    result = run_metric(
        session,
        "turnover",
        {
            "from_date": from_date,
            "to_date": to_date,
            "customer_id": customer_id,
            "article_id": article_id,
            "category_id": category_id,
            "segment": segment,
        },
    )
    return result.scalar()


def turnover_by_month(
    session: Session,
    from_date: datetime.date,
    to_date: datetime.date,
    customer_id: int | None = None,
) -> list[dict[str, Any]]:
    """Monthly turnover series in (from_date, to_date], optionally per customer."""
    result = run_metric(
        session,
        "turnover_by_month",
        {"from_date": from_date, "to_date": to_date, "customer_id": customer_id},
    )
    return result.rows
