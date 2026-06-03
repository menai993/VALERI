"""Dashboard API (M8): the Početna payload in one call — per docs/api-spec.md.

Owner/admin/finance only (reps work from /tasks). Every number is a SQL value
passed through; every AI-derived row carries the response envelope.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.db import get_session
from valeri_api.metrics.dashboard import assemble_dashboard, resolve_range
from valeri_api.metrics.schemas import DashboardResponse
from valeri_api.reports.builder import extract_summary
from valeri_api.reports.models import OwnerReport

router = APIRouter()


def _latest_report_summary(session: Session) -> dict | None:
    """The M7 owner-report summary block for the dashboard, if a report exists."""
    report = session.execute(
        select(OwnerReport).order_by(OwnerReport.week_end.desc()).limit(1)
    ).scalar_one_or_none()
    if report is None:
        return None
    return extract_summary(report).model_dump(mode="json")


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[object, Depends(require_roles("owner", "admin", "finance"))],
    range: str | None = None,  # noqa: A002 - query param name fixed by api-spec
) -> DashboardResponse:
    """The full Početna payload: KPIs, trend, AI uvidi, tables, report summary."""
    as_of = datetime.date.today()
    range_days = resolve_range(range)
    return assemble_dashboard(
        session,
        as_of=as_of,
        range_days=range_days,
        owner_report_summary=_latest_report_summary(session),
    )
