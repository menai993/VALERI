-- Weekly owner report aggregates (M7).
--
-- Every number the report shows is computed HERE (principle 1) — the LLM only
-- narrates these finished values. All queries are parameterised by
-- :week_start / :week_end (a Monday–Sunday week) and, where they list rows,
-- by :top_n (a report layout constant, see builder.py).
--
-- Evidence values read from app.signal.evidence are themselves SQL-computed
-- (by the M4 detection rules) — extracting them here is pass-through, not
-- computation.
--
-- The file is split into named queries on '-- name:' markers (builder._load_queries).

-- name: kpi
WITH params AS (
    SELECT CAST(:week_start AS date) AS week_start,
           CAST(:week_end AS date)   AS week_end
),
this_week AS (
    SELECT COALESCE(SUM(i.total), 0) AS revenue
    FROM core.invoice i, params p
    WHERE i.date BETWEEN p.week_start AND p.week_end
),
prior_week AS (
    SELECT COALESCE(SUM(i.total), 0) AS revenue
    FROM core.invoice i, params p
    WHERE i.date BETWEEN p.week_start - 7 AND p.week_start - 1
),
week_signals AS (
    SELECT COUNT(*)                                                AS new_signals,
           COUNT(*) FILTER (WHERE s.rule = 'customer_decline')     AS n_declines,
           COUNT(*) FILTER (WHERE s.rule = 'lost_article')         AS n_lost_articles,
           COUNT(*) FILTER (WHERE s.rule = 'sleeping_customer')    AS n_sleeping
    FROM app.signal s, params p
    WHERE s.created_at::date BETWEEN p.week_start AND p.week_end
),
week_tasks AS (
    SELECT COUNT(*) AS new_tasks
    FROM app.task t, params p
    WHERE t.created_at::date BETWEEN p.week_start AND p.week_end
),
open_tasks AS (
    SELECT COUNT(*) AS open_tasks
    FROM app.task
    WHERE status = 'open'
)
SELECT tw.revenue                                  AS week_revenue,
       pw.revenue                                  AS prior_week_revenue,
       CASE WHEN pw.revenue > 0
            THEN ROUND((tw.revenue / pw.revenue - 1) * 100, 1)
       END                                         AS revenue_delta_pct,
       ws.new_signals,
       ws.n_declines,
       ws.n_lost_articles,
       ws.n_sleeping,
       wt.new_tasks,
       ot.open_tasks
FROM this_week tw, prior_week pw, week_signals ws, week_tasks wt, open_tasks ot

-- name: top_declines
SELECT s.id                                  AS signal_id,
       s.customer_id,
       c.name                                AS customer_name,
       c.segment,
       (s.evidence->>'value')::numeric       AS value,
       (s.evidence->>'baseline')::numeric    AS baseline,
       (s.evidence->>'delta_pct')::numeric   AS delta_pct,
       s.confidence,
       s.conf_band
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
WHERE s.rule = 'customer_decline'
  AND s.created_at::date BETWEEN CAST(:week_start AS date) AND CAST(:week_end AS date)
ORDER BY (s.evidence->>'baseline')::numeric - (s.evidence->>'value')::numeric DESC
LIMIT :top_n

-- name: lost_articles
SELECT s.id                                       AS signal_id,
       s.customer_id,
       c.name                                     AS customer_name,
       c.segment,
       s.evidence->>'article_name'                AS article_name,
       s.evidence->>'article_code'                AS article_code,
       (s.evidence->>'avg_interval_d')::numeric   AS avg_interval_d,
       (s.evidence->>'gap_days')::int             AS gap_days,
       s.evidence->>'last_seen'                   AS last_seen,
       s.confidence,
       s.conf_band
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
WHERE s.rule = 'lost_article'
  AND s.created_at::date BETWEEN CAST(:week_start AS date) AND CAST(:week_end AS date)
ORDER BY s.confidence DESC, s.id
LIMIT :top_n

-- name: sleeping_customers
SELECT s.id                                            AS signal_id,
       s.customer_id,
       c.name                                          AS customer_name,
       c.segment,
       s.evidence->>'last_order_date'                  AS last_order_date,
       (s.evidence->>'gap_days')::int                  AS gap_days,
       (s.evidence->>'avg_order_interval_d')::numeric  AS avg_order_interval_d,
       (s.evidence->>'order_count')::int               AS order_count,
       s.confidence,
       s.conf_band
FROM app.signal s
JOIN core.customer c ON c.id = s.customer_id
WHERE s.rule = 'sleeping_customer'
  AND s.created_at::date BETWEEN CAST(:week_start AS date) AND CAST(:week_end AS date)
ORDER BY (s.evidence->>'gap_days')::int DESC, s.id
LIMIT :top_n

-- name: task_stats
SELECT COUNT(*)                                          AS total,
       COUNT(*) FILTER (WHERE t.status = 'open')         AS open,
       COUNT(*) FILTER (WHERE t.status = 'in_progress')  AS in_progress,
       COUNT(*) FILTER (WHERE t.status = 'done')         AS done,
       COUNT(*) FILTER (WHERE t.status = 'dismissed')    AS dismissed
FROM app.task t
WHERE t.created_at::date BETWEEN CAST(:week_start AS date) AND CAST(:week_end AS date)

-- name: top_tasks
SELECT t.id            AS task_id,
       t.title,
       t.status        AS task_status,
       t.due_date,
       t.owner_cc,
       r.name          AS assignee_name,
       s.rule,
       s.customer_id,
       c.name          AS customer_name,
       c.segment,
       s.confidence
FROM app.task t
LEFT JOIN app.signal s ON s.id = t.signal_id
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN core.sales_rep r ON r.id = t.assignee_id
WHERE t.created_at::date BETWEEN CAST(:week_start AS date) AND CAST(:week_end AS date)
ORDER BY t.owner_cc DESC, s.confidence DESC NULLS LAST, t.id
LIMIT :top_n

-- name: pending_drafts
SELECT a.id            AS approval_id,
       a.task_id,
       a.kind,
       a.status        AS approval_status,
       a.payload,
       s.rule,
       s.customer_id,
       c.name          AS customer_name
FROM app.approval a
LEFT JOIN app.task t ON t.id = a.task_id
LEFT JOIN app.signal s ON s.id = t.signal_id
LEFT JOIN core.customer c ON c.id = s.customer_id
WHERE a.kind = 'message'
  AND a.status IN ('draft', 'pending_approval')
ORDER BY a.id
