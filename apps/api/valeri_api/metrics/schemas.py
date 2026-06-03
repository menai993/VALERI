"""Pydantic schemas for the dashboard & metrics API (M8).

SQL numbers are passed through as exact strings (Decimal → str via jsonable),
never as floats — the client formats them. The AI-response envelope fields
(register/confidence/conf_band/evidence) ride on every AI-derived row.
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel

Register = Literal["analiza", "preporuka", "akcija"]


class KpiProgress(BaseModel):
    done: int
    total: int


class KpiTile(BaseModel):
    """One KPI card: SQL value + delta + sparkline (api-spec /metrics/overview)."""

    key: str
    value: str | int
    prior_value: str | int | None = None
    delta_pct: str | None = None
    delta_unit: str | None = None
    spark: list[str] = []
    progress: KpiProgress | None = None


class RevenueTrend(BaseModel):
    """The combo-chart series: 12 months of revenue + prior-year comparison."""

    months: list[str]
    revenue: list[str]
    secondary: list[str]
    substats: list[dict[str, Any]]


class EnvelopeRow(BaseModel):
    """Base for AI-derived rows: every one carries the AI-response envelope."""

    signal_id: int
    customer_id: int
    customer_name: str
    segment: str | None
    confidence: str
    conf_band: str
    register: Register
    evidence: dict[str, Any]


class AtRiskRow(EnvelopeRow):
    """One customers-at-risk table row (from a customer_decline signal)."""

    last_order_date: str | None
    value: str
    baseline: str
    delta_pct: str
    risk_band: Literal["nizak", "srednji", "visok"]


class LostArticleRow(EnvelopeRow):
    """One lost-article table row (from a lost_article signal)."""

    article_id: int | None
    article_name: str | None
    article_code: str | None
    avg_interval_d: str | None
    gap_days: int | None
    last_seen: str | None


class InsightRow(EnvelopeRow):
    """One 'AI uvidi' list row (any rule), linked to its task."""

    rule: str
    task_id: int | None
    task_title: str | None
    created_at: datetime.datetime


class CustomerBasketRow(BaseModel):
    category_id: int | None
    category_name: str | None
    n_articles: int
    total_spent: str


class Customer360(BaseModel):
    """The 360-lite metrics block for one customer."""

    customer_id: int
    customer_name: str
    segment: str | None
    status: str
    turnover_60d: str | None
    baseline_60d: str | None
    last_order_date: str | None
    avg_order_interval_d: str | None
    monthly_turnover: list[dict[str, Any]]
    basket: list[CustomerBasketRow]


class MetricsOverview(BaseModel):
    """GET /metrics/overview response."""

    as_of: datetime.date
    range_days: int
    kpis: list[KpiTile]


class DashboardResponse(BaseModel):
    """GET /dashboard — the Početna payload in one call."""

    as_of: datetime.date
    range_days: int
    kpis: list[KpiTile]
    revenue_trend: RevenueTrend
    ai_insights: list[InsightRow]
    customers_at_risk: list[AtRiskRow]
    lost_articles: list[LostArticleRow]
    rep_activity: None = None  # Phase 2 placeholder — never fake data
    owner_report_summary: dict[str, Any] | None = None  # M7 extract_summary payload
    recently_suppressed: list[dict[str, Any]] = []  # filled in M11
