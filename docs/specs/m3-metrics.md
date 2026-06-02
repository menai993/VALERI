# Spec — M3: Metrics & semantic layer (trust foundation)

**Milestone:** M3 · **Builds on:** M2 (core graph + import path) · **Status:** awaiting review
**TDD: golden tests and fixtures are written before any implementation.**

## 1. Objective

Prove that **every business number VALERI ever shows comes from deterministic SQL**: build
`metrics/` (PostgreSQL window-function SQL that recomputes `core.customer_metrics`,
`core.cust_article_cadence`, `core.segment_basket` for a given `as_of` date) and `semantic/`
(a YAML metric registry + a validated query builder that is the only sanctioned way for
later layers — tools in M9, NL→SQL later — to run metric queries). No LLM is involved in any
calculation, and golden tests pin every metric's SQL output to hand-computed fixture values,
exact to the cent.

## 2. Scope

### In scope
1. **Migration 0004**: the three derived tables exactly per `docs/data-model.md`
   (`core.customer_metrics`, `core.cust_article_cadence`, `core.segment_basket`).
2. **`metrics/` package**: pure-SQL recompute (DELETE + `INSERT … SELECT` with window
   functions, one transaction), parameterised by `as_of` (default: today); ad-hoc turnover
   query functions (by customer/article/category/segment/period); CLI
   (`python -m valeri_api.metrics [--as-of]`).
3. **Metric definitions** (exact, see §6): `turnover_60d`, `turnover_6m_avg_60d` (baseline),
   `last_order_date`, `avg_order_interval_d`, per-article cadence (`avg_interval_d`,
   `last_seen`), segment basket `prevalence`.
4. **`semantic/` package**: `registry.yaml` (metric → SQL, entity, grain, params),
   Pydantic-validated loader, and a query builder that only executes registered metrics with
   validated bind parameters (no string interpolation, ever).
5. **Ingest integration**: `run_import(..., recompute_metrics=True)` re-runs the recompute
   after a successful upsert (addresses the M2 review note about line replacement).
6. **Golden tests** (handcrafted fixture, fixed dates, hand-computed expected values) +
   seed-consistency tests (metrics == direct SQL over the seed; planted declines visible).
7. New dependency: `pyyaml`.

### Out of scope (deferred)
- API endpoints `/metrics/*`, `/dashboard` (M8 — the milestone is proven by golden tests).
- Rules/signals/scanner that consume these metrics (M4).
- Any LLM involvement, narration of metrics (M6), NL→SQL (M9+).
- Incremental/partial recompute (full refresh is fast at this scale: 82 customers, ~3.4k
  invoices; revisit when real data demands it).
- Caching/materialised views.

## 3. Files

