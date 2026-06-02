"""SQLAlchemy models for the append-only audit schema."""

import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)


class AiLog(Base):
    """One LLM call (M6). APPEND-ONLY: rows are only ever inserted.

    masked_input must never contain raw PII — the masking layer guarantees it
    and the contract tests assert it.
    """

    __tablename__ = "ai_log"
    __table_args__ = {"schema": "audit"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    masked_input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    register: Mapped[str | None] = mapped_column(register_enum)
    tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


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
