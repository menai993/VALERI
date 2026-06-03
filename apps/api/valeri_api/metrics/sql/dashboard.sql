-- Dashboard & metrics-API aggregates (M8).
--
-- Every number the Početna dashboard and the metrics endpoints show is computed
-- HERE (principle 1) — the API only passes these values through. Queries are
-- parameterised by :as_of (reference date) and, where row lists support
-- rep scoping, by :scoped/:customer_ids (RBAC row-level scope).
--
-- Evidence values read from app.signal.evidence are themselves SQL-computed by
-- the M4 detection rules — extracting them here is pass-through, not computation.
--
-- The file is split into named queries on '-- name:' markers.

-- name: kpi_revenue
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of,
           CAST(:range_days AS int) AS range_days
),
current_window AS (
    SELECT COALESCE(SUM(i.total), 0) AS value
    FROM core.invoice i, params p
    WHERE i.date > p.as_of - p.range_days AND i.date <= p.as_of
),
prior_window AS (
    SELECT COALESCE(SUM(i.total), 0) AS value
    FROM core.invoice i, params p
    WHERE i.date > p.as_of - 2 * p.range_days AND i.date <= p.as_of - p.range_days
)
SELECT ROUND(c.value, 2)  AS value,
       ROUND(p.value, 2)  AS prior_value,
       CASE WHEN p.value > 0
            THEN ROUND((c.value / p.value - 1) * 100, 1)
       END                AS delta_pct
FROM current_window c, prior_window p

-- name: kpi_revenue_spark
-- Weekly revenue totals for the last 8 weeks (oldest week first).
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of
)
SELECT gs.week_offset,
       COALESCE(SUM(i.total), 0) AS value
FROM generate_series(7, 0, -1) AS gs(week_offset)
CROSS JOIN params p
LEFT JOIN core.invoice i
  ON i.date >  p.as_of - (gs.week_offset + 1) * 7
 AND i.date <= p.as_of - gs.week_offset * 7
GROUP BY gs.week_offset
ORDER BY gs.week_offset DESC

-- name: kpi_signals
-- Open detection counts (the MVP recovery tiles).
SELECT COUNT(DISTINCT s.customer_id) FILTER (
           WHERE s.rule = 'customer_decline' AND s.status IN ('new', 'tasked')
       )                                                       AS declining_customers,
       COUNT(*) FILTER (
           WHERE s.rule = 'lost_article' AND s.status IN ('new', 'tasked')
       )                                                       AS lost_articles_open,
       COUNT(*) FILTER (
           WHERE s.rule = 'sleeping_customer' AND s.status IN ('new', 'tasked')
       )                                                       AS sleeping_open
FROM app.signal s

-- name: kpi_tasks
SELECT COUNT(*) FILTER (WHERE t.status = 'open')                                  AS open_tasks,
       COUNT(*) FILTER (WHERE t.status = 'open' AND t.due_date <= CAST(:as_of AS date))
                                                                                  AS due_tasks,
       COUNT(*) FILTER (WHERE t.status = 'done')                                  AS done_tasks,
       COUNT(*)                                                                   AS total_tasks
FROM app.task t

-- name: revenue_trend
-- Monthly revenue for the last 12 months + the same month one year earlier
-- (the dashed comparison line), oldest month first.
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of
),
months AS (
    SELECT (date_trunc('month', p.as_of) - make_interval(months => n))::date AS month_start,
           (date_trunc('month', p.as_of) - make_interval(months => n - 1))::date AS month_end
    FROM params p, generate_series(11, 0, -1) AS n
)
SELECT to_char(m.month_start, 'YYYY-MM') AS month,
       COALESCE((SELECT ROUND(SUM(i.total), 2) FROM core.invoice i
                 WHERE i.date >= m.month_start AND i.date < m.month_end), 0)  AS revenue,
       COALESCE((SELECT ROUND(SUM(i.total), 2) FROM core.invoice i
                 WHERE i.date >= (m.month_start - INTERVAL '1 year')::date
                   AND i.date <  (m.month_end - INTERVAL '1 year')::date), 0) AS prior_year
FROM months m
ORDER BY m.month_start

-- name: revenue_substats
-- YTD revenue, average monthly revenue and best month over the last 12 months.
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of
),
ytd AS (
    SELECT COALESCE(SUM(i.total), 0) AS value
    FROM core.invoice i, params p
    WHERE i.date >= date_trunc('year', p.as_of)::date AND i.date <= p.as_of
),
monthly AS (
    SELECT date_trunc('month', i.date) AS month, SUM(i.total) AS revenue
    FROM core.invoice i, params p
    WHERE i.date > p.as_of - 365 AND i.date <= p.as_of
    GROUP BY 1
)
SELECT ROUND(y.value, 2)                                AS ytd_revenue,
       ROUND((SELECT AVG(revenue) FROM monthly), 2)     AS avg_monthly,
       ROUND((SELECT MAX(revenue) FROM monthly), 2)     AS best_month
FROM ytd y

