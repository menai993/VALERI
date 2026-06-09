"""Ops status API (P2): the system's self-report for Postavke → Podaci.

Per-job ledger rollups, data freshness, and the active alert conditions — all
SQL/Python-over-DB facts. Owner/admin only (D1).
"""

import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.db import get_session
from valeri_api.ops.runs import data_freshness, derive_alerts, job_statuses

router = APIRouter(dependencies=[Depends(require_roles("owner", "admin"))])


class JobStatusRow(BaseModel):
    job: str
    last_status: str | None
    last_run_at: datetime.datetime | None
    last_ok_at: datetime.datetime | None
    consecutive_failures: int


class OpsAlert(BaseModel):
    kind: str
    message: str


class OpsStatusResponse(BaseModel):
    jobs: list[JobStatusRow]
    data_freshness: dict[str, Any]
    alerts: list[OpsAlert]


@router.get("/admin/ops/status", response_model=OpsStatusResponse)
def ops_status(session: Annotated[Session, Depends(get_session)]) -> OpsStatusResponse:
    """Job health + data freshness + active alerts (the bell's `alerts` detail)."""
    return OpsStatusResponse(
        jobs=[JobStatusRow(**row) for row in job_statuses(session)],
        data_freshness=data_freshness(session),
        alerts=[OpsAlert(**alert) for alert in derive_alerts(session)],
    )
