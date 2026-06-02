"""SQLAlchemy model for app.owner_report (M7, D1)."""

import datetime

from sqlalchemy import BigInteger, Date, DateTime, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class OwnerReport(Base):
    """One immutable weekly report snapshot (Monday–Sunday week).

    Stored so the report is a reproducible artifact ("what did VALERI tell me
    last Monday?") and LLM narration is paid once per week, not per view.
    """

    __tablename__ = "owner_report"
    __table_args__ = (
        UniqueConstraint("week_start", "week_end", name="ux_owner_report_week"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    week_end: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
