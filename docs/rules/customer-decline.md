# Rule: customer_decline

**Register:** analiza · **Entity:** customer · **Source tables:** `core.customer_metrics`, `core.invoice`

## What it detects

A customer whose recent revenue has dropped substantially below their own normal level:
the last-60-days turnover is well below their 6-month baseline — and the drop is **not**
explained by seasonality (the same period last year was normal for them).

## Logic (SQL over metrics; numbers never computed by the LLM)

1. From `core.customer_metrics`: candidates where
   `turnover_60d / turnover_6m_avg_60d < decline_ratio_threshold`
   AND `turnover_6m_avg_60d >= min_baseline_60d`
   AND `turnover_60d > 0` (zero recent turnover is the sleeping rule's territory).
2. **Seasonal guard**: compute (in SQL, from `core.invoice`) the customer's turnover in the
   same 60-day window one year earlier (`(as_of-425d, as_of-365d]`). If
   `turnover_60d / same_window_last_year >= seasonal_yoy_tolerance`, the current level is
   normal for the season → **do not fire**.
3. Evidence collects the exact invoice ids in the 60-day window and both windows' values.

## Thresholds (`app.rule_config`, rule = `customer_decline`)

| Param | Default | Meaning |
|---|---|---|
| `decline_ratio_threshold` | 0.65 | fire when 60d/baseline ratio is below this |
| `min_baseline_60d` | 500 | (KM) ignore customers with a smaller baseline |
| `seasonal_yoy_tolerance` | 0.75 | YoY ratio at/above this ⇒ seasonal ⇒ no signal |
| `conf_at_threshold` | 0.40 | confidence when ratio == threshold |
| `conf_at_floor` | 0.90 | confidence when ratio <= floor |
| `conf_floor_ratio` | 0.35 | the ratio at which confidence reaches `conf_at_floor` |

## Evidence payload

```json
{ "metric": "turnover_60d", "value": 14155.90, "baseline": 31660.97, "ratio": 0.447,
  "delta_pct": -55.3, "invoices": [311, 384, ...],
  "period": {"from": "2026-04-03", "to": "2026-06-02"},
  "seasonal_check": {"same_window_last_year": 30122.50, "yoy_ratio": 0.470, "seasonal": false} }
```

## Confidence

Linear interpolation computed **in SQL**, anchored by config:
ratio == `decline_ratio_threshold` → `conf_at_threshold`; ratio <= `conf_floor_ratio` →
`conf_at_floor`; in between, linear. Band via global `conf_band_high` / `conf_band_mid`.

## Must NOT fire (guards)

- **Seasonal customers** (yearly pattern: same-window-last-year comparable to now).
- Customers with `turnover_60d = 0` (sleeping rule's case).
- Customers with baseline below `min_baseline_60d` (too small to matter).
- Customers already covered by an open signal of this rule (dedup) or an active
  `app.learned_rule` suppression matching this rule/customer.
