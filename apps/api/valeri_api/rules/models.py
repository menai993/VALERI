"""SQLAlchemy models for app.rule_config, app.signal, app.learned_rule (M4)."""

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)
conf_band_enum = ENUM("niska", "srednja", "visoka", name="conf_band", create_type=False)
signal_status_enum = ENUM(
    "new", "tasked", "dismissed", "suppressed", "resolved", name="signal_status", create_type=False
)
lr_status_enum = ENUM(
    "pending_confirm", "active", "reverted", "expired", name="lr_status", create_type=False
)
autonomy_enum = ENUM("auto_applied", "confirmed", name="autonomy", create_type=False)


class RuleConfig(Base):
    """A single detection threshold: (rule, param) → JSONB value."""

    __tablename__ = "rule_config"
    __table_args__ = {"schema": "app"}

    rule: Mapped[str] = mapped_column(Text, primary_key=True)
    param: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Signal(Base):
    """A detection result with evidence and confidence (docs/data-model.md)."""

    __tablename__ = "signal"
    __table_args__ = (
        Index("ix_signal_status", "status"),
        Index("ix_signal_customer", "customer_id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.customer.id"))
    article_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.article.id"))
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    conf_band: Mapped[str] = mapped_column(conf_band_enum, nullable=False)
    register: Mapped[str] = mapped_column(
        register_enum, nullable=False, server_default=text("'analiza'")
    )
    status: Mapped[str] = mapped_column(
        signal_status_enum, nullable=False, server_default=text("'new'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LearnedRule(Base):
    """A self-configured rule (written in M10; consulted by the scanner from M4)."""

    __tablename__ = "learned_rule"
    __table_args__ = (
        Index(
            "ix_learned_rule_active",
            "status",
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.signal.id"))
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    effect_estimate: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        lr_status_enum, nullable=False, server_default=text("'active'")
    )
    autonomy: Mapped[str] = mapped_column(autonomy_enum, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class SuppressionHit(Base):
    """One scanner suppression event (M10). APPEND-ONLY.

    Links the learned rule that suppressed to the persisted suppressed signal
    (status='suppressed', evidence kept) — the raw material for the M11
    over-suppression auditor.
    """

    __tablename__ = "suppression_hit"
    __table_args__ = (
        Index("ix_suppression_hit_rule", "learned_rule_id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    learned_rule_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.learned_rule.id"), nullable=False
    )
    signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.signal.id"))
    suppressed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
