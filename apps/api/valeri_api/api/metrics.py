"""Metrics API (M8): KPI overview, revenue trend, customer 360 — per docs/api-spec.md.

Owner/admin/finance, except the customer 360 which an owning rep may also load.
All numbers from SQL (metrics/sql/dashboard.sql), passed through exactly.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser, require_roles, visible_customer_ids
from valeri_api.db import get_session
from valeri_api.metrics.dashboard import customer_360, kpis, resolve_range, revenue_trend
from valeri_api.metrics.schemas import Customer360, MetricsOverview, RevenueTrend

router = APIRouter()


@router.get("/metrics/overview", response_model=MetricsOverview)
def get_overview(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[object, Depends(require_roles("owner", "admin", "finance"))],
    range: str | None = None,  # noqa: A002 - query param name fixed by api-spec
) -> MetricsOverview:
    """The 4 KPI cards for the selected range preset."""
    as_of = datetime.date.today()
    range_days = resolve_range(range)
    return MetricsOverview(
        as_of=as_of, range_days=range_days, kpis=kpis(session, as_of, range_days)
    )


@router.get("/metrics/revenue-trend", response_model=RevenueTrend)
def get_revenue_trend(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[object, Depends(require_roles("owner", "admin", "finance"))],
) -> RevenueTrend:
    """The 12-month combo-chart series + sub-stats."""
    return revenue_trend(session, as_of=datetime.date.today())


@router.get("/metrics/customer/{customer_id}", response_model=Customer360)
def get_customer_metrics(
    customer_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> Customer360:
    """360-lite metrics for one customer (owner/admin/finance, or the owning rep)."""
    scope = visible_customer_ids(user, session)
    if scope is not None and customer_id not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Nemate pristup ovom kupcu"},
        )

    result = customer_360(session, customer_id, as_of=datetime.date.today())
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Customer {customer_id} has no metrics"},
        )
    return result
