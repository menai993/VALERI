"""LLM cost computation + spend aggregates (P3). Pure Decimal/SQL over the DB.

Principle 1 lives here too: a cost figure is arithmetic over DB-seeded prices and
token counts the gateway reported — the model never produces or sees it. An
unknown model yields NULL, never a guessed price.
"""

import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("valeri.llm.cost")

_MTOK = Decimal(1_000_000)
_CENT6 = Decimal("0.000001")


def get_pricing(session: Session, model: str) -> dict[str, Decimal] | None:
    """Prices for one model (USD per 1M tokens) + batch discount, or None."""
    row = session.execute(
        text(
            "SELECT input_per_mtok, output_per_mtok, cache_read_per_mtok, batch_discount "
            "FROM app.llm_pricing WHERE model = :model"
        ),
        {"model": model},
    ).one_or_none()
    if row is None:
        return None
    return {
        "input": Decimal(row.input_per_mtok),
        "output": Decimal(row.output_per_mtok),
        "cache_read": (
            Decimal(row.cache_read_per_mtok) if row.cache_read_per_mtok is not None else Decimal(0)
        ),
        "batch_discount": Decimal(row.batch_discount),
    }


def compute_cost(
    session: Session,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None = 0,
    batched: bool = False,
) -> Decimal | None:
    """USD cost for one call from token counts × DB prices. NULL when unpriced.

    cost = (input−cached)×in_rate + cached×cache_read_rate + output×out_rate,
    all × batch_discount when batched. Rounded to 6 dp (matches NUMERIC(12,6)).
    """
    pricing = get_pricing(session, model)
    if pricing is None:
        logger.warning("no llm_pricing row for model %r — cost_usd left NULL", model)
        return None

    inp = Decimal(input_tokens or 0)
    out = Decimal(output_tokens or 0)
    cached = Decimal(cached_input_tokens or 0)
    billable_input = inp - cached
    if billable_input < 0:
        billable_input = Decimal(0)

    cost = (
        billable_input / _MTOK * pricing["input"]
        + cached / _MTOK * pricing["cache_read"]
        + out / _MTOK * pricing["output"]
    )
    if batched:
        cost *= pricing["batch_discount"]
    return cost.quantize(_CENT6, rounding=ROUND_HALF_UP)


# ── spend aggregates (for the admin dashboard + budget alert) — all SQL ──────


def _month_period(as_of: datetime.date | None = None) -> str:
    day = as_of or datetime.date.today()
    return day.strftime("%Y-%m")


def budget_for(session: Session, period: str | None = None) -> dict[str, Any]:
    """The active budget for a month: the month row if present, else 'default'."""
    period = period or _month_period()
    row = session.execute(
        text(
            "SELECT period, limit_usd, alert_pct FROM app.llm_budget "
            "WHERE period = :p ORDER BY period DESC LIMIT 1"
        ),
        {"p": period},
    ).one_or_none()
    if row is None:
        row = session.execute(
            text("SELECT period, limit_usd, alert_pct FROM app.llm_budget WHERE period = 'default'")
        ).one_or_none()
    if row is None:
        return {"period": period, "limit_usd": None, "alert_pct": 80}
    return {
        "period": period,
        "limit_usd": Decimal(row.limit_usd),
        "alert_pct": int(row.alert_pct),
    }


def month_spend(session: Session, period: str | None = None) -> Decimal:
    """Total cost_usd recorded in the given month (UTC), to the cent6."""
    period = period or _month_period()
    spent = session.execute(
        text(
            "SELECT coalesce(sum(cost_usd), 0) FROM audit.ai_log "
            "WHERE to_char(created_at, 'YYYY-MM') = :p"
        ),
        {"p": period},
    ).scalar_one()
    return Decimal(spent)


def budget_status(session: Session, period: str | None = None) -> dict[str, Any]:
    """Spend vs budget for a month: limit, spent, and pct (None if no limit)."""
    period = period or _month_period()
    budget = budget_for(session, period)
    spent = month_spend(session, period)
    limit = budget["limit_usd"]
    pct = None
    if limit is not None and limit > 0:
        pct = float((spent / limit * 100).quantize(Decimal("0.1")))
    return {
        "period": period,
        "limit_usd": limit,
        "alert_pct": budget["alert_pct"],
        "spent_usd": spent,
        "pct": pct,
    }


