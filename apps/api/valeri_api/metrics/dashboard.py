"""Dashboard & metrics-API assembly (M8).

Every number comes from sql/dashboard.sql (principle 1); these functions only
run the queries, convert Decimals/dates to exact strings (jsonable), and shape
the response structures. No arithmetic happens here and no LLM is involved.

Row lists that reps may access take `customer_ids` (RBAC row scope): None means
unrestricted (owner/admin/finance), a set restricts to those customers.
"""

import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.metrics.schemas import (
    AtRiskRow,
    Customer360,
    CustomerBasketRow,
    DashboardResponse,
    InsightRow,
    KpiProgress,
    KpiTile,
    LostArticleRow,
    RecentlySuppressedRow,
    RevenueTrend,
)

# Dashboard layout constants (presentation row counts, NOT detection thresholds —
# those live in app.rule_config per CLAUDE.md).
TABLE_LIMIT = 10
INSIGHT_LIMIT = 8

# Supported date-range presets (D7).
RANGE_PRESETS = {"30d": 30, "90d": 90, "12m": 365}
DEFAULT_RANGE = "30d"

_SQL_FILE = Path(__file__).parent / "sql" / "dashboard.sql"


def _load_queries() -> dict[str, str]:
    """Split dashboard.sql into named queries on '-- name:' markers."""
    queries: dict[str, str] = {}
    content = _SQL_FILE.read_text(encoding="utf-8")
    for block in content.split("-- name: ")[1:]:
        name, _, sql = block.partition("\n")
        queries[name.strip()] = sql.strip()
    return queries


def _scope_params(customer_ids: set[int] | None) -> dict[str, Any]:
    """SQL parameters for RBAC row scoping."""
    return {
        "scoped": customer_ids is not None,
        "customer_ids": sorted(customer_ids) if customer_ids is not None else [],
    }


# ── KPI tiles ─────────────────────────────────────────────────────────────────


def kpis(session: Session, as_of: datetime.date, range_days: int) -> list[KpiTile]:
    """The 4 Početna KPI tiles (api-spec /metrics/overview), all values from SQL."""
    queries = _load_queries()

    revenue = session.execute(
        text(queries["kpi_revenue"]), {"as_of": as_of, "range_days": range_days}
    ).one()
    spark_rows = session.execute(text(queries["kpi_revenue_spark"]), {"as_of": as_of}).all()
    signals = session.execute(text(queries["kpi_signals"])).one()
    tasks = session.execute(text(queries["kpi_tasks"]), {"as_of": as_of}).one()

    spark = [str(jsonable(row.value)) for row in spark_rows]

    return [
        KpiTile(
            key="ukupan_prihod",
            value=str(jsonable(revenue.value)),
            prior_value=str(jsonable(revenue.prior_value)),
            delta_pct=str(jsonable(revenue.delta_pct)) if revenue.delta_pct is not None else None,
            delta_unit="%",
            spark=spark,
        ),
        KpiTile(key="kupci_u_padu", value=signals.declining_customers),
        KpiTile(key="izgubljeni_artikli", value=signals.lost_articles_open),
        KpiTile(
            key="zadaci_danas",
            value=tasks.due_tasks,
            progress=KpiProgress(done=tasks.done_tasks, total=tasks.total_tasks),
        ),
    ]


# ── revenue trend (combo chart) ───────────────────────────────────────────────


def revenue_trend(session: Session, as_of: datetime.date) -> RevenueTrend:
    """12-month revenue series + prior-year comparison + sub-stats."""
    queries = _load_queries()
    rows = session.execute(text(queries["revenue_trend"]), {"as_of": as_of}).all()
    substats = session.execute(text(queries["revenue_substats"]), {"as_of": as_of}).one()

    return RevenueTrend(
        months=[row.month for row in rows],
        revenue=[str(jsonable(row.revenue)) for row in rows],
        secondary=[str(jsonable(row.prior_year)) for row in rows],
        substats=[
            {"key": "ytd_prihod", "value": str(jsonable(substats.ytd_revenue))},
            {"key": "prosjecni_mjesecni", "value": str(jsonable(substats.avg_monthly))},
            {"key": "najbolji_mjesec", "value": str(jsonable(substats.best_month))},
        ],
    )


# ── AI-derived row lists (each row carries the envelope) ─────────────────────


def at_risk_rows(
    session: Session,
    limit: int = TABLE_LIMIT,
    customer_ids: set[int] | None = None,
) -> list[AtRiskRow]:
    """Customers-at-risk table rows from open customer_decline signals."""
    queries = _load_queries()
    rows = session.execute(
        text(queries["at_risk"]), {"limit": limit, **_scope_params(customer_ids)}
    ).mappings()
    return [AtRiskRow(**jsonable(dict(row))) for row in rows]


