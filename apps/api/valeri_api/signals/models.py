"""SQLAlchemy models for app.task and app.task_feedback (M5)."""

import datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

task_status_enum = ENUM(
    "open", "in_progress", "done", "dismissed", name="task_status", create_type=False
)
register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)

TASK_STATUSES = ("open", "in_progress", "done", "dismissed")


class Task(Base):
    """A unit of work derived from exactly one signal (docs/data-model.md)."""

    __tablename__ = "task"
    __table_args__ = (
        Index("ix_task_assignee_status", "assignee_id", "status"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.signal.id"))
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.sales_rep.id"))
    owner_cc: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    proposed_action: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        task_status_enum, nullable=False, server_default=text("'open'")
    )
    register: Mapped[str] = mapped_column(
        register_enum, nullable=False, server_default=text("'preporuka'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskFeedback(Base):
    """Rep/owner feedback on a task (the raw material of the M10 learning loop)."""

    __tablename__ = "task_feedback"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app.task.id"), nullable=False)
    useful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    by_user: Mapped[int | None] = mapped_column(BigInteger)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
