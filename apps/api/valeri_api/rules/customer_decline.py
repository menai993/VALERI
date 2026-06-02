"""Rule: customer_decline — revenue drop vs own baseline, with seasonal guard.

Spec: docs/rules/customer-decline.md. All numbers (values, ratios, confidence)
are computed in SQL; thresholds come from app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import SignalDraft, load_rule_config

RULE_NAME = "customer_decline"

_SQL = """
WITH params AS (
    SELECT CAST(:decline_ratio_threshold AS numeric) AS threshold,
           CAST(:min_baseline_60d AS numeric)        AS min_baseline,
           CAST(:seasonal_yoy_tolerance AS numeric)  AS yoy_tolerance,
           CAST(:conf_at_threshold AS numeric)       AS conf_at_threshold,
           CAST(:conf_at_floor AS numeric)           AS conf_at_floor,
           CAST(:conf_floor_ratio AS numeric)        AS conf_floor_ratio,
           CAST(:as_of AS date)                      AS as_of
),
candidates AS (
    SELECT m.customer_id,
           m.turnover_60d,
           m.turnover_6m_avg_60d AS baseline,
           m.turnover_60d / m.turnover_6m_avg_60d AS ratio
    FROM core.customer_metrics m, params p
    WHERE m.turnover_6m_avg_60d >= p.min_baseline
      AND m.turnover_60d > 0
      AND m.turnover_60d / m.turnover_6m_avg_60d < p.threshold
),
yoy AS (
    SELECT c.customer_id, COALESCE(SUM(i.total), 0) AS same_window_last_year
    FROM candidates c
    CROSS JOIN params p
    LEFT JOIN core.invoice i
      ON i.customer_id = c.customer_id
     AND i.date >  p.as_of - 425
     AND i.date <= p.as_of - 365
    GROUP BY c.customer_id
),
window_invoices AS (
    SELECT c.customer_id, ARRAY_AGG(i.id ORDER BY i.date) AS invoice_ids
    FROM candidates c
    CROSS JOIN params p
    JOIN core.invoice i
      ON i.customer_id = c.customer_id
     AND i.date >  p.as_of - 60
     AND i.date <= p.as_of
    GROUP BY c.customer_id
)
SELECT c.customer_id,
       c.turnover_60d,
       c.baseline,
       ROUND(c.ratio, 3)             AS ratio,
       ROUND((c.ratio - 1) * 100, 1) AS delta_pct,
       y.same_window_last_year,
       CASE WHEN y.same_window_last_year > 0
            THEN ROUND(c.turnover_60d / y.same_window_last_year, 3) END AS yoy_ratio,
       w.invoice_ids,
       ROUND(LEAST(p.conf_at_floor, GREATEST(p.conf_at_threshold,
           p.conf_at_threshold + (p.conf_at_floor - p.conf_at_threshold)
             * (p.threshold - c.ratio) / NULLIF(p.threshold - p.conf_floor_ratio, 0)
       )), 3)                        AS confidence,
       (p.as_of - 60)::text          AS period_from,
       p.as_of::text                 AS period_to
FROM candidates c
CROSS JOIN params p
JOIN yoy y ON y.customer_id = c.customer_id
LEFT JOIN window_invoices w ON w.customer_id = c.customer_id
WHERE y.same_window_last_year = 0
   OR c.turnover_60d / y.same_window_last_year < p.yoy_tolerance
ORDER BY c.ratio
"""


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    rows = session.execute(text(_SQL), {"as_of": as_of, **config}).all()

    return [
        SignalDraft(
            rule=RULE_NAME,
            customer_id=row.customer_id,
            evidence={
                "metric": "turnover_60d",
                "value": row.turnover_60d,
                "baseline": row.baseline,
                "ratio": row.ratio,
                "delta_pct": row.delta_pct,
                "invoices": list(row.invoice_ids or []),
                "period": {"from": row.period_from, "to": row.period_to},
                "seasonal_check": {
                    "same_window_last_year": row.same_window_last_year,
                    "yoy_ratio": row.yoy_ratio,
                    "seasonal": False,
                },
            },
            confidence=Decimal(row.confidence),
            register="analiza",
        )
        for row in rows
    ]
