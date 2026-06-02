"""Rule: narrow_basket — cross-sell recommendation for single-category customers.

Spec: docs/rules/narrow-basket.md. Register: preporuka. All numbers computed in
SQL; thresholds from app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import SignalDraft, load_rule_config

RULE_NAME = "narrow_basket"

_SQL = """
WITH params AS (
    SELECT CAST(:max_categories AS int)           AS max_categories,
           CAST(:min_peer_prevalence AS numeric)  AS min_prevalence,
           CAST(:min_baseline_60d AS numeric)     AS min_baseline,
           CAST(:as_of AS date)                   AS as_of
),
customer_categories AS (
    SELECT DISTINCT i.customer_id, a.category_id, cat.name
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    JOIN core.article a ON a.id = l.article_id
    JOIN core.category cat ON cat.id = a.category_id
    WHERE a.category_id IS NOT NULL
),
basket_width AS (
    SELECT customer_id,
           COUNT(*) AS n_categories,
           JSONB_AGG(JSONB_BUILD_OBJECT('id', category_id, 'name', name)
                     ORDER BY category_id) AS categories_bought
    FROM customer_categories
    GROUP BY customer_id
),
candidates AS (
    SELECT bw.customer_id, bw.n_categories, bw.categories_bought,
           m.segment, m.turnover_6m_avg_60d AS baseline
    FROM basket_width bw
    JOIN core.customer_metrics m ON m.customer_id = bw.customer_id
    CROSS JOIN params p
    WHERE bw.n_categories <= p.max_categories
      AND m.turnover_6m_avg_60d >= p.min_baseline
      AND m.segment IS NOT NULL
),
missing AS (
    SELECT c.customer_id,
           JSONB_AGG(JSONB_BUILD_OBJECT('id', sb.category_id, 'name', cat.name,
                                        'prevalence', sb.prevalence)
                     ORDER BY sb.prevalence DESC) AS missing_categories,
           ROUND(AVG(sb.prevalence), 3)           AS avg_prevalence
    FROM candidates c
    CROSS JOIN params p
    JOIN core.segment_basket sb
      ON sb.segment = c.segment AND sb.prevalence >= p.min_prevalence
    JOIN core.category cat ON cat.id = sb.category_id
    LEFT JOIN customer_categories cc
      ON cc.customer_id = c.customer_id AND cc.category_id = sb.category_id
    WHERE cc.category_id IS NULL
    GROUP BY c.customer_id
)
SELECT c.customer_id, c.n_categories, c.categories_bought, c.segment, c.baseline,
       mi.missing_categories,
       mi.avg_prevalence  AS confidence,
       p.as_of::text      AS period_to
FROM candidates c
CROSS JOIN params p
JOIN missing mi ON mi.customer_id = c.customer_id
ORDER BY mi.avg_prevalence DESC
"""


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    rows = session.execute(text(_SQL), {"as_of": as_of, **config}).all()

    return [
        SignalDraft(
            rule=RULE_NAME,
            customer_id=row.customer_id,
            evidence={
                "metric": "basket_width",
                "categories_bought": row.categories_bought,
                "n_categories": row.n_categories,
                "segment": row.segment,
                "missing_categories": row.missing_categories,
                "baseline_60d": row.baseline,
                "period": {"from": None, "to": row.period_to},
            },
            confidence=Decimal(row.confidence),
            register="preporuka",
        )
        for row in rows
    ]
