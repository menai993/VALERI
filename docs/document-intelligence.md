# VALERI — Document Intelligence: import & understand documents (`docs/document-intelligence.md`)

Companies upload **PDF / DOCX / XLSX** — born‑digital *or* scanned paper. VALERI stores the file, extracts its content (OCR for scans), works out what the document is, turns it into **structured knowledge** (facts/events with document+page provenance) and, in DI2, into **retrievable text** so the LLM can read a document as context. It reuses the knowledge base and the entity‑resolution + clarification machinery from `client-intelligence.md`. Build **after CI1** (it writes into the same KB and needs the confirmation/decision plumbing). Email is a later source (see §11). Conventions per `data-model.md` / `api-spec.md` / `frontend-spec.md`.

> The PDFs/scans are **uploaded through the app** (the upload screen below) and stored on the server — they are not committed to the repo. Only this spec goes in `docs/`.

## 1. Pipeline (stage by stage)

1. **Ingest & store.** Accept PDF/DOCX/XLSX; store the original on‑prem (a files volume / object storage) with a `document` row (filename, type, company, uploader, SHA‑256 hash for dedupe, status). Re‑uploads of the same hash are detected, not duplicated.
1. **Extract text** (born‑digital vs scanned — see §2).
1. **Classify** the document: invoice / contract / price_list / delivery_note / offer / statement / other. Classification drives extraction.
1. **Extract structure** per type: invoice → customer + line items + totals + date; contract → parties + term + key clauses; price_list → articles + prices; etc.
1. **Resolve & connect** the document’s customer/articles to existing `core` entities using the **same entity‑resolution + clarification policy** (§8 of `client-intelligence.md`): ranked candidates, “da li ste mislili… / novi kupac?”, confidence. A document about “Fupupu” is handled exactly like a rep saying it.
1. **Write to the KB with provenance.** Extracted facts/events become `client_fact` / `commercial_event` rows whose evidence points back to the **document + page (+ region)**. High‑stakes or low‑confidence extractions go to the confirmation queue, never silently in.
1. **Index for retrieval (DI2).** Chunk the text, embed it, store vectors in **pgvector** so “what do we know about X” and the investigation agent can pull the relevant passages as context, each with a citation back to the file/page.

## 2. Born‑digital vs scanned (the hard part)

- **Detect:** if a PDF has little/no extractable text layer, treat it as **scanned**.
- **Born‑digital** → parse directly: PDF text/tables (PyMuPDF/pdfplumber), DOCX (python‑docx/mammoth), XLSX (openpyxl/pandas). High fidelity.
- **Scanned paper** → rasterize (pdf2image/poppler) then **OCR**. Use Tesseract via OCRmyPDF with the **Bosnian/Croatian Latin language data** (`bos`, `hrv`, `srp`) so diacritics (č, ć, ž, š, đ) are recognised; OCRmyPDF also yields a searchable PDF. OCR returns a **confidence**; the page text is stored with it.
- **Honest limits:** clean scans of typed invoices work well; handwriting, faint stamps, and messy multi‑column tables will miss — those route to human review. Set this expectation up front.

## 3. Trust boundary (what keeps it safe)

- **The document never overrides ERP numbers your transactional data already has.** Invoices/turnover come from the ERP (Principle 1 — numbers from SQL). Documents add *new* context (contracts, terms, prices, paper‑only deals); they don’t rewrite transactional figures. If a scanned invoice’s OCR’d total disagrees with the ERP, **the ERP wins and the discrepancy is flagged** — an OCR guess never edits a financial number.
- **OCR confidence propagates.** Anything from a scan is tagged lower‑trust; consequential facts from scans always require confirmation.
- **The LLM extracts and reads; it doesn’t compute.** It classifies, pulls fields, and reads passages for context; figures stay in SQL and document text is retrieved as evidence, never invented.
- **Privacy.** Documents are full of PII — keep masking before the model where identity isn’t needed, keep the Zero‑Data‑Retention posture, and remember the files live on your server.

## 4. Data model (`app`; additions)

```sql
CREATE TYPE doc_type   AS ENUM ('invoice','contract','price_list','delivery_note','offer','statement','other');
CREATE TYPE doc_source AS ENUM ('upload','scan','email');
CREATE TYPE doc_status AS ENUM ('uploaded','parsing','ocr','extracting','needs_review','processed','failed');

CREATE TABLE app.document (
  id              BIGSERIAL PRIMARY KEY,
  legal_entity_id BIGINT REFERENCES core.legal_entity(id),
  filename        TEXT NOT NULL,
  mime_type       TEXT NOT NULL,
  doc_type        doc_type,
  source          doc_source NOT NULL DEFAULT 'upload',
  is_scanned      BOOLEAN NOT NULL DEFAULT false,
  ocr_confidence  NUMERIC(4,3),           -- avg OCR confidence if scanned
  file_path       TEXT NOT NULL,          -- on-prem storage path
  sha256          TEXT UNIQUE,            -- dedupe re-uploads
  uploaded_by     BIGINT,
  status          doc_status NOT NULL DEFAULT 'uploaded',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.document_page (
  id             BIGSERIAL PRIMARY KEY,
  document_id    BIGINT NOT NULL REFERENCES app.document(id),
  page_no        INT NOT NULL,
  text           TEXT,                    -- extracted/OCR'd text
  ocr_confidence NUMERIC(4,3),
  image_ref      TEXT,                    -- optional rasterised page (for evidence crops)
  layout         JSONB                    -- optional blocks/tables/bboxes
);
CREATE INDEX ix_docpage_doc ON app.document_page(document_id);

CREATE TABLE app.document_extraction (    -- candidate records pulled from a document (mirrors kb_extraction)
  id          BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES app.document(id),
  page_no     INT,
  extracted   JSONB NOT NULL,             -- candidate fields/facts/events + entities mentioned
  model       TEXT,
  confidence  NUMERIC(4,3),
  status      kb_status NOT NULL DEFAULT 'proposed',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- DI2: retrieval index
CREATE TABLE app.doc_chunk (
  id           BIGSERIAL PRIMARY KEY,
  document_id  BIGINT NOT NULL REFERENCES app.document(id),
  page_no      INT,
  chunk_no     INT NOT NULL,
  text         TEXT NOT NULL,
  token_count  INT,
  embedding    vector(1024)               -- dim must match the chosen embedding model
);
CREATE INDEX ix_doc_chunk_vec ON app.doc_chunk USING hnsw (embedding vector_cosine_ops);
```

