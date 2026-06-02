-- Recompute core.cust_article_cadence for a given :as_of date.
--
-- Per (customer, article): average gap between consecutive DISTINCT purchase
-- dates (window function LAG), and the last date the article was bought.
-- avg_interval_d is NULL when the pair has fewer than 2 distinct purchase dates.

INSERT INTO core.cust_article_cadence (customer_id, article_id, avg_interval_d, last_seen)
WITH purchase_dates AS (
    SELECT DISTINCT i.customer_id, l.article_id, i.date
    FROM core.invoice_line l
    JOIN core.invoice i ON i.id = l.invoice_id
    WHERE i.date <= CAST(:as_of AS date)
),
gaps AS (
    SELECT customer_id,
           article_id,
           date,
           date - LAG(date) OVER (
               PARTITION BY customer_id, article_id ORDER BY date
           ) AS gap_days
    FROM purchase_dates
)
SELECT customer_id,
       article_id,
       ROUND(AVG(gap_days), 2),   -- AVG ignores NULLs; all-NULL (single purchase) → NULL
       MAX(date)
FROM gaps
GROUP BY customer_id, article_id
