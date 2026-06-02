# Spec — M2: Ingestion / staging / data-quality

**Milestone:** M2 · **Builds on:** M1 (core graph + seed) · **Status:** awaiting review

## 1. Objective

Prove the **read-only import path**: an ERP-style CSV/Excel export is loaded raw into
`staging.*` (kept for traceability), idempotently upserted into `core.*` by natural keys
(codes/JIB — never internal IDs), and every import produces a **data-quality report**
(duplicate codes, renamed articles, code-swap candidates, missing segments, orphan lines).
Exposed via `POST /api/ingest/import` + `GET /api/ingest/report/{id}` and a CLI. Acceptance:
importing the seed export twice is idempotent, totals are preserved to the cent, and the
report detects the planted code-swaps and a renamed article.

## 2. Scope

### In scope
1. **Seed export** (`valeri_api/seed/export.py`): write the M1 seed as an ERP-style export —
   4 files: `kupci.csv`, `artikli.csv`, `fakture.csv`, `stavke.csv` (Bosnian headers,
   `;` delimiter, external codes only). This is "the seed export" the acceptance refers to.
2. **`ingest/` package**: readers (CSV + XLSX) → `staging.*` raw load → idempotent upsert to
   `core.*` → data-quality report → persisted `import_run` with stats + report.
3. **Migration 0003**: `staging.import_run`, `staging.kupci`, `staging.artikli`,
   `staging.fakture`, `staging.stavke`; plus `core.invoice.external_no` (see D1).
4. **API**: `POST /api/ingest/import` (multipart upload or server-side path) → `{import_id}`;
   `GET /api/ingest/report/{import_id}` → stats + quality report. Synchronous processing.
5. **CLI**: `python -m valeri_api.ingest <dir-or-files> [--no-upsert]`.
6. **Seed change**: invoices get `external_no` (`FK-YYYY-NNNNNN`), so import-over-seeded-data
   matches by natural key.
7. Tests (TDD): idempotency, totals to the cent, code-swap + rename detection, quality flags,
   staging traceability, API + CLI + Excel paths.

