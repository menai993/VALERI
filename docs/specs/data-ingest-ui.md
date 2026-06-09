# Spec — Data ingest UI (Phase 1: ERP data) + DI1 outline (Phase 2: documents)

## 1. Objective

Give the admin a way to **ingest data through the app**. The M2 ERP-ingest backend (CSV/Excel →
staging → idempotent upsert → SQL quality report) and a CLI already exist, but there is **no UI** —
the only entry points are the CLI or a raw API call. Phase 1 adds the admin "Uvoz podataka" screen
over the existing endpoints, plus a small import-history endpoint, CSV templates, and a one-click
post-import refresh (reusing the admin-recompute-panel). Phase 2 (DI1, documents+OCR) is a separate
milestone-sized track, outlined here and built as a dedicated follow-up.

Builds on: M2 (ingest pipeline), M8 (web + RBAC), admin-recompute-panel (recompute/scan endpoints).

## 2. Scope

**Phase 1 — in scope**
- Admin **Uvoz podataka** screen: pick/drag the 4 files (kupci/artikli/fakture/stavke) → POST → render
  the data-quality report; or trigger a server-`path` import.
- `GET /api/ingest/imports` — list past import runs (history).
- Downloadable **CSV templates** (exact headers + a sample row) generated client-side.
- **Post-import refresh**: after a successful import, one-click (or auto) recompute + scan via the
  existing `/api/admin/metrics/recompute` and `/api/admin/scan`, so the dashboard reflects new data.
- Nav item + route + bs/en strings.

**Phase 1 — out of scope (deferred)**
- Column-mapping UI / flexible headers / partial imports (the 4 fixed files + exact headers stay).
- Async/background import with progress streaming (synchronous is fine for pilot sizes).
- Undo/rollback of a committed import (the pipeline is idempotent; re-import corrects).

**Phase 2 — DI1 documents (separate follow-up, not built here)**
- Per `docs/document-intelligence.md`: file storage volume, `document`/`document_page`/
  `document_extraction` tables, born-digital parsing + OCR (Tesseract/OCRmyPDF bos/hrv) in the worker,
  classification, extraction → KB with provenance, the upload/library/review UI. Milestone-sized;
  spec'd and sequenced after Phase 1.

## 3. Files (Phase 1)

```
apps/api/valeri_api/
  api/ingest.py                 EDIT add GET /ingest/imports (list runs) + ImportRunSummary schema
apps/api/tests/
  test_ingest.py                EDIT/ADD: list endpoint returns runs; admin-only

apps/web/src/
  features/ingest/IngestPage.tsx    NEW  upload 4 files, report, templates, history, post-import refresh
  components/widgets/QualityReport.tsx NEW  renders the 6 quality sections (counts + rows)
  lib/api/client.ts             EDIT add api.upload(path, FormData) (no JSON content-type)
  lib/api/queries.ts            EDIT useImportMutation, useImportReport, useImportRuns
  lib/api/types.ts              EDIT ImportResult, ImportReport, ImportStats, QualityReport, ImportRunSummary
  lib/ingest/templates.ts       NEW  the 4 CSV templates (headers + sample row) as strings
  app/Sidebar.tsx               EDIT add "Uvoz" nav item (admin only)
  routes.tsx                    EDIT add /uvoz route (admin guard)
  lib/i18n/bs.ts, en.ts         EDIT strings
  test/ingest.test.tsx          NEW  renders, upload posts multipart, report shows, history lists
```

## 4. Data-model touchpoints

No migration. Reads `staging.import_run` (history list) and the existing report JSON. The import
itself (existing M2 code) writes `staging.*` and upserts `core.*`. Phase-1 additions are read-only
over `staging.import_run`.

## 5. API touchpoints

- Existing (unchanged): `POST /api/ingest/import` (multipart 4 files or `path`), `GET /api/ingest/report/{id}`.
- **New**: `GET /api/ingest/imports?limit=` (admin) → `{ items: [{ import_id, source, status, started_at, finished_at, stats? }] }`.
- Post-import refresh reuses `POST /api/admin/metrics/recompute` + `POST /api/admin/scan`.

## 6. Tests

Backend (`tests/test_ingest.py`):
- `test_list_imports_admin_only` — non-admin → 403.
- `test_list_imports_returns_runs` — after an import, the run appears with status/source/counts.

Web (`test/ingest.test.tsx`):
- renders the 4 file inputs + template buttons (admin); hidden/blocked for non-admin.
- selecting 4 files + submit → a multipart POST to `/api/ingest/import`; the returned report renders
  (e.g. a code-swap candidate row shows).
- the history table lists runs from `/api/ingest/imports`.

## 7. Acceptance criteria

- An admin opens **Uvoz**, drops the 4 export files, imports, and sees the quality report
  (dupes/renames/code-swaps/missing segments/orphans) with counts; a one-click **Preračunaj + skeniraj**
  refreshes metrics/signals so the dashboard updates.
- Template CSVs download with the exact headers.
- Past imports are listed; a non-admin cannot reach the screen or the endpoints (403).
- Numbers in the report come from SQL (the existing pipeline); no LLM is involved.

## 8. Principles compliance

| # | Principle | How |
|---|-----------|-----|
| 1 | AI computes no numbers | Import + quality report are pure SQL/Python; no LLM. |
| 4/5 | No source writes / read-only phase | Reads an export; writes only VALERI staging/core, never the ERP. |
| 6 | PII masking before LLM | N/A — no LLM in this path (PII lands in core as usual, masked later at LLM calls). |
| 7 | Append-only logs | `staging.import_run` records each run; no AI/decision rows needed (not a config change). |
| 9 | Analysis/recommendation/action tags | Admin operational screen, not an AI surface. |
| 10 | Reversible/admin | Import is admin-gated and idempotent; re-import corrects. RBAC enforced on every endpoint. |

## 9. Open questions

1. Post-import refresh: **auto** after every successful import, or a **button** the admin clicks? (Default: button, to keep import fast and the action explicit.)
2. Keep the server-`path` import option in the UI, or upload-only? (Default: upload-only in the UI; `path` stays available via API/CLI.)
3. DI1 (Phase 2): build right after Phase 1, or wait? (Default: separate follow-up after Phase 1 ships.)
