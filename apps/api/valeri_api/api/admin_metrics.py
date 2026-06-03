"""Admin operational control over the derived-metrics pipeline.

GET  /api/admin/metrics/status     — derived-data state (counts + last computed/scan time)
POST /api/admin/metrics/recompute  — full recompute of the derived core.* tables (no LLM)
POST /api/admin/scan               — run detection rules → signals only (create_tasks=False, no LLM)

RBAC (admin only — operational/administrative actions, like the ingest router). Every number
is produced by SQL/Python (principle 1); no LLM is involved. Recompute/scan refresh *derived*
data from unchanged inputs (rule_config, learned_rule), so they are not configuration changes
and write no app.decision (principle 10 governs config changes); they are logged via app logging.
"""

import datetime
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.db import get_session
from valeri_api.metrics.recompute import recompute_all
from valeri_api.scanner.scan import run_scan

logger = logging.getLogger("valeri.admin.metrics")

router = APIRouter(dependencies=[Depends(require_roles("admin"))])


class TableStat(BaseModel):
    """Row count for one derived table, plus the freshness timestamp where it exists."""

    rows: int
    computed_at: datetime.datetime | None = None  # core.customer_metrics only
    last_scan_at: datetime.datetime | None = None  # app.signal only


class MetricsStatus(BaseModel):
    """State of every derived table the dashboard/scanner depend on."""

    customer_metrics: TableStat
    cust_article_cadence: TableStat
    segment_basket: TableStat
    client_expectation: TableStat
    signals: TableStat
    tasks: TableStat


class RecomputeResponse(BaseModel):
    rows: dict[str, int]
    as_of: datetime.date


class ScanResponse(BaseModel):
    inserted: int
    suppressed: int
    as_of: datetime.date


@router.get("/admin/metrics/status", response_model=MetricsStatus)
def metrics_status(session: Annotated[Session, Depends(get_session)]) -> MetricsStatus:
    """Counts + freshness for the derived tables — numbers straight from SQL."""

    def _count(query: str) -> int:
        return int(session.execute(text(query)).scalar() or 0)

    return MetricsStatus(
        customer_metrics=TableStat(
            rows=_count("SELECT COUNT(*) FROM core.customer_metrics"),
            computed_at=session.execute(
                text("SELECT MAX(computed_at) FROM core.customer_metrics")
            ).scalar(),
        ),
        cust_article_cadence=TableStat(
            rows=_count("SELECT COUNT(*) FROM core.cust_article_cadence")
        ),
        segment_basket=TableStat(rows=_count("SELECT COUNT(*) FROM core.segment_basket")),
        client_expectation=TableStat(rows=_count("SELECT COUNT(*) FROM core.client_expectation")),
        signals=TableStat(
            rows=_count("SELECT COUNT(*) FROM app.signal"),
            last_scan_at=session.execute(text("SELECT MAX(created_at) FROM app.signal")).scalar(),
        ),
        tasks=TableStat(rows=_count("SELECT COUNT(*) FROM app.task")),
    )


@router.post("/admin/metrics/recompute", response_model=RecomputeResponse)
def recompute(session: Annotated[Session, Depends(get_session)]) -> RecomputeResponse:
    """Full refresh of the derived core.* tables. Synchronous; pure SQL; no LLM."""
    result = recompute_all(session, as_of=datetime.date.today())
    session.commit()
    logger.info("admin recompute: %s", result.rows)
    return RecomputeResponse(rows=result.rows, as_of=result.as_of)


@router.post("/admin/scan", response_model=ScanResponse)
def scan(session: Annotated[Session, Depends(get_session)]) -> ScanResponse:
    """Run detection rules → signals only (no task creation, so no LLM/token cost)."""
    result = run_scan(session, as_of=datetime.date.today(), create_tasks=False)
    session.commit()
    logger.info(
        "admin scan: inserted=%s suppressed=%s", result.total_inserted, result.total_suppressed
    )
    return ScanResponse(
        inserted=result.total_inserted, suppressed=result.total_suppressed, as_of=result.as_of
    )
