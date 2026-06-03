-- Recompute core.client_expectation for a given :as_of date (CI2).
--
-- Per customer, a snapshot of what VALERI expects: the typical order interval,
-- the categories normally bought, the current gap since the last order, the
-- stretch ratio (gap ÷ expected interval), and an early-decline flag when the
-- stretch crosses the rule_config threshold. Every figure is SQL — never the LLM.
-- Runs AFTER core.customer_metrics (it reads avg_order_interval_d / last_order).

INSERT INTO core.client_expectation
    (customer_id, expected_interval_d, expected_categories, gap_days, stretch_ratio,
     early_decline, computed_at)
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of,
           (SELECT (value::text)::numeric
            FROM app.rule_config
            WHERE rule = 'client_expectation' AND param = 'early_decline_stretch') AS early_stretch
),
cats AS (
    SELECT i.customer_id,
           jsonb_agg(DISTINCT cat.name) FILTER (WHERE cat.name IS NOT NULL) AS categories
    FROM core.invoice i
    JOIN core.invoice_line l ON l.invoice_id = i.id
    JOIN core.article a ON a.id = l.article_id
    LEFT JOIN core.category cat ON cat.id = a.category_id
    GROUP BY i.customer_id
)
SELECT m.customer_id,
       m.avg_order_interval_d AS expected_interval_d,
       COALESCE(cats.categories, '[]'::jsonb) AS expected_categories,
       (p.as_of - m.last_order_date) AS gap_days,
       CASE
           WHEN m.avg_order_interval_d > 0 AND m.last_order_date IS NOT NULL
           THEN ROUND((p.as_of - m.last_order_date) / m.avg_order_interval_d, 3)
       END AS stretch_ratio,
       CASE
           WHEN m.avg_order_interval_d > 0 AND m.last_order_date IS NOT NULL
                AND p.early_stretch IS NOT NULL
           THEN (p.as_of - m.last_order_date) / m.avg_order_interval_d >= p.early_stretch
           ELSE false
       END AS early_decline,
       now()
FROM core.customer_metrics m
CROSS JOIN params p
LEFT JOIN cats ON cats.customer_id = m.customer_id