```
apps/api/valeri_api/metrics/
  __init__.py
  sql/
    customer_metrics.sql        INSERT INTO core.customer_metrics … SELECT (window functions)
    cust_article_cadence.sql    INSERT INTO core.cust_article_cadence … SELECT
    segment_basket.sql          INSERT INTO core.segment_basket … SELECT
  recompute.py                  recompute_all(session, as_of) + per-table functions:
                                DELETE + execute the .sql file with bind params; RecomputeResult
  queries.py                    ad-hoc deterministic queries: turnover(session, from, to,
                                customer_id?, article_id?, category_id?, segment?) -> Decimal;
                                turnover_by_month(...) -> list[(month, Decimal)]
  __main__.py                   CLI: python -m valeri_api.metrics [--as-of YYYY-MM-DD]

apps/api/valeri_api/semantic/
  __init__.py
  registry.yaml                 the metric registry (definitions below, §7)
  registry.py                   MetricDefinition/MetricParam (Pydantic) + load_registry()
  query_builder.py              build_metric_query(name, params) -> (sql, binds) +
                                run_metric(session, name, params) -> MetricResult

apps/api/valeri_api/ingest/pipeline.py    (edit) optional metrics recompute after upsert

apps/api/migrations/versions/
  0004_derived_metrics.py       create the 3 derived tables (+ downgrade)

apps/api/tests/
  fixtures/
    __init__.py
    metrics_fixture.py          handcrafted dataset (fixed dates, as_of=2026-06-01) +
                                hand-computed expected rows for all 3 tables
  test_metrics.py               golden tests + seed-consistency tests (list in §8)
  test_semantic.py              registry + query-builder tests (list in §8)

apps/api/pyproject.toml         (edit) + pyyaml ; uv.lock updated
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `core.customer_metrics` | **create** (0004) + write (recompute) | exactly per data-model.md |
| `core.cust_article_cadence` | **create** (0004) + write (recompute) | exactly per data-model.md |
| `core.segment_basket` | **create** (0004) + write (recompute) | exactly per data-model.md |
| `core.customer/invoice/invoice_line/article/category` | read | the source of every number |

- **One migration** for the milestone: `0004_derived_metrics`.
- Recompute = full refresh (DELETE all + INSERT … SELECT) in one transaction — idempotent,
  no partial states.

## 5. API touchpoints

**None.** `/metrics/*` endpoints land in M8 per the plan (M3 is proven by golden tests).
The semantic layer's `run_metric()` is the internal API that M9 tools will call.

## 6. Metric definitions (exact semantics — the contract the golden tests pin)

All windows are half-open intervals `(start, end]` relative to a given `as_of` date.

| Metric | Definition |
|---|---|
| `turnover_60d` | `SUM(invoice.total)` for the customer's invoices with `date ∈ (as_of − 60d, as_of]`; **0.00** (not NULL) when no invoices in window |
| `turnover_6m_avg_60d` | `SUM(invoice.total)` for `date ∈ (as_of − 240d, as_of − 60d]` **÷ 3** (a 180-day baseline window normalised to 60 days; division in SQL); 0.00 when empty |
| `last_order_date` | `MAX(invoice.date)` over all history; NULL if the customer never ordered |
| `avg_order_interval_d` | average of day-gaps between **consecutive distinct invoice dates** (window fn `LAG`), over all history; NULL when < 2 distinct dates |
| `customer_metrics.segment` | copied from `customer.segment` at recompute time |
| `cust_article_cadence.avg_interval_d` | per (customer, article): average gap between consecutive **distinct invoice dates** containing that article; NULL when < 2 purchases |
| `cust_article_cadence.last_seen` | per (customer, article): MAX(invoice.date) containing the article |
| `segment_basket.prevalence` | per (segment, category): `COUNT(DISTINCT customers of the segment that ever bought the category) ÷ COUNT(DISTINCT customers of the segment with ≥ 1 invoice)`, division in SQL, NUMERIC(5,4); only rows with prevalence > 0 are stored |

Customers with `status != 'active'` are still computed (detection rules decide what to do
with them — that's M4's job, not the metric layer's).

## 7. Semantic registry (M3 contents)

`registry.yaml` defines, for each metric: `name`, `description_bs`, `description_en`,
`entity` (customer/article/segment/company), `grain`, `params` (name, type, required),
`sql` (with named bind parameters only). M3 registry entries:

1. `customer_turnover_60d` (reads `core.customer_metrics`) — params: `customer_id`
2. `customer_baseline_60d` (reads `core.customer_metrics`) — params: `customer_id`
3. `customer_last_order` — params: `customer_id`
4. `customer_order_interval` — params: `customer_id`
5. `article_cadence` (reads `core.cust_article_cadence`) — params: `customer_id`, `article_id`
6. `segment_basket` (reads `core.segment_basket`) — params: `segment`
7. `turnover` (ad-hoc over invoices) — params: `from_date`, `to_date`, optional
   `customer_id`/`article_id`/`category_id`/`segment`
8. `turnover_by_month` (ad-hoc series) — params: `from_date`, `to_date`, optional `customer_id`

Query-builder guarantees: unknown metric → error; missing/extra/wrong-type params → error;
**values only ever passed as bind parameters** (SQL injection structurally impossible);
results returned typed (`Decimal`/`date`/`str`).

## 8. Tests (TDD — fixtures and tests written before any implementation)

### Golden fixture (`tests/fixtures/metrics_fixture.py`)
Handcrafted, fixed `as_of = 2026-06-01`, hand-computed expected values:
- 3 customers (hotel / restoran / kafić), 2 categories, 4 articles, ~20 invoices with
  round numbers placed exactly on window boundaries (to pin the half-open interval
  semantics), one customer with a single invoice (NULL interval), one customer with no
  invoices in the 60d window (zero turnover), same-day double invoice (distinct-date rule).
- `EXPECTED_CUSTOMER_METRICS`, `EXPECTED_CADENCE`, `EXPECTED_SEGMENT_BASKET` literals.

### `tests/test_metrics.py`
1. `test_golden_customer_metrics` — every row of `core.customer_metrics` equals
   `EXPECTED_CUSTOMER_METRICS` exactly (turnover/baseline to the cent, dates, intervals to
   0.01, segment).
2. `test_golden_cadence` — every row of `core.cust_article_cadence` equals `EXPECTED_CADENCE`.
3. `test_golden_segment_basket` — every row of `core.segment_basket` equals
   `EXPECTED_SEGMENT_BASKET` (prevalence to 4 decimals).
4. `test_window_boundaries_are_half_open` — an invoice dated exactly `as_of − 60d` falls in
   the **baseline**, not the 60d window; an invoice dated exactly `as_of` falls in the 60d window.
5. `test_recompute_is_idempotent` — recompute twice → identical table contents.
6. `test_recompute_excludes_nothing_silently` — every customer (even with zero invoices) has
   a `customer_metrics` row.
7. `test_seed_customer_metrics_match_direct_sql` — over the full seed: every customer's
   `turnover_60d`/`turnover_6m_avg_60d`/`last_order_date` equals an independent direct SQL
   computation (cross-check, to the cent).
8. `test_seed_planted_declines_visible` — for the 3 manifest declines:
   `turnover_60d / turnover_6m_avg_60d` ∈ [0.30, 0.65]; for the 2 seasonal cafés the ratio is
   also < 0.75 (the metric itself doesn't decide seasonality — that's M4's guard).
9. `test_recompute_after_import` — full flow: fresh import (M2) with `recompute_metrics=True`
   → metrics tables populated and consistent with the imported data.

### `tests/test_semantic.py`
10. `test_registry_loads_and_validates` — registry.yaml parses; every entry has valid SQL
    params; descriptions present in bs + en.
11. `test_unknown_metric_rejected` — `build_metric_query("nepostojeci", …)` raises.
12. `test_param_validation` — missing required param, unknown param, wrong type → each raises.
13. `test_metric_results_equal_direct_sql` — `run_metric("turnover", …)` over the golden
    fixture equals the hand-computed expected value to the cent; same for
    `customer_turnover_60d`.
14. `test_bind_params_only` — a malicious string param (`"1; DROP TABLE core.invoice;--"`)
    is passed as a bind value: query executes safely / matches nothing; the registry loader
    rejects any SQL containing string-format placeholders (`%s`, `{`).
15. `test_llm_not_involved` — static check: `metrics/` and `semantic/` import nothing from
    any LLM/network module (no `llm`, `anthropic`, `litellm`, `httpx` imports).

## 9. Acceptance criteria (per IMPLEMENTATION-PLAN M3)

1. Migration 0004 creates the 3 derived tables; clean downgrade.
2. `python -m valeri_api.metrics --as-of …` populates all three tables from invoice data.
3. **Golden tests: every metric's SQL output equals the fixtures exactly, to the cent** (tests 1–4).
4. Recompute is idempotent and complete (tests 5–6).
5. Seed-consistency + planted-decline visibility (tests 7–8); import triggers recompute (test 9).
6. Semantic registry + query builder enforce validation and bind-params-only (tests 10–15).
7. `/numbers-check` passes: golden tests green + no arithmetic on business data outside SQL.
8. Full pytest suite green locally + CI; ruff/black clean.
9. principle-reviewer reports PASS on the M3 diff.

## 10. Principles compliance

| Principle | M3 impact |
|---|---|
| 1. **No LLM-computed numbers** | This milestone IS the enforcement mechanism: every number is produced by SQL inside the DB (`INSERT … SELECT`, window functions, SQL division). Python only orchestrates; the LLM doesn't exist in this layer (test 15 asserts no LLM imports). |
| 2. Evidence on signals/tasks | N/A (no signals yet). The metric tables are what M4 evidence will point at. |
| 3. Confidence scores | N/A (no AI conclusions; metrics are deterministic facts). |
| 4. No writes to source ERP | Recompute writes only `core.*` derived tables. |
| 5. Read-only/staging posture | Reads `core.*` (the staged copy), writes derived `core.*` tables. |
| 6. PII masking before LLM | No LLM calls. Metric tables carry no PII (ids, numbers, dates, segment only). |
| 7. Append-only logs | N/A for audit.*; derived tables are recomputed state, not logs (full refresh by design). |
| 8. Feedback loop | N/A. |
| 9. Register tags | N/A (no AI output). |
| 10. Approval gates | N/A. |
| Conventions | Money NUMERIC/Decimal; thresholds: none introduced (metric definitions are facts, not thresholds — thresholds arrive with M4 rules in `app.rule_config`); typed Pydantic for registry/results; one migration. |

## 11. Open questions

1. **Baseline definition** — `turnover_6m_avg_60d` = turnover of the 180 days **before** the
   current 60-day window (i.e. `(as_of−240d, as_of−60d]`), divided by 3. This matches how M1
   planted the declines and how M4 will detect them. Confirm?
2. **avg_order_interval_d horizon** — computed over **all available history** (~18 months).
   Alternative: cap at last 12 months. Propose: all history.
3. **segment_basket horizon** — prevalence over **all available history**. Propose: all history.
4. **Recompute after import** — `run_import()` triggers metrics recompute by default
   (decoupled flag, can be disabled). Confirm?