Add document provenance to KB records (additive):

```sql
ALTER TABLE app.client_fact      ADD COLUMN source_document_id BIGINT REFERENCES app.document(id), ADD COLUMN source_page INT;
ALTER TABLE app.commercial_event ADD COLUMN source_document_id BIGINT REFERENCES app.document(id), ADD COLUMN source_page INT;
```

A document‑sourced fact links `source_document_id` + `source_page`; the page text (and optional cropped image region) is the evidence shown to the human.

## 5. Resolution & clarification

Reuse `client-intelligence.md` §8 verbatim: ranked candidates with similarity+confidence, the confidence×stakes matrix, the “did you mean… / is this new?” clarification (entity/reference/merge/value/conflict), the `customer_alias` learning loop. The document is shown as context in the clarification. Nothing high‑stakes from a scan is auto‑attached.

## 6. Classification & extraction

- **Tables first, deterministically** (pdfplumber/camelot/openpyxl), then the LLM maps rows to fields — don’t ask the model to read raw numbers it could miscopy.
- **LLM with structured output** (Pydantic, reject+retry) for classification and for free‑text fields/clauses; OCR text passes through with its confidence; log to `document_extraction` and `audit.ai_log` (feature = `doc_extraction`, for the cost dashboard).
- Use Tier‑1 for classification/simple extraction, Tier‑2 for messy contracts; route per `llm-cost.md`.

## 7. Retrieval / RAG (DI2)

- Chunk page text (overlapping windows), **embed**, store in `app.doc_chunk` (pgvector); query by cosine similarity to fetch the top passages, then the LLM reads them as context and **cites the file/page**.
- **Embeddings note (important):** Claude is generative — it does not produce embeddings. For an on‑prem, ZDR‑friendly setup, run a **local multilingual embedding model** (e.g. `bge‑m3` or `multilingual‑e5‑large`, which handle Bosnian/Latin) on CPU so document text never leaves the server and there’s no per‑token cost; set `vector(dim)` to match it. Alternatively use a hosted embeddings provider (e.g. Voyage) under a data agreement. Either way, **the generative tiers stay hosted Claude** — only the small embedding model is local. (This is a deliberate, contained exception to “no local model.”)
- **Boundary:** the vector index is for *recall* — finding relevant text to show a human or feed the LLM. It never holds facts or numbers; those stay in the typed tables with provenance. Embeddings retrieve; SQL computes; the LLM narrates.

## 8. API

- `POST /api/documents/upload` (multipart) → `{document_id}`; processing runs async in the worker.
- `GET /api/documents?type=&status=&company=` ; `GET /api/documents/{id}` → status + pages + extracted records ; `GET /api/documents/{id}/file` → original.
- `POST /api/documents/{id}/reprocess`.
- Extraction review reuses `/api/kb/pending` + `/api/kb/items/{id}/confirm|reject` (document‑sourced items show the page as evidence).
- **DI2:** `GET /api/documents/search?q=` → semantic passage search (pgvector) with file/page citations; plus a read‑only `search_documents` tool added to the safe catalog for the investigation agent.

## 9. Frontend

- **Upload screen:** drag‑and‑drop; type auto‑detected; a progress state (parsing → OCR → extracting → review/processed); scanned files flagged.
- **Documents library:** filter by type/status; a **document detail** view = the original file viewer + per‑page text (OCR’d text carries a low‑trust badge) + “Šta je VALERI izvukao iz ovog dokumenta” (the extracted records) with confirm/undo.
- **Extraction‑review queue:** the same KB review queue, with document‑sourced items showing the page snippet/region as evidence.
- **DI2:** document search; in chat/investigation, cited passages link back to the file/page.

## 10. Dependencies & infra (new)

- **Parsing:** PyMuPDF/pdfplumber (PDF), python‑docx/mammoth (DOCX), openpyxl/pandas (XLSX), camelot (PDF tables, optional).
- **OCR:** Tesseract + OCRmyPDF + `bos`/`hrv`/`srp` language data; pdf2image + poppler to rasterise. Runs in the **worker** (CPU).
- **Storage:** a files volume (or MinIO/object storage) for originals + page images.
- **DI2:** the **pgvector** extension in the existing Postgres (no separate DB) + a local multilingual embedding model (or hosted embeddings). These are the only new dependencies, and they belong to DI2.

## 11. Milestones (see the plan / prompts)

- **DI1 — Ingestion, OCR & extraction → KB** (after CI1): storage, born‑digital parsing, OCR for scans (Bosnian), classification, structured extraction, resolution via §8, KB write‑back with document+page provenance and the confirmation queue, the upload + library + review UI. No embeddings yet.
- **DI2 — Document retrieval (pgvector RAG)** (after DI1): chunk+embed+index, semantic search, the `search_documents` tool for the agent, cited passages in chat/investigation. pgvector + embedding model added here.
- **Later — Email ingestion:** parse `.eml`/`.msg`, handle threads, run the same pipeline; specify when needed.