def usage_aggregates(
    session: Session,
    date_from: datetime.date,
    date_to: datetime.date,
    group_by: str = "feature",
) -> dict[str, Any]:
    """Spend + token + call aggregates over a date range, grouped (SQL only)."""
    column = {"feature": "feature", "model": "model", "user": "user_id"}.get(group_by, "feature")
    params = {"f": date_from, "t": date_to}
    total = session.execute(
        text(
            "SELECT coalesce(sum(cost_usd),0) AS cost_usd, "
            "       coalesce(sum(input_tokens),0) AS input_tokens, "
            "       coalesce(sum(output_tokens),0) AS output_tokens, "
            "       count(*) AS calls "
            "FROM audit.ai_log WHERE created_at::date BETWEEN :f AND :t"
        ),
        params,
    ).one()
    groups = session.execute(
        text(
            f"SELECT {column}::text AS key, coalesce(sum(cost_usd),0) AS cost_usd, "
            "       count(*) AS calls, coalesce(sum(input_tokens),0) AS input_tokens, "
            "       coalesce(sum(output_tokens),0) AS output_tokens "
            "FROM audit.ai_log WHERE created_at::date BETWEEN :f AND :t "
            f"GROUP BY {column} ORDER BY cost_usd DESC"
        ),
        params,
    ).all()
    trend = session.execute(
        text(
            "SELECT created_at::date AS day, coalesce(sum(cost_usd),0) AS cost_usd "
            "FROM audit.ai_log WHERE created_at::date BETWEEN :f AND :t "
            "GROUP BY day ORDER BY day"
        ),
        params,
    ).all()
    return {
        "total": {
            "cost_usd": Decimal(total.cost_usd),
            "input_tokens": int(total.input_tokens),
            "output_tokens": int(total.output_tokens),
            "calls": int(total.calls),
        },
        "groups": [
            {
                "key": row.key,
                "cost_usd": Decimal(row.cost_usd),
                "calls": int(row.calls),
                "input_tokens": int(row.input_tokens),
                "output_tokens": int(row.output_tokens),
            }
            for row in groups
        ],
        "trend": [{"day": row.day.isoformat(), "cost_usd": Decimal(row.cost_usd)} for row in trend],
    }


def cost_per_useful_task(
    session: Session, date_from: datetime.date, date_to: datetime.date
) -> dict[str, Any]:
    """Spend ÷ tasks reps actually acted on (task_log outcome→done) in the range.

    The metric that matters (llm-cost.md §7): value, not just size of the bill.
    """
    spent = session.execute(
        text(
            "SELECT coalesce(sum(cost_usd),0) FROM audit.ai_log "
            "WHERE created_at::date BETWEEN :f AND :t"
        ),
        {"f": date_from, "t": date_to},
    ).scalar_one()
    useful = session.execute(
        text(
            "SELECT count(DISTINCT task_id) FROM audit.task_log "
            "WHERE event = 'outcome' AND payload->>'status' = 'done' "
            "AND at::date BETWEEN :f AND :t"
        ),
        {"f": date_from, "t": date_to},
    ).scalar_one()
    spent = Decimal(spent)
    value = None
    if useful:
        value = float((spent / Decimal(useful)).quantize(_CENT6))
    return {"cost_usd": spent, "useful_tasks": int(useful), "value": value}


def recent_calls(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    """The most expensive recent calls — for spotting runaways (admin list)."""
    rows = session.execute(
        text(
            "SELECT id, created_at, model, tier, feature, user_id, input_tokens, "
            "       output_tokens, cached, batched, cost_usd, latency_ms "
            "FROM audit.ai_log WHERE cost_usd IS NOT NULL "
            "ORDER BY cost_usd DESC, id DESC LIMIT :n"
        ),
        {"n": limit},
    ).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "model": r.model,
            "tier": r.tier,
            "feature": r.feature,
            "user_id": r.user_id,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cached": r.cached,
            "batched": r.batched,
            "cost_usd": Decimal(r.cost_usd) if r.cost_usd is not None else None,
            "latency_ms": r.latency_ms,
        }
        for r in rows
    ]
