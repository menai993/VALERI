"""Rule: lost_article — a regularly-bought article that disappeared (code-swap guarded).

Spec: docs/rules/lost-article.md. All numbers computed in SQL; thresholds from
app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import GLOBAL_RULE, SignalDraft, load_rule_config

RULE_NAME = "lost_article"

_SQL = """
WITH params AS (
    SELECT CAST(:gap_factor AS numeric)         AS gap_factor,
           CAST(:min_purchases AS int)          AS min_purchases,
           CAST(:min_avg_interval_d AS numeric) AS min_interval,
           CAST(:conf_at_gap_factor AS numeric) AS conf_base,
           CAST(:conf_per_extra_gap AS numeric) AS conf_step,
           CAST(:conf_cap AS numeric)           AS conf_cap,
           CAST(:as_of AS date)                 AS as_of
),
purchase_counts AS (
    SELECT i.customer_id, l.article_id, COUNT(DISTINCT i.date) AS n_purchases
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    GROUP BY i.customer_id, l.article_id
),
candidates AS (
    SELECT cac.customer_id, cac.article_id, cac.avg_interval_d, cac.last_seen,
           (p.as_of - cac.last_seen)                      AS gap_days,
           (p.as_of - cac.last_seen) / cac.avg_interval_d AS gap_ratio,
           pc.n_purchases
    FROM core.cust_article_cadence cac
    CROSS JOIN params p
    JOIN purchase_counts pc
      ON pc.customer_id = cac.customer_id AND pc.article_id = cac.article_id
    WHERE cac.avg_interval_d IS NOT NULL
      AND cac.avg_interval_d >= p.min_interval
      AND pc.n_purchases >= p.min_purchases
      AND (p.as_of - cac.last_seen) >= p.gap_factor * cac.avg_interval_d
),
not_swapped AS (
    -- code-swap guard: a retired (aliased) code is a catalog change, not a lost sale
    SELECT c.*, a.code AS article_code, a.name AS article_name
    FROM candidates c
    JOIN core.article a ON a.id = c.article_id
    LEFT JOIN core.article_alias alias ON alias.old_code = a.code
    WHERE alias.old_code IS NULL
),
active_since AS (
    -- customer-still-active guard: they keep ordering other things
    SELECT ns.customer_id, ns.article_id,
           (ARRAY_AGG(i.id ORDER BY i.date DESC))[1:5] AS invoices_since
    FROM not_swapped ns
    JOIN core.invoice i ON i.customer_id = ns.customer_id AND i.date > ns.last_seen
    GROUP BY ns.customer_id, ns.article_id
)
SELECT ns.customer_id, ns.article_id, ns.article_code, ns.article_name,
       ns.last_seen::text       AS last_seen,
       ns.avg_interval_d,
       ns.gap_days,
       ROUND(ns.gap_ratio, 2)   AS gap_ratio,
       ns.n_purchases,
       a.invoices_since,
       ROUND(LEAST(p.conf_cap,
                   p.conf_base + p.conf_step * (ns.gap_ratio - p.gap_factor)), 3) AS confidence,
       ns.last_seen::text       AS period_from,
       p.as_of::text            AS period_to
FROM not_swapped ns
CROSS JOIN params p
JOIN active_since a ON a.customer_id = ns.customer_id AND a.article_id = ns.article_id
ORDER BY ns.gap_ratio DESC
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
            article_id=row.article_id,
            evidence={
                "metric": "article_gap",
                "article_code": row.article_code,
                "article_name": row.article_name,
                "last_seen": row.last_seen,
                "avg_interval_d": row.avg_interval_d,
                "gap_days": row.gap_days,
                "gap_ratio": row.gap_ratio,
                "purchases_before_loss": row.n_purchases,
                "invoices_since": list(row.invoices_since or []),
                "period": {"from": row.period_from, "to": row.period_to},
                "code_swap_check": {"is_swapped": False},
            },
            confidence=Decimal(row.confidence),
            register="analiza",
        )
        for row in rows
    ]
