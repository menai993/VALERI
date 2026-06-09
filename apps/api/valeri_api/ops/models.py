"""SQLAlchemy model for the job-run ledger (P2 ops hardening).

Operational telemetry: prunable (90-day retention), deliberately NOT part of
the append-only audit family.
"""

import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

JOB_RUN_STATUSES = ("running", "ok", "failed", "skipped")

# The scheduled jobs whose failure streaks alert (worker_heartbeat is liveness only).
ALERTED_JOBS = ("daily_scan", "weekly_cycle", "over_suppression_audit", "backup_restore_check")

HEARTBEAT_JOB = "worker_heartbeat"


class JobRun(Base):
    """One scheduled-job execution (or the single upserted worker heartbeat)."""

    __tablename__ = "job_run"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="running")
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
