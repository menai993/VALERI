# Rule: narrow_basket

**Register:** **preporuka** (cross-sell recommendation) · **Entity:** customer · **Source tables:** `core.customer_metrics`, `core.segment_basket`, `core.invoice`, `core.invoice_line`, `core.article`

## What it detects

A worthwhile customer who buys from only one or two categories while most of their segment
peers buy from several — a concrete cross-sell opportunity (the categories the peers buy and
this customer doesn't).

## Logic

1. Per customer, in SQL: the set of distinct categories ever purchased.
2. Fire when the count ≤ `max_categories`
   AND the customer's `turnover_6m_avg_60d >= min_baseline_60d` (worth the effort)
   AND there exists ≥ 1 category in `core.segment_basket` for the customer's segment with
   `prevalence >= min_peer_prevalence` that the customer does NOT buy.
3. The recommended (missing) categories with their peer prevalence go into the evidence.

## Thresholds (`app.rule_config`, rule = `narrow_basket`)

| Param | Default | Meaning |
|---|---|---|
| `max_categories` | 2 | customer buys at most this many categories |
| `min_peer_prevalence` | 0.60 | only recommend categories ≥ this share of segment peers buy |
| `min_baseline_60d` | 300 | (KM) only customers with at least this baseline |

## Evidence payload

```json
{ "metric": "basket_width", "categories_bought": [{"id": 1, "name": "papir"}],
  "n_categories": 1, "segment": "klinika",
  "missing_categories": [{"id": 4, "name": "rukavice", "prevalence": 0.9167},
                          {"id": 2, "name": "hemija", "prevalence": 0.8333}],
  "baseline_60d": 2210.40,
  "period": {"from": null, "to": "2026-06-02"} }
```

## Confidence

In SQL: the **average peer prevalence of the missing categories** (already a 0–1 share —
the more universally peers buy what this customer doesn't, the more confident the
recommendation). Band via the global thresholds.

## Must NOT fire (guards)

- Segments whose peers genuinely buy few categories (e.g. kafić buys 3 — a 3-category kafić
  is normal, and missing-category prevalence won't clear `min_peer_prevalence` for thin segments).
- Small customers below `min_baseline_60d`.
- Dedup / active learned-rule suppressions.
