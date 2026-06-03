"""Rule: sleeping_customer — a regular customer who stopped ordering entirely.

Spec: docs/rules/sleeping-customer.md. All numbers computed in SQL; thresholds
from app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import GLOBAL_RULE, SignalDraft, load_rule_config

RULE_NAME = "sleeping_customer"

_SQL = """
WITH params AS (
    SELECT CAST(:gap_factor AS numeric)         AS gap_factor,
           CAST(:min_gap_days AS int)           AS min_gap_days,
           CAST(:min_history_orders AS int)     AS min_history_orders,
           CAST(:conf_at_min AS numeric)        AS conf_at_min,
           CAST(:conf_per_extra_gap AS numeric) AS conf_step,
           CAST(:conf_cap AS numeric)           AS conf_cap,
           CAST(:as_of AS date)                 AS as_of
),
order_history AS (
    SELECT customer_id,
           COUNT(DISTINCT date)                        AS n_orders,
           (ARRAY_AGG(id ORDER BY date DESC))[1:3]     AS recent_invoice_ids
    FROM core.invoice
    GROUP BY customer_id
)
SELECT m.customer_id,
       m.last_order_date::text  AS last_order_date,
       m.avg_order_interval_d,
       (p.as_of - m.last_order_date)  AS gap_days,
       ROUND((p.as_of - m.last_order_date) / m.avg_order_interval_d, 2) AS gap_ratio,
       oh.n_orders,
       oh.recent_invoice_ids,
       ROUND(LEAST(p.conf_cap,
                   p.conf_at_min + p.conf_step *
                   ((p.as_of - m.last_order_date) / m.avg_order_interval_d - p.gap_factor)),
             3)                  AS confidence,
       m.last_order_date::text   AS period_from,
       p.as_of::text             AS period_to
FROM core.customer_metrics m
CROSS JOIN params p
JOIN core.customer c ON c.id = m.customer_id AND c.status = 'active'
JOIN order_history oh ON oh.customer_id = m.customer_id
WHERE m.last_order_date IS NOT NULL
  AND m.avg_order_interval_d IS NOT NULL
  AND m.avg_order_interval_d > 0
  AND oh.n_orders >= p.min_history_orders
  AND (p.as_of - m.last_order_date) >= GREATEST(p.min_gap_days,
                                                p.gap_factor * m.avg_order_interval_d)
ORDER BY gap_ratio DESC
"""


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    global_config = load_rule_config(session, GLOBAL_RULE)
    rows = session.execute(
        text(_SQL), {"as_of": as_of, "conf_cap": global_config["conf_cap"], **config}
    ).all()

    return [
        SignalDraft(
            rule=RULE_NAME,
            customer_id=row.customer_id,
            evidence={
                "metric": "order_gap",
                "last_order_date": row.last_order_date,
                "avg_order_interval_d": row.avg_order_interval_d,
                "gap_days": row.gap_days,
                "gap_ratio": row.gap_ratio,
                "order_count": row.n_orders,
                "invoices": list(row.recent_invoice_ids or []),
                "period": {"from": row.period_from, "to": row.period_to},
            },
            confidence=Decimal(row.confidence),
            register="analiza",
        )
        for row in rows
    ]
