"""Pydantic schemas for opportunities + pipeline (C-CRM1).

Money/probability are returned as exact strings (the client formats), consistent
with every other VALERI money field. These are USER DATA, not AI output — no
register/confidence/evidence envelope applies.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OppStage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]


class OpportunityCreate(BaseModel):
    customer_id: int
    title: str = Field(min_length=2, max_length=300)
    value: float | None = Field(default=None, ge=0)
    probability: float | None = Field(default=None, ge=0, le=1)
    stage: OppStage = "lead"
    source: str | None = None
    expected_close: datetime.date | None = None
    owner_rep_id: int | None = None


class OpportunityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    value: float | None = Field(default=None, ge=0)
    probability: float | None = Field(default=None, ge=0, le=1)
    stage: OppStage | None = None
    source: str | None = None
    expected_close: datetime.date | None = None
    owner_rep_id: int | None = None


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_name: str | None = None
    title: str
    value: str | None
    probability: str | None
    stage: OppStage
    source: str | None
    expected_close: datetime.date | None
    owner_rep_id: int | None
    owner_rep_name: str | None = None
    # SQL-computed: the effective probability (explicit OR stage default) and value × it.
    effective_probability: str | None = None
    weighted_value: str | None = None
    created_at: datetime.datetime


class OpportunityListResponse(BaseModel):
    items: list[OpportunityRead]


# ── pipeline ──────────────────────────────────────────────────────────────────


class PipelineStage(BaseModel):
    """One kanban column: a stage with its opportunities + SQL aggregates."""

    stage: OppStage
    count: int
    value: str  # SUM(value)
    weighted_value: str  # SUM(value × effective_probability)
    opportunities: list[OpportunityRead]


class PipelineResponse(BaseModel):
    stages: list[PipelineStage]
    total_weighted_value: str  # over open stages
    conversion_rate: str  # won / (won + lost)
    open_count: int


# ── dashboard summary block ───────────────────────────────────────────────────


class OpportunitySummaryRow(BaseModel):
    id: int
    title: str
    customer_name: str | None
    value: str | None
    probability: str | None
    weighted_value: str


class OpportunitySummary(BaseModel):
    """The dashboard 'Prilike' block — Otvorene prilike / Stopa konverzije / Najveće prilike."""

    open_count: int
    conversion_rate: str
    weighted_value: str
    top: list[OpportunitySummaryRow]


# ── activity (C-CRM2) ─────────────────────────────────────────────────────────

ActivityKind = Literal["meeting", "call", "offer", "follow_up", "analysis"]


class ActivityCreate(BaseModel):
    kind: ActivityKind
    customer_id: int | None = None
    done: bool = False
    sales_rep_id: int | None = None  # owner/admin may log for any rep; reps forced to own
    at: datetime.datetime | None = None


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_rep_id: int
    customer_id: int | None
    kind: ActivityKind
    done: bool
    at: datetime.datetime


class RepActivityRow(BaseModel):
    """One rep's activity rollup for a period (counts by kind + completion)."""

    sales_rep_id: int
    name: str | None
    total: int
    done: int
    completion: str  # done / total, "0.0000" when none
    by_kind: dict[str, int]


class RepActivityBlock(BaseModel):
    as_of: datetime.date
    reps: list[RepActivityRow]


# ── forecasting (C-CRM2) ──────────────────────────────────────────────────────


class RevenueForecast(BaseModel):
    """Revenue-vs-plan + a simple run-rate forecast for the current month — all SQL/Python."""

    period: str  # 'YYYY-MM'
    actual_mtd: str  # SUM(invoice.total) this month
    target: str | None  # revenue_target for the period (None if unset)
    variance: str | None  # actual − target (None if no target)
    forecast: str  # actual_mtd / days_elapsed × days_in_month
    days_elapsed: int
    days_in_month: int


# ── owner-report CRM sections (C-CRM2) ────────────────────────────────────────


class OpportunitySourceRow(BaseModel):
    source: str | None
    count: int
    value: str
    weighted_value: str


class OpportunityStats(BaseModel):
    """Opportunity-source attribution + average opportunity value (owner report)."""

    by_source: list[OpportunitySourceRow]
    avg_value: str
    total_count: int
