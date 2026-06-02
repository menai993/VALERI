"""Rule: lost_category — a whole category the customer stopped buying.

Spec: docs/rules/lost-category.md. All numbers computed in SQL; thresholds from
app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import GLOBAL_RULE, SignalDraft, load_rule_config

RULE_NAME = "lost_category"

_SQL = """
WITH params AS (
    SELECT CAST(:gap_days AS int)          AS gap_days,
           CAST(:min_purchases AS int)     AS min_purchases,
           CAST(:conf_base AS numeric)     AS conf_base,
           CAST(:conf_per_30d AS numeric)  AS conf_per_30d,
           CAST(:conf_cap AS numeric)      AS conf_cap,
           CAST(:as_of AS date)            AS as_of
),
category_purchases AS (
    SELECT i.customer_id, a.category_id,
           MAX(i.date)            AS last_purchase,
           COUNT(DISTINCT i.date) AS n_purchases
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    JOIN core.article a ON a.id = l.article_id
    WHERE a.category_id IS NOT NULL
    GROUP BY i.customer_id, a.category_id
),
candidates AS (
    SELECT cp.customer_id, cp.category_id, cp.last_purchase, cp.n_purchases,
           (p.as_of - cp.last_purchase) AS gap_days_actual
    FROM category_purchases cp
    CROSS JOIN params p
    WHERE cp.n_purchases >= p.min_purchases
      AND (p.as_of - cp.last_purchase) >= p.gap_days
),
still_active AS (
    SELECT c.customer_id, c.category_id,
           (ARRAY_AGG(i.id ORDER BY i.date DESC))[1:5] AS invoices_since
    FROM candidates c
    JOIN core.invoice i ON i.customer_id = c.customer_id AND i.date > c.last_purchase
    GROUP BY c.customer_id, c.category_id
)
SELECT c.customer_id, c.category_id, cat.name AS category_name,
       c.last_purchase::text   AS last_purchase,
       c.gap_days_actual,
       c.n_purchases,
       sa.invoices_since,
       ROUND(LEAST(p.conf_cap,
                   p.conf_base + p.conf_per_30d * (c.gap_days_actual - p.gap_days) / 30.0),
             3)                AS confidence,
       c.last_purchase::text   AS period_from,
       p.as_of::text           AS period_to
FROM candidates c
CROSS JOIN params p
JOIN core.category cat ON cat.id = c.category_id
JOIN still_active sa ON sa.customer_id = c.customer_id AND sa.category_id = c.category_id
ORDER BY c.gap_days_actual DESC
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
                "metric": "category_gap",
                "category_id": row.category_id,
                "category_name": row.category_name,
                "last_purchase": row.last_purchase,
                "gap_days": row.gap_days_actual,
                "purchases_before": row.n_purchases,
                "invoices_since": list(row.invoices_since or []),
                "period": {"from": row.period_from, "to": row.period_to},
            },
            confidence=Decimal(row.confidence),
            register="analiza",
        )
        for row in rows
    ]
