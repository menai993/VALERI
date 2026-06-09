# Spec — DI1: Document ingestion → knowledge base

Implements the DI1 milestone from `docs/document-intelligence.md`. Because OCR needs heavy
system packages in the image, DI1 is split into two slices so value ships without the OCR
infrastructure first.

- **DI1a — born-digital** (this spec, buildable now): storage + tables + parse PDF/DOCX/XLSX +
  classify + extract → KB with document+page provenance + confirmation queue + upload/library/review UI.
  Scanned files are detected and flagged "needs OCR" (not processed yet). Pure-Python parsing only.
- **DI1b — OCR for scans** (follow-up): Tesseract/OCRmyPDF/poppler + bos/hrv language data in the
  worker image; rasterize + OCR scanned PDFs.
- **DI2 — retrieval/RAG** (later): pgvector + embeddings.

Builds on: CI1 (the KB tables, confirmation queue, `app.decision`, entity resolution/clarification),
M2 (admin ingest patterns), admin-recompute/ingest UI patterns, M6 LLM gateway (structured extraction).

## 1. Objective

Let an admin upload **PDF/DOCX/XLSX** business documents through the app; VALERI stores the original
on-prem, extracts the text/tables, classifies the document, pulls structured fields, resolves the
customer/articles to `core` entities, and writes facts/events into the **knowledge base with
document+page provenance** — high-stakes/low-confidence items going to the existing confirmation
queue. Documents add context; they never overwrite ERP numbers (a doc total disagreeing with the ERP
is flagged, not written).

## 2. Scope

**DI1a — in scope**
- File storage on-prem (a `files` volume) + `document` / `document_page` / `document_extraction` tables.
- Born-digital parsing: PDF text/tables (PyMuPDF + pdfplumber), DOCX (python-docx), XLSX (openpyxl).
- Scanned-vs-digital detection (a PDF with ~no text layer → `is_scanned=true`, status `needs_review`,
  not auto-extracted).
- Classification (invoice/contract/price_list/delivery_note/offer/statement/other) + structured
  extraction via the Tier-1 LLM (Pydantic, reject+retry); deterministic table parse first, then the
  model maps rows → fields (never reads raw numbers to copy).
- Entity resolution + clarification reusing CI1 §8 (ranked candidates, confidence×stakes, the
  `clarification` queue) — a document about an ambiguous customer asks, doesn't guess.
- KB write-back to `client_fact` / `commercial_event` with `source_document_id` + `source_page`;
  graduated apply (auto-save low-stakes; high-stakes/scanned/low-confidence → confirmation queue).
- SHA-256 dedupe of re-uploads.
- ERP-guard: an extracted invoice total that disagrees with an existing ERP invoice is **flagged**
  (a `proposed` discrepancy note), never written over the ERP figure.
- Async processing in the worker (a `document` queue poll, mirroring the M13 investigation poll) so a
  large parse/LLM pass doesn't block the upload request.
- Frontend: upload screen, documents library (filter by type/status), document detail (file link +
  per-page text + extracted records with confirm/undo); extraction review reuses the CI1 queue.

**Out of scope (later slices)**
- OCR for scanned paper (DI1b). DI1a flags scans; it does not read them.
- pgvector retrieval / `search_documents` tool / cited passages (DI2).
- Email ingestion.

## 3. New dependencies (DI1a)

Pure-Python parsing wheels: `pymupdf` (PDF text), `pdfplumber` (PDF tables), `python-docx` (DOCX);
`openpyxl` already present. **No Tesseract/poppler/OCRmyPDF in DI1a** (deferred to DI1b).

**Storage = MinIO (decided).** Add a `minio` service to `infra/docker-compose.yml` (S3-compatible,
on-prem) and the `boto3` client (S3 API) to the api/worker deps. Config: endpoint, access/secret keys
(Docker secrets/.env), bucket `valeri-documents`. `storage.py` wraps put/get/exists by SHA-256 key.

## 4. Data model (one migration: `0021_documents.py`)

New `app` enums + tables per `docs/document-intelligence.md` §4:
- `doc_type`, `doc_source`, `doc_status` enums.
- `app.document` (filename, mime_type, doc_type, source, is_scanned, ocr_confidence, file_path,
  sha256 UNIQUE, uploaded_by, status, created_at).
- `app.document_page` (document_id, page_no, text, ocr_confidence, image_ref, layout).
- `app.document_extraction` (document_id, page_no, extracted JSONB, model, confidence, status,
  created_at).
- `ALTER app.client_fact ADD source_document_id, source_page`; same on `app.commercial_event`
  (additive, nullable).

No `doc_chunk`/pgvector (DI2). Reuses `app.decision`, `app.clarification`, `app.customer_alias`.

## 5. Backend files