### Out of scope (deferred)
- Async/worker-based import (synchronous is fine at this data size; revisit for real exports).
- Contact/PII import (contacts are not part of the export — see D2).
- Rep-change history handling (a customer's rep assignment is created if missing, never moved).
- Auth/RBAC on the endpoints (M8) — same as `/api/health` today.
- Any LLM involvement, metrics, rules, signals (M3+). The report is pure SQL/Python.
- Scheduling of imports (the worker stays a placeholder until M4).

## 3. Files

```
apps/api/valeri_api/seed/
  export.py               write_export_csvs(data: SeedData, out_dir) -> list[Path]
                          (kupci/artikli/fakture/stavke CSVs, ERP format)
  invoices.py             (edit) generate external_no "FK-{year}-{id:06d}" per invoice
  __main__.py             (edit) add --export-dir flag (load seed AND/OR write the export)

apps/api/valeri_api/ingest/
  __init__.py
  models.py               SQLAlchemy models: ImportRun + StagingKupac/Artikal/Faktura/Stavka
  schemas.py              Pydantic: ImportResult, ImportReport, QualityReport, RenamedArticle,
                          CodeSwapCandidate, OrphanLine, DuplicateCode, MissingSegment
  readers.py              read_table(path) -> list[dict]: CSV (sniffed delimiter) + XLSX (openpyxl)
  staging.py              create_import_run(), load_to_staging(rows, run) — raw TEXT rows
  quality.py              build_quality_report(session, run_id) — the 5 checks (SQL over
                          staging + core, BEFORE upsert)
  upsert.py               upsert_to_core(session, run_id) — idempotent by natural keys;
                          returns per-entity {created, updated, unchanged} stats
  pipeline.py             run_import(session, files, source) — orchestrates:
                          read → staging → quality → upsert → finalize run (stats+report)
  __main__.py             CLI

apps/api/valeri_api/api/
  ingest.py               POST /api/ingest/import, GET /api/ingest/report/{import_id}

apps/api/valeri_api/
  main.py                 (edit) include the ingest router
  domain/models.py        (edit) Invoice.external_no: Mapped[str | None]
  domain/schemas.py       (edit) InvoiceRead.external_no

apps/api/migrations/versions/
  0003_staging_and_invoice_external_no.py

apps/api/pyproject.toml   (edit) add openpyxl (+ python-multipart for FastAPI uploads); uv.lock

apps/api/tests/
  test_ingest.py          the 10 tests below (fixtures: export_dir, fresh_import_db)

docs/data-model.md        (edit) document core.invoice.external_no + the staging.* tables
db/seed/README.md         (edit) document the export command/format
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `staging.import_run` | **create** (0003) | id, source, started_at, finished_at, status, stats JSONB, report JSONB |
| `staging.kupci` | **create** (0003) | raw TEXT columns: sifra, naziv, jib, naziv_pravnog_lica, segment, status, komercijalista + import_run_id, row_no |
| `staging.artikli` | **create** (0003) | sifra, naziv, kategorija, aktivan + import_run_id, row_no |
| `staging.fakture` | **create** (0003) | broj_fakture, sifra_kupca, datum, ukupno + import_run_id, row_no |
| `staging.stavke` | **create** (0003) | broj_fakture, sifra_artikla, kolicina, cijena, iznos + import_run_id, row_no |
| `core.invoice` | **alter** (0003) | + `external_no TEXT`, unique partial index (see D1) |
| `core.*` (all M1 tables) | read + upsert | by natural keys; never by internal id |

- **One migration** for the milestone: `0003_staging_and_invoice_external_no`.
- All staging payload columns are TEXT (raw rows kept for traceability per data-model.md notes).
- `docs/data-model.md` is updated to stay canonical.

## 5. API touchpoints (per docs/api-spec.md, Ingest M2)

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/ingest/import` | multipart files (`kupci`, `artikli`, `fakture`, `stavke`) **or** JSON `{"path": "/dir"}` | `201 {"import_id": 1}` |
| `GET /api/ingest/report/{import_id}` | — | `200` ImportReport (below); `404` unknown id |

ImportReport shape:

```json
{ "import_id": 1, "status": "completed",
  "started_at": "…", "finished_at": "…", "source": "api|cli|path",
  "stats": { "kupci":   {"created": 0, "updated": 0, "unchanged": 82},
             "artikli": {"created": 0, "updated": 0, "unchanged": 122},
             "fakture": {"created": 0, "updated": 0, "unchanged": 3445},
             "stavke":  {"created": 0, "replaced": 0, "unchanged": 26413} },
  "quality": {
    "duplicate_customer_codes": [{"code": "…", "names": ["…","…"]}],
    "duplicate_article_codes":  [{"code": "…", "names": ["…","…"]}],
    "renamed_articles":   [{"code": "…", "old_name": "…", "new_name": "…"}],
    "code_swap_candidates": [{"old_code": "…", "new_code": "…", "name": "…", "already_mapped": false}],
    "missing_segments":   [{"customer_code": "…", "name": "…"}],
    "orphan_lines":       [{"row_no": 1, "broj_fakture": "…", "sifra_artikla": "…", "reason": "unknown_invoice|unknown_article"}] } }
```

Numbers in stats/report are SQL counts — no LLM anywhere. Errors per api-spec envelope.

## 6. Key design decisions (flagged for review)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Add `core.invoice.external_no` (TEXT, unique when not null)** + update `docs/data-model.md` | Idempotent invoice upsert needs a natural key. Real ERP exports always carry an invoice number (`broj fakture`); `core.customer` already has `external_code` for exactly this reason. Without it, re-import would duplicate every invoice. |
| **D2** | **Export = 4 files, no contacts** (`kupci.csv`, `artikli.csv`, `fakture.csv`, `stavke.csv`; Bosnian headers; `;` delimiter; UTF-8; external codes only) | Sales-recovery needs customers/articles/invoices. Contact PII is not round-tripped through exports; contacts stay only in the DB. Reader auto-detects delimiter, so real exports with `,` also work. |
| **D3** | **Synchronous import processing** in the POST request | ~3.4k invoices import in seconds. Async via the worker is a later optimization; the API contract (`import_id` + separate report fetch) already allows it. |
| **D4** | **Quality report computed BEFORE upsert** | Rename/code-swap detection needs the staging-vs-core diff; after upsert the diff disappears. Report is persisted on `import_run` so it stays retrievable. |
| **D5** | **Code-swap detection is data-driven, no thresholds**: same article name + old article inactive (or activity stops) + new article's activity starts where old's ends → candidate; pairs already in `core.article_alias` are reported with `already_mapped: true` | Avoids inventing hard-coded business thresholds before `app.rule_config` exists (M4). |
| **D6** | **Upsert semantics**: legal_entity by `tax_id` → customer by `external_code` → category by `name` → article by `code` (rename applied, report flags it) → invoice by `external_no` (unchanged ⇒ skip; changed ⇒ update + replace lines) → reps created by name, assignment created only if customer has none | "Read-only copy of the source": core mirrors the ERP; the report gives humans visibility into what changed. |

## 7. Tests (TDD — written before the implementation)

Fixtures (test_ingest.py): `export_dir` (module): seed_data → CSVs in tmp dir ·
`fresh_import_db` (module): reset core → import export_dir → yield (engine, import_id);
teardown restores the M1-loaded seed so later M1 tests are unaffected.

1. `test_fresh_import_populates_core_to_the_cent` — counts (customers/articles/invoices/lines)
   equal seed counts; `SUM(invoice.total)` and `SUM(line_total)` equal the seed sums exactly;
   a sampled invoice's total matches.
2. `test_reimport_is_idempotent` — importing the same files again: stats all
   `unchanged`, 0 created/updated; counts, sums, and sampled internal IDs identical.
3. `test_import_over_seeded_data_is_idempotent` — with the M1 seed loaded, importing the
   export creates nothing (everything matches by natural keys).
4. `test_report_detects_code_swap_candidates` — fresh-import report lists both planted swaps
   (old/new code pairs from `db/seed/planted_cases.json`) as candidates.
5. `test_report_detects_renamed_article` — import once → edit one article name in
   `artikli.csv` → import again → `renamed_articles` contains {code, old_name, new_name} and
   `core.article.name` now equals the new name.
6. `test_report_flags_dupes_missing_segments_orphans` — handcrafted mini-CSVs with a duplicate
   article code (two names), a customer without segment, a line with unknown invoice, and a
   line with unknown article → each flagged in its report section.
7. `test_staging_keeps_raw_rows` — after import, staging row counts per table match the CSVs
   and carry the right import_run_id (traceability).
8. `test_api_import_and_report_endpoints` — POST multipart upload → 201 {import_id}; GET
   report → 200 with stats + quality; GET unknown id → 404 with the api-spec error envelope.
9. `test_cli_import` — `python -m valeri_api.ingest <dir>` (main() called directly) runs the
   pipeline and prints the import id + summary.
10. `test_excel_import` — `artikli.xlsx` (converted from CSV) + the other 3 CSVs imports
    identically to the all-CSV path.

## 8. Acceptance criteria (per IMPLEMENTATION-PLAN M2)

1. The seed export (4 files) is generated by `python -m valeri_api.seed --export-dir …`.
2. **Importing the seed export twice is idempotent** (test 2; also test 3).
3. **Totals preserved to the cent** (test 1).
4. **The report detects the planted code-swaps** (test 4) **and a renamed article** (test 5).
5. `POST /api/ingest/import` and `GET /api/ingest/report/{id}` work per api-spec (test 8).
6. CLI path works (test 9). CSV and Excel both supported (test 10).
7. Full pytest suite green locally + CI; ruff/black clean.
8. principle-reviewer reports PASS on the M2 diff.

## 9. Principles compliance

| Principle | M2 impact |
|---|---|
| 1. No LLM-computed numbers | No LLM exists in M2. All stats/report numbers are SQL counts/sums; totals parsed as Decimal. |
| 2. Evidence on signals/tasks | N/A (no signals). The quality report carries row-level references (codes, row numbers) — the same evidence discipline. |
| 3. Confidence scores | N/A (no AI conclusions; the report is deterministic SQL). |
| 4. **No writes to source ERP** | The ingest only READS export files; it never connects to, let alone writes, any source system. |
| 5. **Read-only / export / staging access** | This milestone IS that principle: export → staging (raw, append-only per run) → core copy. |
| 6. PII masking before LLM | No LLM calls. The export deliberately excludes contact PII (D2). |
| 7. Append-only logs | `staging.*` rows are kept per import run (never updated), giving a full import audit trail. `audit.*` untouched. |
| 8. Feedback loop | N/A. |
| 9. Register tags | N/A (no AI output; the report is a deterministic data product). |
| 10. Approval gates | N/A (no customer-facing communication). |
| Conventions | Money Decimal/NUMERIC; typed Pydantic schemas for API I/O; no secrets; no hard-coded business thresholds (D5); migration discipline (one per milestone). |

## 10. Open questions

1. **D1 (`core.invoice.external_no`)** — approve the schema addition + data-model.md update?
   (Without it, idempotent invoice import is impossible.)
2. **D2 (export format/content)** — 4 files, Bosnian headers, `;` delimiter, no contacts. OK?
3. **D3 (synchronous import)** — OK for now (seconds at this volume)?
