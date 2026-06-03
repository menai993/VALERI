# Rule: lost_category

**Register:** analiza · **Entity:** customer × category · **Source tables:** `core.invoice`, `core.invoice_line`, `core.article`, `core.category`

## What it detects

A whole product category that a customer used to buy repeatedly and has now completely
stopped buying — while still ordering from other categories. Broader than a lost article:
the customer moved an entire need (e.g. all paper goods) to someone else.

## Logic

1. Per (customer, category), in SQL: last purchase date of ANY article in the category,
   and the count of distinct purchase dates.
2. Fire when `(as_of - last_category_purchase) >= gap_days`
   AND distinct purchase dates ≥ `min_purchases`
   AND the customer has ≥ 1 invoice **after** that date (still active).

## Thresholds (`app.rule_config`, rule = `lost_category`)

| Param | Default | Meaning |
|---|---|---|
| `gap_days` | 90 | days of category silence before firing |
| `min_purchases` | 5 | distinct purchase dates the category had before |
| `conf_base` | 0.50 | confidence at exactly `gap_days` of silence |
| `conf_per_30d` | 0.10 | added per extra 30 days of silence (cap 0.95) |

## Evidence payload

```json
{ "metric": "category_gap", "category_id": 4, "category_name": "rukavice",
  "last_purchase": "2026-02-10", "gap_days": 112, "purchases_before": 14,
  "invoices_since": [2204, 2271], "period": {"from": "2026-02-10", "to": "2026-06-02"} }
```

## Confidence

In SQL: `conf_base + conf_per_30d × (gap_days_actual − gap_days) / 30`, capped at 0.95.

## Must NOT fire (guards)

- Customers who stopped ordering entirely (sleeping — handled by sleeping_customer).
- Categories the customer only bought incidentally (< `min_purchases` purchases).
- Dedup / active learned-rule suppressions.