-- name: at_risk
-- Customers-at-risk rows from open customer_decline signals.
-- risk_band is a deterministic mapping of conf_band (visoka→visok, ...).
SELECT s.id                                  AS signal_id,
       s.customer_id,
       c.name                                AS customer_name,
       c.segment,
       m.last_order_date,
       (s.evidence->>'value')::numeric       AS value,
       (s.evidence->>'baseline')::numeric    AS baseline,
       (s.evidence->>'delta_pct')::numeric   AS delta_pct,
       CASE s.conf_band::text
            WHEN 'visoka'  THEN 'visok'
            WHEN 'srednja' THEN 'srednji'
            ELSE 'nizak'
       END                                   AS risk_band,
       s.confidence,
       s.conf_band,
       s.register,
       s.evidence
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN core.customer_metrics m ON m.customer_id = s.customer_id
WHERE s.rule = 'customer_decline'
  AND s.status IN ('new', 'tasked')
  AND (CAST(:scoped AS boolean) IS FALSE
       OR s.customer_id = ANY(CAST(:customer_ids AS bigint[])))
ORDER BY (s.evidence->>'baseline')::numeric - (s.evidence->>'value')::numeric DESC
LIMIT :limit

-- name: lost_articles
-- Lost-article rows from open lost_article signals (code-swaps already excluded by M4).
SELECT s.id                                  AS signal_id,
       s.customer_id,
       c.name                                AS customer_name,
       c.segment,
       s.article_id,
       s.evidence->>'article_name'           AS article_name,
       s.evidence->>'article_code'           AS article_code,
       (s.evidence->>'avg_interval_d')::numeric AS avg_interval_d,
       (s.evidence->>'gap_days')::int        AS gap_days,
       s.evidence->>'last_seen'              AS last_seen,
       s.confidence,
       s.conf_band,
       s.register,
       s.evidence
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
WHERE s.rule = 'lost_article'
  AND s.status IN ('new', 'tasked')
  AND (CAST(:customer_id AS bigint) IS NULL OR s.customer_id = :customer_id)
  AND (CAST(:scoped AS boolean) IS FALSE
       OR s.customer_id = ANY(CAST(:customer_ids AS bigint[])))
ORDER BY s.confidence DESC, s.id
LIMIT :limit

-- name: insights
-- The "AI uvidi" list: open signals across all rules, strongest first,
-- each with its task (for the action link) and full evidence envelope.
SELECT s.id                                  AS signal_id,
       s.rule,
       s.customer_id,
       c.name                                AS customer_name,
       c.segment,
       t.id                                  AS task_id,
       t.title                               AS task_title,
       s.confidence,
       s.conf_band,
       s.register,
       s.evidence,
       s.created_at
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN app.task t ON t.signal_id = s.id
WHERE s.status IN ('new', 'tasked')
  AND (CAST(:scoped AS boolean) IS FALSE
       OR s.customer_id = ANY(CAST(:customer_ids AS bigint[])))
ORDER BY s.confidence DESC, s.created_at DESC, s.id
LIMIT :limit

-- name: customer_metrics
-- 360-lite header metrics for one customer.
SELECT m.customer_id,
       c.name                                AS customer_name,
       c.segment,
       c.status,
       m.turnover_60d,
       m.turnover_6m_avg_60d                 AS baseline_60d,
       m.last_order_date,
       m.avg_order_interval_d
FROM core.customer_metrics m
JOIN core.customer c ON c.id = m.customer_id
WHERE m.customer_id = :customer_id

-- name: customer_monthly_turnover
-- Monthly turnover for one customer over the last 12 months (oldest first).
WITH params AS (
    SELECT CAST(:as_of AS date) AS as_of, CAST(:customer_id AS bigint) AS customer_id
),
months AS (
    SELECT (date_trunc('month', p.as_of) - make_interval(months => n))::date AS month_start,
           (date_trunc('month', p.as_of) - make_interval(months => n - 1))::date AS month_end,
           p.customer_id
    FROM params p, generate_series(11, 0, -1) AS n
)
SELECT to_char(m.month_start, 'YYYY-MM') AS month,
       COALESCE((SELECT ROUND(SUM(i.total), 2) FROM core.invoice i
                 WHERE i.customer_id = m.customer_id
                   AND i.date >= m.month_start AND i.date < m.month_end), 0) AS revenue
FROM months m
ORDER BY m.month_start

-- name: customer_basket
-- What the customer buys, by category, over the last 180 days.
SELECT cat.id                                AS category_id,
       cat.name                              AS category_name,
       COUNT(DISTINCT l.article_id)          AS n_articles,
       ROUND(SUM(l.line_total), 2)           AS total_spent
FROM core.invoice_line l
JOIN core.invoice i ON i.id = l.invoice_id
JOIN core.article a ON a.id = l.article_id
LEFT JOIN core.category cat ON cat.id = a.category_id
WHERE i.customer_id = :customer_id
  AND i.date > CAST(:as_of AS date) - 180
  AND i.date <= CAST(:as_of AS date)
GROUP BY cat.id, cat.name
ORDER BY total_spent DESC
