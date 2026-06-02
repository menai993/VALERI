"""Owner report API (M7): the stored weekly report + the dashboard summary block.

Numbers in responses are the stored SQL values, passed through — the API never
returns a figure computed by the LLM. RBAC lands in M8.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.db import get_session
from valeri_api.reports.builder import extract_summary, week_bounds
from valeri_api.reports.models import OwnerReport
from valeri_api.reports.schemas import OwnerReportRead, OwnerReportSummary, ReportSection

router = APIRouter()


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": message})


def _to_read(report: OwnerReport) -> OwnerReportRead:
    return OwnerReportRead(
        week_start=report.week_start,
        week_end=report.week_end,
        generated_at=report.generated_at,
        sections=[ReportSection.model_validate(section) for section in report.payload["sections"]],
    )


@router.get("/reports/owner/weekly", response_model=OwnerReportRead)
def get_weekly_report(
    session: Annotated[Session, Depends(get_session)],
    week_end: datetime.date | None = None,
) -> OwnerReportRead:
    """The stored weekly report — for the week containing week_end, or the latest."""
    query = select(OwnerReport)
    if week_end is not None:
        week_start, _ = week_bounds(week_end)
        query = query.where(OwnerReport.week_start == week_start)
    else:
        query = query.order_by(OwnerReport.week_end.desc())

    report = session.execute(query.limit(1)).scalar_one_or_none()
    if report is None:
        raise _not_found("No owner report stored for the requested week")
    return _to_read(report)


@router.get("/reports/owner/summary", response_model=OwnerReportSummary)
def get_summary(session: Annotated[Session, Depends(get_session)]) -> OwnerReportSummary:
    """The dashboard summary block, extracted from the latest stored report."""
    report = session.execute(
        select(OwnerReport).order_by(OwnerReport.week_end.desc()).limit(1)
    ).scalar_one_or_none()
    if report is None:
        raise _not_found("No owner report stored yet")
    return extract_summary(report)
