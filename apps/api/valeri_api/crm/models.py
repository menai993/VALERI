"""SQLAlchemy models for the Phase-2 CRM tables (C-CRM1)."""

import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

opp_stage_enum = ENUM(
    "lead",
    "qualified",
    "proposal",
    "negotiation",
    "won",
    "lost",
    name="opp_stage",
    create_type=False,
)


class Opportunity(Base):
    """One sales opportunity (data-model.md Phase-2). User data — no AI envelope."""

    __tablename__ = "opportunity"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    stage: Mapped[str] = mapped_column(opp_stage_enum, nullable=False, server_default="lead")
    source: Mapped[str | None] = mapped_column(Text)
    expected_close: Mapped[datetime.date | None] = mapped_column(Date)
    owner_rep_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.sales_rep.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OpportunityStageHistory(Base):
    """One stage transition (APPEND-ONLY): never updated or deleted."""

    __tablename__ = "opportunity_stage_history"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.opportunity.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(opp_stage_enum, nullable=False)
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Activity(Base):
    """Rep activity (data-model.md Phase-2). Logged + rolled up in C-CRM2."""

    __tablename__ = "activity"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_rep_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.sales_rep.id"), nullable=False
    )
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.customer.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RevenueTarget(Base):
    """The company's monthly revenue plan (C-CRM2). period = 'YYYY-MM'."""

    __tablename__ = "revenue_target"
    __table_args__ = {"schema": "app"}

    period: Mapped[str] = mapped_column(Text, primary_key=True)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
