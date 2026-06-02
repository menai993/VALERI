# Rule: sleeping_customer

**Register:** analiza · **Entity:** customer · **Source tables:** `core.customer_metrics`, `core.invoice`

## What it detects

A customer with a long, regular ordering history who has stopped ordering altogether —
silence for several times their own normal ordering interval. The relationship is going
cold; a win-back action is needed.

## Logic

From `core.customer_metrics` (+ invoice count in SQL): fire when
`(as_of - last_order_date) >= GREATEST(min_gap_days, gap_factor * avg_order_interval_d)`
AND distinct order dates ≥ `min_history_orders`
AND `customer.status = 'active'`.

## Thresholds (`app.rule_config`, rule = `sleeping_customer`)

| Param | Default | Meaning |
|---|---|---|
| `gap_factor` | 3.0 | silence ≥ this × the customer's own average interval |
| `min_gap_days` | 60 | and at least this many days in absolute terms |
| `min_history_orders` | 10 | distinct order dates required (a real history, not a one-off buyer) |
| `conf_at_min` | 0.50 | confidence at exactly the firing threshold |
| `conf_per_extra_gap` | 0.10 | added per extra interval-multiple of silence (cap 0.95) |

## Evidence payload

```json
{ "metric": "order_gap", "last_order_date": "2026-02-20", "avg_order_interval_d": 7.9,
  "gap_days": 102, "gap_ratio": 12.9, "order_count": 57,
  "invoices": [1804, 1815, 1822],
  "period": {"from": "2026-02-20", "to": "2026-06-02"} }
```
(`invoices` = the customer's last few invoices before going quiet — proof of the prior cadence.)

## Confidence

In SQL: `conf_at_min + conf_per_extra_gap × (gap_ratio − gap_factor)`, capped at 0.95.

## Must NOT fire (guards)

- Customers without a real history (< `min_history_orders` orders).
- Customers whose silence is shorter than both thresholds (e.g. slow-cadence school that
  simply hasn't been due yet).
- Customers with `status != 'active'` (already known inactive/closed).
- Dedup / active learned-rule suppressions.
