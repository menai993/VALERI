"""SQLAlchemy models for LLM cost tracking (P3): pricing + budget.

Both live in the app schema. Prices are editable rows (the admin API patches
them, writing a reversible decision) — never literals in code.
"""

import datetime
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class LlmPricing(Base):
    """Per-model token prices (USD per 1M tokens). Keyed by the model id or tier
    alias the gateway echoes back; unknown models have no row → cost is NULL."""

    __tablename__ = "llm_pricing"
    __table_args__ = {"schema": "app"}

    model: Mapped[str] = mapped_column(Text, primary_key=True)
    input_per_mtok: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    output_per_mtok: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    cache_read_per_mtok: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    batch_discount: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.5")
    )
    effective_date: Mapped[datetime.date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )


class LlmBudget(Base):
    """A monthly spend budget. period is 'YYYY-MM' or 'default' (the fallback row
    so alerting works without per-month admin upkeep)."""

    __tablename__ = "llm_budget"
    __table_args__ = {"schema": "app"}

    period: Mapped[str] = mapped_column(Text, primary_key=True)
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    alert_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
