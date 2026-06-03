"""Pydantic schemas for the weekly owner report (typed I/O per CLAUDE.md)."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Register = Literal["analiza", "preporuka", "akcija"]


class ReportSectionNarrative(BaseModel):
    """The LLM output schema for one report section (D6).

    The stored section register is fixed by the report layout (D5); the LLM's
    claimed register is recorded in audit.ai_log only.
    """

    text: str = Field(min_length=20, description="Bosanski narativ sekcije izvještaja")
    register: Register


class ReportSection(BaseModel):
    """One register-tagged block of the stored report."""

    key: str
    title: str
    register: Register
    narrative: str
    narrative_source: Literal["llm", "template"]
    data: dict[str, Any]


class OwnerReportRead(BaseModel):
    """The full stored weekly report, as served by the API."""

    model_config = ConfigDict(from_attributes=True)

    week_start: datetime.date
    week_end: datetime.date
    generated_at: datetime.datetime
    sections: list[ReportSection]


class SummaryMetric(BaseModel):
    """One mini metric card in the dashboard summary block."""

    label: str
    value: Any  # SQL value passed through (string-encoded Decimal or int)
    register: Register


class SummaryBullet(BaseModel):
    """One narrative bullet in the dashboard summary block."""

    text: str
    register: Register


class OwnerReportSummary(BaseModel):
    """The dashboard summary block extracted from the latest stored report."""

    week_start: datetime.date
    week_end: datetime.date
    metrics: list[SummaryMetric]
    bullets: list[SummaryBullet]
