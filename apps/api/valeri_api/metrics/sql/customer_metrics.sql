-- Recompute core.customer_metrics for a given :as_of date.
--
-- Window semantics (half-open intervals, start excluded / end included):
--   60-day window   : (as_of - 60d,  as_of]
--   baseline window : (as_of - 240d, as_of - 60d]   → 180 days, normalised /3 to 60d
-- last_order_date / avg_order_interval_d use all history up to as_of.
-- Same-day invoices count as ONE order event (distinct dates) for intervals.

INSERT INTO core.customer_metrics
    (customer_id, turnover_60d, turnover_6m_avg_60d, last_order_date,
     avg_order_interval_d, segment, computed_at)
WITH order_dates AS (
    SELECT DISTINCT customer_id, date
    FROM core.invoice
    WHERE date <= CAST(:as_of AS date)
),
gaps AS (
    SELECT customer_id,
           date - LAG(date) OVER (PARTITION BY customer_id ORDER BY date) AS gap_days
    FROM order_dates
),
avg_intervals AS (
    SELECT customer_id, AVG(gap_days) AS avg_gap
    FROM gaps
    WHERE gap_days IS NOT NULL
    GROUP BY customer_id
),
turnovers AS (
    SELECT c.id AS customer_id,
           COALESCE(SUM(i.total) FILTER (
               WHERE i.date >  CAST(:as_of AS date) - 60
                 AND i.date <= CAST(:as_of AS date)), 0)       AS turnover_60d,
           COALESCE(SUM(i.total) FILTER (
               WHERE i.date >  CAST(:as_of AS date) - 240
                 AND i.date <= CAST(:as_of AS date) - 60), 0) / 3 AS baseline_60d,
           MAX(i.date) FILTER (WHERE i.date <= CAST(:as_of AS date)) AS last_order_date
    FROM core.customer c
    LEFT JOIN core.invoice i ON i.customer_id = c.id
    GROUP BY c.id
)
SELECT t.customer_id,
       ROUND(t.turnover_60d, 2),
       ROUND(t.baseline_60d, 2),
       t.last_order_date,
       ROUND(a.avg_gap, 2),
       c.segment,
       now()
FROM turnovers t
JOIN core.customer c ON c.id = t.customer_id
LEFT JOIN avg_intervals a ON a.customer_id = t.customer_id
