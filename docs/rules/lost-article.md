# Rule: lost_article

**Register:** analiza · **Entity:** customer × article · **Source tables:** `core.cust_article_cadence`, `core.invoice`, `core.invoice_line`, `core.article`, `core.article_alias`

## What it detects

An article a customer used to buy on a regular cadence that has silently disappeared from
their orders — while the customer keeps ordering other things (so the relationship is alive;
only this product was lost, probably to a competitor).

## Logic

1. From `core.cust_article_cadence`: pairs where
   `(as_of - last_seen) >= gap_factor * avg_interval_d`
   AND `avg_interval_d >= min_avg_interval_d` (cadence is meaningful)
   AND the pair has at least `min_purchases` distinct purchase dates.
2. **Customer-still-active guard**: the customer has ≥ 1 invoice **after** `last_seen`
   (otherwise it's a sleeping customer, not a lost article).
3. **Code-swap guard**: the article's `code` must NOT appear in `core.article_alias.old_code`
   — a swapped code is a catalog change, not a lost sale. (The replacement article continues
   the purchases under its new id.)

## Thresholds (`app.rule_config`, rule = `lost_article`)

| Param | Default | Meaning |
|---|---|---|
| `gap_factor` | 3.0 | gap since last purchase ≥ this × the article's cadence |
| `min_purchases` | 4 | distinct purchase dates required before the loss |
| `min_avg_interval_d` | 5 | ignore articles bought more often than this (noise) |
| `conf_at_gap_factor` | 0.50 | confidence when the gap is exactly `gap_factor` × cadence |
| `conf_per_extra_gap` | 0.10 | added per extra cadence-multiple of silence (cap 0.95) |

## Evidence payload

```json
{ "metric": "article_gap", "article_code": "ART-0068", "article_name": "…",
  "last_seen": "2026-01-27", "avg_interval_d": 13.2, "gap_days": 126, "gap_ratio": 9.5,
  "purchases_before_loss": 32, "invoices_since": [2101, 2188, ...],
  "period": {"from": "2026-01-27", "to": "2026-06-02"},
  "code_swap_check": {"is_swapped": false} }
```

## Confidence

In SQL: `conf_at_gap_factor + conf_per_extra_gap × (gap_ratio − gap_factor)`, capped at 0.95.

## Must NOT fire (guards)

- **Code-swapped articles** (old code present in `article_alias`).
- Articles of customers who stopped ordering entirely (sleeping — no invoices after last_seen).
- Pairs with fewer than `min_purchases` purchases or cadence < `min_avg_interval_d`.
- Dedup / active learned-rule suppressions.
