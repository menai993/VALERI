"""SQLAlchemy models for app.investigation + app.investigation_step (M13)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

inv_status_enum = ENUM(
    "queued", "running", "needs_input", "done", "failed", name="inv_status", create_type=False
)


class Investigation(Base):
    """One investigation run (data-model.md M13 + additive created_by/signal_id)."""

    __tablename__ = "investigation"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)  # user/auto/signal
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(inv_status_enum, nullable=False, server_default="queued")
    model_tier: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # {narrative, findings[], confidence, next_step, trace_ref, ...}
    report: Mapped[dict | None] = mapped_column(JSONB)
    thread_id: Mapped[str | None] = mapped_column(Text)  # LangGraph checkpoint thread
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.app_user.id"))
    signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.signal.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InvestigationStep(Base):
    """One trace entry (APPEND-ONLY): every node execution / tool call is recorded."""

    __tablename__ = "investigation_step"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.investigation.id"), nullable=False
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    node: Mapped[str | None] = mapped_column(Text)
    tool: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