```
apps/api/valeri_api/documents/
  models.py        Document, DocumentPage, DocumentExtraction ORM
  schemas.py       Pydantic: upload result, document detail, extraction candidates (LLM output)
  storage.py       save original to the files volume + SHA-256 hash + dedupe lookup
  parse.py         born-digital parsers (PyMuPDF/pdfplumber/python-docx/openpyxl) → pages + tables
  classify.py      Tier-1 classification (structured output)
  extract.py       per-type field extraction (deterministic tables → Tier-1 field map)
  pipeline.py      orchestrate: store → parse → detect scanned → classify → extract → resolve → KB write
  prompts.py       Bosnian classification/extraction prompts
apps/api/valeri_api/api/documents.py    routers (upload/list/detail/file/reprocess)
apps/api/valeri_api/worker + scanner/scheduler.py   add a document-queue poll job
apps/api/migrations/versions/0021_documents.py
```
Reuses: `valeri_api/kb/` (resolution, clarification, apply, merge, models), `llm/` (gateway, masking,
structured), `audit/` (`ai_log` feature='doc_extraction', `decision`).

## 6. Frontend files

```
apps/web/src/features/documents/DocumentsPage.tsx    upload + library
  .../DocumentDetailPage.tsx                         file link + per-page text + extracted records
apps/web/src/components/widgets/DocumentUpload.tsx   drag-drop, status (parsing→extracting→review/processed)
apps/web/src/lib/api/{queries,types}.ts              document hooks/types
apps/web/src/{routes.tsx, app/Sidebar.tsx}           /dokumenti route + admin nav item
apps/web/src/lib/i18n/{bs,en}.ts                      strings
```
Review reuses the existing CI1 review queue (document-sourced items show the page snippet as evidence).

## 7. API (per `document-intelligence.md` §8)

- `POST /api/documents/upload` (multipart) → `{document_id}`; processing async in the worker.
- `GET /api/documents?type=&status=` ; `GET /api/documents/{id}` (status + pages + extracted) ;
  `GET /api/documents/{id}/file` (original).
- `POST /api/documents/{id}/reprocess`.
- Review via existing `/api/kb/pending` + `/api/kb/items/{id}/confirm|reject`.
All admin (upload/reprocess) / owner+admin (read), mirroring ingest RBAC.

## 8. Tests (TDD on the trust-critical parse+extract)

- `test_documents_storage`: SHA-256 dedupe — re-upload of the same bytes returns the same document, no duplicate.
- `test_parse_born_digital`: a fixture PDF/DOCX/XLSX → pages with expected text/tables.
- `test_scanned_detection`: a text-less PDF → `is_scanned=true`, status `needs_review`, NOT extracted.
- `test_invoice_extraction_to_kb`: a born-digital invoice → a `commercial_event`/fact resolved to the
  right `core.customer`, with `source_document_id`+page provenance and confidence (LLM faked).
- `test_erp_guard`: an extracted total disagreeing with an existing ERP invoice is flagged, not written.
- `test_ambiguous_customer_clarifies`: an ambiguous customer name → a clarification (reuses CI1), record stays `proposed`.
- RBAC: non-admin cannot upload/reprocess (403).
- Web: upload renders status; processed document shows extracted records; review confirm works.

## 9. Acceptance (DI1a)

A born-digital invoice uploads, parses, classifies, and extracts customer+lines+total resolved to the
right `core` customer with document+page evidence + confidence; a scanned PDF is stored and **flagged
needs-OCR** (not extracted); a re-uploaded identical file is deduped; an extracted total disagreeing
with the ERP is flagged not written; an ambiguous name triggers the CI1 clarification; non-admins are
blocked. Numbers come from SQL/tables; the LLM only classifies/maps/extracts. Run principle-reviewer +
selfconfig-reviewer + /decision-audit.

## 10. Principles compliance (summary)

1 numbers-from-SQL: tables/ERP win; LLM extracts fields, never computes aggregates · 2/3 every KB
record carries evidence(document+page)+confidence · 4/5 reads uploaded files, writes only VALERI
storage/KB, never the ERP; ERP figures are authoritative · 6 PII masked before the LLM (identity
resolved server-side) · 7 `ai_log`(doc_extraction) + reversible `decision` per KB write · 8 the
confirmation/clarification feedback loop is reused · 9 captured facts=Analiza, suggestions=Preporuka ·
10 every KB write reversible+shown; scanned/high-stakes never auto-applied.

## 11. Open questions

1. **OCR timing**: ship DI1a (born-digital) first and do DI1b (OCR system deps in the worker image)
   as a separate follow-up? (Recommended — keeps the image lean and value early.)
2. **Processing model**: async via a worker document-queue poll (recommended, matches M13), or
   synchronous on upload (simpler, but a slow LLM pass blocks the request)?
3. **Storage**: a Docker named volume `valeri_files` mounted at `/app/data/documents` on api+worker
   (recommended) vs. MinIO/object storage (heavier).
4. **Scope of DI1a extraction**: all six doc types, or start with **invoice + contract + price_list**
   (the highest-value) and treat the rest as `other` (store + classify, no field extraction yet)?
