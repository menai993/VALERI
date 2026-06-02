# Spec — M1: Domain model, migration, synthetic seed

**Milestone:** M1 · **Builds on:** M0 (schemas exist, Alembic wired) · **Status:** approved (Q1–Q3 OK'd by owner, 2026-06-02)

## 1. Objective

Prove the business graph: implement the ten `core.*` tables from `docs/data-model.md` (core
graph section) as SQLAlchemy 2.x models + one Alembic migration + Pydantic v2 schemas in
`domain/`, and build a deterministic synthetic seed resembling Ultra Higijena — ~80
customers under realistic legal entities, ~120 articles in 7 categories, ~18 months of
invoices with per-customer/article cadence, and **17 planted cases** that later milestones
(M3 metrics, M4 rules) must detect or must NOT flag. Acceptance is **Capability A**: a
sampled customer enumerates its legal entity, sibling objects, last-12-months invoices, and
assigned rep with no invented relationships.

## 2. Scope

### In scope
1. `domain/` package: SQLAlchemy models for `core.legal_entity, customer, contact,
   sales_rep, customer_rep, category, article, article_alias, invoice, invoice_line`
   — columns, FKs, indexes, uniques **exactly** as in `docs/data-model.md`.
2. Alembic migration `0002_core_graph` (one migration for this schema-changing milestone).
3. Pydantic v2 read schemas (one per model, `from_attributes=True`).
4. Deterministic seed generator (`valeri_api/seed/`) + CLI
   (`python -m valeri_api.seed`) + planted-case manifest (`db/seed/planted_cases.json`).
5. Tests: model structure, seed integrity, planted cases, determinism, **Capability A**.
6. CI keeps running these tests (no workflow changes needed — pytest picks them up).

### Out of scope (deferred)
- Derived metric tables `customer_metrics`, `cust_article_cadence`, `segment_basket` (M3).
- All `app.*` / `audit.*` tables and enums (`register`, `conf_band`, …) — M4+; core tables
  use plain TEXT for `segment`/`status` per the data model.
- `staging.*` content and the CSV-export/ingest path (M2). The seed writes **directly to
  `core.*`**; the importable CSV "export" of this seed is an M2 deliverable.
- Any API endpoint (customer/article endpoints land in M8 per `docs/api-spec.md`).
- Any LLM involvement, rules, signals, metrics computation.

## 3. Files

```
apps/api/valeri_api/domain/
  __init__.py            re-export models + schemas
  models.py              the 10 SQLAlchemy models (schema="core"), typed (Mapped[...])
  schemas.py             Pydantic v2 read schemas: LegalEntityRead, CustomerRead, ContactRead,
                         SalesRepRead, CustomerRepRead, CategoryRead, ArticleRead,
                         ArticleAliasRead, InvoiceRead, InvoiceLineRead

apps/api/migrations/versions/
  0002_core_graph.py     create the 10 core.* tables + all indexes/uniques; full downgrade

apps/api/valeri_api/seed/
  __init__.py
  __main__.py            CLI: python -m valeri_api.seed [--as-of YYYY-MM-DD] [--rng-seed N] [--reset]
  config.py              SeedConfig dataclass: counts, segments, categories, cadence ranges,
                         price ranges, RNG seed default, planted-case parameters
  names.py               Bosnian name pools: hotels, restorani, kafići, klinike, škole,
                         people (contacts/reps), article names per category
  entities.py            generate_legal_entities(), generate_customers(), generate_contacts(),
                         generate_reps(), assign_reps()
  articles.py            generate_categories(), generate_articles(), generate_code_swaps()
  invoices.py            generate_invoices(): cadence-based orders + lines over 18 months
  planted.py             plant_declines(), plant_seasonal_cafes(), plant_lost_articles(),
                         plant_code_swaps(), plant_narrow_baskets(), plant_sleeping();
                         build_manifest()
  loader.py              load(): bulk-insert all generated rows into core.* in one transaction;
                         reset(): truncate core.* (dev convenience)

apps/api/tests/
  conftest.py            (edit) add seeded-db fixture: run migration + seed once per session
  test_domain_models.py  structure tests (tables/FKs/uniques/NUMERIC types)
  test_seed.py           volume, integrity, planted-case, determinism tests
  test_capability_a.py   the acceptance test (sampled-customer enumeration)

db/seed/
  README.md              how to run the seed; what is planted and where (human-readable)
  planted_cases.json     generated manifest — ground truth consumed by M3/M4 tests (committed)
  .gitkeep               (delete — replaced by real content)
```

## 4. Data-model touchpoints

| Table (schema `core`) | Action | Notes |
|---|---|---|
| `legal_entity` | create | `tax_id` UNIQUE |
| `customer` | create | FK → legal_entity; ix on legal_entity_id, segment |
| `contact` | create | FK → customer; PII columns (synthetic only) |
| `sales_rep` | create | |
| `customer_rep` | create | composite PK (customer_id, sales_rep_id, from_date) |
| `category` | create | |
| `article` | create | FK → category; `code` UNIQUE (ux_article_code) |
| `article_alias` | create | PK old_code; FK → article (code-swap mapping) |
| `invoice` | create | FK → customer; ix (customer_id, date) |
| `invoice_line` | create | FK → invoice, article; ix invoice_id, article_id |

- **Migration:** `0002_core_graph` (revises `0001`). Upgrade creates all 10 tables;
  downgrade drops them in FK-safe order. No enums needed (core uses TEXT).
- Money/qty columns: `NUMERIC(14,2)` / `NUMERIC(14,3)` / `NUMERIC(14,4)` exactly per the
  data model; `Decimal` end-to-end in Python — **never float**.
- `staging`, `app`, `audit` schemas: untouched.

## 5. API touchpoints

**None.** M1 adds no endpoints (per `docs/api-spec.md`, customer/article endpoints are M8).
The graph is exercised via tests and the seed CLI only.

## 6. Seed design (what "resembling Ultra Higijena" means concretely)

All generation is **deterministic** given `(rng_seed, as_of)`; defaults `rng_seed=20260601`,
`as_of=today`. Bosnian names with full diacritics throughout.

| Dimension | Target |
|---|---|
| Legal entities | ~5 hotel groups (each with **2–3 customer objects**: e.g. "Hotel Bistrik — domaćinstvo", "— restoran", "— wellness") + ~55 single-object entities |
| Customers (objects) | **~80** total: ~12–15 hotel objects, rest restoran/kafić/klinika/škola |
| Segments | hotel / restoran / kafić / klinika / škola |
| Categories | papir / hemija / dispenzeri / rukavice / kozmetika / tekstil / oprema (7) |
| Articles | **~120**, distributed across the 7 categories, realistic names + KM prices |
| Sales reps | 4, each owning a region/portfolio of customers (`customer_rep`) |
| Contacts | 1–2 per customer (synthetic names/emails/phones/addresses) |
| Invoices | **18 months** ending at `as_of`; each customer has a basket (6–25 articles) and a cadence (7–35 days ± noise); 3–12 lines per invoice; `invoice.total` = Σ `line_total` to the cent |

### Planted cases (recorded in `db/seed/planted_cases.json`)

| Case | Count | Construction (relative to `as_of`) |
|---|---|---|
| **Real decline** | 3 | Normal history for 16 months, then last-60d turnover drops to ~40–55% of the customer's 6-month baseline; no such drop the year before (not seasonal) |
| **Seasonal café** | 2 | kafić whose turnover always drops in this season (same drop pattern 12 months ago) — must **NOT** be flagged as decline by M4 |
| **Lost article** | 4 | customer×article bought on a regular cadence for ≥12 months, then zero purchases for ≥3× cadence, while the customer keeps ordering other articles |
| **Code-swap** | 2 | article gets a new code: old article → `active=false`, new article created, `article_alias(old_code → new_article)`; purchases continue seamlessly under the new code — must **NOT** appear as lost |
| **Narrow basket** | 3 | customer buying only 1–2 categories while ≥70% of its segment buys ≥4 categories (cross-sell candidate) |
| **Sleeping customer** | 3 | ≥12 months of regular ordering, then **no invoices for ≥3× their average interval** (and ≥75 days), customer still `active` |

Manifest shape (consumed by M3/M4 tests):

```json
{ "rng_seed": 20260601, "as_of": "2026-06-02",
  "declines":        [{ "customer_id": 17, "external_code": "UH-0017", "baseline_60d": "4210.50", "last_60d": "1890.20" }],
  "seasonal_cafes":  [{ "customer_id": 31 }],
  "lost_articles":   [{ "customer_id": 8, "article_id": 55, "last_seen": "2026-02-10", "cadence_days": 14 }],
  "code_swaps":      [{ "old_code": "ART-0033", "new_article_id": 121, "customer_ids": [5, 9] }],
  "narrow_baskets":  [{ "customer_id": 44, "categories": ["papir"] }],
  "sleeping":        [{ "customer_id": 61, "last_order": "2026-02-20", "avg_interval_days": 12.5 }] }
```

## 7. Tests

TDD order: model structure tests → migration/models → seed tests → seed → Capability A.

`tests/test_domain_models.py`
1. `test_core_tables_exist` — all 10 tables exist in schema `core` after `alembic upgrade head`.
2. `test_article_code_unique` — inserting a duplicate `article.code` raises IntegrityError.
3. `test_fk_integrity_enforced` — customer without legal_entity / line without invoice → IntegrityError.
4. `test_money_columns_are_numeric` — `invoice.total`, `invoice_line.unit_price/line_total` are NUMERIC with the spec'd precision (inspector check), and round-trip `Decimal` exactly.
5. `test_customer_rep_composite_pk` — duplicate (customer, rep, from_date) rejected.

`tests/test_seed.py`
6. `test_seed_volumes` — ~80 customers (75–85), ~120 articles (115–125), 7 categories, ≥5 multi-object legal entities (2–3 objects each), 4 reps, invoice dates span ≥17 months.
7. `test_invoice_totals_match_lines` — for **every** invoice: `total == Σ line_total` to the cent (SQL aggregation).
8. `test_every_customer_has_current_rep` — exactly one effective rep per customer.
9. `test_planted_cases_match_manifest` — for each entry in `planted_cases.json`, the data exhibits the pattern (decline ratio, seasonal repeat, lost-article gap, alias rows, basket width, sleeping gap) — verified with direct SQL.
10. `test_seed_deterministic` — generating twice with the same `(rng_seed, as_of)` yields identical counts and identical manifest.

`tests/test_capability_a.py` (acceptance)
11. `test_sampled_customer_enumeration` — for a sampled hotel object AND a sampled standalone customer:
    - legal entity name/tax_id match the seeded values;
    - the set of sibling objects under that legal entity is exactly the seeded set;
    - ORM-enumerated last-12-months invoices equal a direct SQL query (ids, count, sum to the cent);
    - the assigned rep equals the seeded `customer_rep` row;
    - **no invented relationships**: every enumerated entity originates from the seed (ids ⊆ seeded ids).

## 8. Acceptance criteria

1. `alembic upgrade head` creates the 10 `core.*` tables; downgrade removes them cleanly.
2. `python -m valeri_api.seed --reset` populates `core.*` to the volumes in §6 and writes
   `db/seed/planted_cases.json`.
3. All 17 planted cases are present and verifiable by SQL (test 9).
4. Capability A test (11) passes: sampled customer's legal entity, objects, 12-month
   invoices, and rep enumerate correctly with no invented links.
5. Full pytest suite green locally (against PostgreSQL 16) and in CI.
6. principle-reviewer reports PASS on the M1 diff.

## 9. Principles compliance

| Principle | M1 impact |
|---|---|
| 1. No LLM-computed numbers | No LLM anywhere in M1; all seed numbers come from deterministic Python/`Decimal` and are verified by SQL aggregation. |
| 2. Evidence on signals/tasks | N/A (no signals yet). The planted-case manifest becomes the ground-truth evidence for M4 tests. |
| 3. Confidence scores | N/A (no AI conclusions). |
| 4. No writes to source ERP | Seed writes only to VALERI's own `core.*` schema; no external system exists. |
| 5. Read-only / staging posture | Synthetic data only; no source data is read or modified. |
| 6. PII masking before LLM | Contacts carry **synthetic** PII; no LLM calls exist in M1. The PII columns are flagged in the model docstrings for M6. |
| 7. Append-only logs | N/A (no AI/task/decision activity). `audit` schema remains empty. |
| 8. Feedback loop | N/A. |
| 9. Register tags | N/A (no AI output). |
| 10. Approval gates | N/A (no customer-facing communication). |
| Conventions | Money = NUMERIC/Decimal (never float); typed models/schemas; no secrets; no thresholds hard-coded (planted-case parameters live in `SeedConfig`, which is test fixture config, not business rule config). |

## 10. Open questions — resolved at review (2026-06-02)

1. **Seed CLI default volume** — ✅ OK (~80 customers / 18 months; realistic estimate
   ≈ 3–4k invoices, ≈ 25–30k lines — well within a few seconds of load time).
2. **`as_of` semantics** — ✅ OK (default `as_of = today`, `--as-of` override).
3. **Manifest committed** — ✅ OK (`db/seed/planted_cases.json` committed as ground truth).
