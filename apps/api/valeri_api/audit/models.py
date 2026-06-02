"""SQLAlchemy models for the append-only audit schema."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class TaskLog(Base):
    """One task lifecycle event (M5). APPEND-ONLY: rows are only ever inserted."""

    __tablename__ = "task_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.task.id"))
    event: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
