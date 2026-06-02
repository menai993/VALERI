-- Recompute core.segment_basket for a given :as_of date.
--
-- prevalence = share of the segment's buying customers (≥1 invoice) that have
-- ever bought at least one article of the category, up to :as_of.
-- Only rows with prevalence > 0 are produced (a category nobody in the segment
-- buys simply has no row).

INSERT INTO core.segment_basket (segment, category_id, prevalence)
WITH segment_buyers AS (
    SELECT DISTINCT c.segment, c.id AS customer_id
    FROM core.customer c
    JOIN core.invoice i ON i.customer_id = c.id
    WHERE c.segment IS NOT NULL
      AND i.date <= CAST(:as_of AS date)
),
segment_sizes AS (
    SELECT segment, COUNT(*) AS n_customers
    FROM segment_buyers
    GROUP BY segment
),
category_buyers AS (
    SELECT DISTINCT c.segment, a.category_id, c.id AS customer_id
    FROM core.customer c
    JOIN core.invoice i ON i.customer_id = c.id
    JOIN core.invoice_line l ON l.invoice_id = i.id
    JOIN core.article a ON a.id = l.article_id
    WHERE c.segment IS NOT NULL
      AND a.category_id IS NOT NULL
      AND i.date <= CAST(:as_of AS date)
)
SELECT cb.segment,
       cb.category_id,
       ROUND(COUNT(DISTINCT cb.customer_id)::numeric / s.n_customers, 4) AS prevalence
FROM category_buyers cb
JOIN segment_sizes s ON s.segment = cb.segment
GROUP BY cb.segment, cb.category_id, s.n_customers
