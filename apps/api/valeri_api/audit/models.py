"""SQLAlchemy models for the append-only audit schema + the decision log."""

import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)
decision_kind_enum = ENUM(
    "suppression",
    "threshold_change",
    "reactivation",
    "undo",
    "approval",
    "rejection",
    name="decision_kind",
    create_type=False,
)
actor_kind_enum = ENUM("valeri", "user", name="actor_kind", create_type=False)

DECISION_KINDS = (
    "suppression",
    "threshold_change",
    "reactivation",
    "undo",
    "approval",
    "rejection",
)


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


class Decision(Base):
    """One self-configuration / mutation decision (M9+). APPEND-ONLY.

    "Show the decision on the platform": every config-changing or mutating path
    writes one of these, and it is reversible (a revert writes a NEW decision
    referencing this one via reverted_decision_id — never an update/delete).
    """

    __tablename__ = "decision"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(decision_kind_enum, nullable=False)
    actor: Mapped[str] = mapped_column(actor_kind_enum, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    reverted_decision_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("app.decision.id")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