def lost_article_rows(
    session: Session,
    limit: int = TABLE_LIMIT,
    customer_id: int | None = None,
    customer_ids: set[int] | None = None,
) -> list[LostArticleRow]:
    """Lost-article rows from open lost_article signals."""
    queries = _load_queries()
    rows = session.execute(
        text(queries["lost_articles"]),
        {"limit": limit, "customer_id": customer_id, **_scope_params(customer_ids)},
    ).mappings()
    return [LostArticleRow(**jsonable(dict(row))) for row in rows]


def insight_rows(
    session: Session,
    limit: int = INSIGHT_LIMIT,
    customer_ids: set[int] | None = None,
) -> list[InsightRow]:
    """'AI uvidi' rows: the strongest open signals across all rules."""
    queries = _load_queries()
    rows = session.execute(
        text(queries["insights"]), {"limit": limit, **_scope_params(customer_ids)}
    ).mappings()
    return [InsightRow(**{**jsonable(dict(row)), "created_at": row["created_at"]}) for row in rows]


# ── customer 360 ──────────────────────────────────────────────────────────────


def customer_360(session: Session, customer_id: int, as_of: datetime.date) -> Customer360 | None:
    """360-lite metrics for one customer; None when the customer has no metrics row."""
    queries = _load_queries()
    header = (
        session.execute(text(queries["customer_metrics"]), {"customer_id": customer_id})
        .mappings()
        .one_or_none()
    )
    if header is None:
        return None

    monthly = session.execute(
        text(queries["customer_monthly_turnover"]), {"customer_id": customer_id, "as_of": as_of}
    ).mappings()
    basket = session.execute(
        text(queries["customer_basket"]), {"customer_id": customer_id, "as_of": as_of}
    ).mappings()

    header_data = jsonable(dict(header))
    return Customer360(
        customer_id=header["customer_id"],
        customer_name=header["customer_name"],
        segment=header["segment"],
        status=header["status"],
        turnover_60d=header_data["turnover_60d"],
        baseline_60d=header_data["baseline_60d"],
        last_order_date=header_data["last_order_date"],
        avg_order_interval_d=header_data["avg_order_interval_d"],
        monthly_turnover=[jsonable(dict(row)) for row in monthly],
        basket=[CustomerBasketRow(**jsonable(dict(row))) for row in basket],
    )


# ── the one-call dashboard payload ────────────────────────────────────────────

# How many recent suppressions the dashboard lists (presentation choice, D6).
SUPPRESSED_LIMIT = 10


def recently_suppressed_rows(
    session: Session, limit: int = SUPPRESSED_LIMIT
) -> list[RecentlySuppressedRow]:
    """The last N suppression hits (M11): what learned rules recently hid — pure SQL."""
    rows = session.execute(
        text(
            "SELECT h.id AS hit_id, h.suppressed_at, lr.id AS learned_rule_id, lr.description, "
            "       s.rule, s.customer_id, c.name AS customer_name "
            "FROM app.suppression_hit h "
            "JOIN app.learned_rule lr ON lr.id = h.learned_rule_id "
            "LEFT JOIN app.signal s ON s.id = h.signal_id "
            "LEFT JOIN core.customer c ON c.id = s.customer_id "
            "ORDER BY h.id DESC LIMIT :limit"
        ),
        {"limit": limit},
    ).mappings()
    return [
        RecentlySuppressedRow(**{**jsonable(dict(row)), "suppressed_at": row["suppressed_at"]})
        for row in rows
    ]


def assemble_dashboard(
    session: Session,
    as_of: datetime.date,
    range_days: int,
    owner_report_summary: dict[str, Any] | None,
) -> DashboardResponse:
    """The Početna payload (api-spec GET /dashboard) — pure SQL pass-through."""
    return DashboardResponse(
        as_of=as_of,
        range_days=range_days,
        kpis=kpis(session, as_of, range_days),
        revenue_trend=revenue_trend(session, as_of),
        ai_insights=insight_rows(session),
        customers_at_risk=at_risk_rows(session),
        lost_articles=lost_article_rows(session),
        rep_activity=None,
        owner_report_summary=owner_report_summary,
        recently_suppressed=recently_suppressed_rows(session),
        opportunities=_opportunities_summary(session),
    )


def _opportunities_summary(session: Session) -> dict[str, Any] | None:
    """C-CRM1: the dashboard's Prilike block — None when no opportunities exist yet."""
    from valeri_api.crm.service import dashboard_summary

    has_any = session.execute(text("SELECT EXISTS (SELECT 1 FROM app.opportunity)")).scalar()
    if not has_any:
        return None  # CRM track not in use → honest empty, not fake pipeline data
    # The dashboard is owner/admin/finance only — unrestricted scope.
    return dashboard_summary(session, customer_ids=None).model_dump(mode="json")


def resolve_range(range_key: str | None) -> int:
    """Map a range preset (?range=30d/90d/12m) to days; default 30d."""
    return RANGE_PRESETS.get(range_key or DEFAULT_RANGE, RANGE_PRESETS[DEFAULT_RANGE])
