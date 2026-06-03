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
