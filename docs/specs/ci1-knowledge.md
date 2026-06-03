# Spec — CI1: Knowledge base & conversational capture

**Track:** Client Intelligence (optional, owner-approved) · **Builds on:** M6 (LLM gateway + masking + `narrate_structured` + `ai_log`), M9 (conversation/chat + server-side entity resolution + tool catalog), M10–M11 (graduated autonomy + reversible `app.decision` + confirmation discipline) · **Status:** draft (awaiting owner review)

## 1. Objective

Turn what users say (in chat, and as notes) into a **structured, queryable knowledge base** about customers — qualitative facts, commercial events (deals/meetings/complaints), and customer-to-customer relationships — so later analysis can lean on it. This is the **CI1** milestone of the Client Intelligence track (`docs/client-intelligence.md`). Every message runs through a relevance gate + Tier-1 extraction (async, non-blocking) → server-side entity resolution → merge/dedup → **graduated apply by stakes**: high-confidence low-stakes records auto-save (reversible, shown); consequential/low-confidence/ambiguous records go to a **confirmation queue**, and any ambiguity (entity, reference, merge, value, conflict, new-vs-existing) raises **one short clarification** instead of a guess. Every record carries provenance + confidence + the raw utterance as evidence; numbers for analysis stay in SQL — the LLM only extracts and narrates.

## 2. Scope

### In scope
- KB tables (§2 of `client-intelligence.md`): `client_profile`, `client_fact`, `commercial_event`, `client_relationship`, `kb_extraction`; plus `customer_alias` + `clarification` (§8.4). One migration.
- Relevance gate + Tier-1 structured extraction (reject+retry), run **async** on every chat message and synchronously on `POST /kb/capture` / `POST /kb/notes`.
- Server-side entity resolution: `pg_trgm` similarity + full-text + `customer_alias` + conversation focus; ranked candidates with a distinguishing detail. The model never picks ids.
- Merge/dedup: supersede stale `(customer_id, fact_type, fact_key)` facts; maintain `client_profile.summary` (Tier-1 narration, Bosnian).
- Graduated apply by **confidence × stakes** (§8.2 matrix); thresholds in `app.rule_config`.
- Clarification policy (§8.3): one short, specific, tappable question per ambiguity (entity / reference / merge / value / conflict / new_entity); non-blocking; unanswered items stay in the queue.
- Provenance + confidence + evidence on every record; KB writes reuse `app.decision` (reversible) + `audit.ai_log`.
- Endpoints (§5): capture, notes, pending, items confirm/reject/edit, clarification answer, customer knowledge.
- Frontend: "Šta VALERI zna" client-360 panel, in-chat capture chip, review queue (Zabilješke) with clarification cards.
- Personal PII masked before the model; entity resolution on real names server-side.

### Out of scope (deferred)
- **CI2:** relationship-map view + `GET /kb/graph`; behavioral-expectation model; graph-aware rules; KB in the weekly owner report; `get_client_knowledge` investigation tool.
- Document-sourced facts (DI1: `source_document_id`/`source_page`).
- Phase-2 CRM `app.opportunity` linkage (a deal stays a `commercial_event`; no `opportunity_id` write).
- Worker-polled job queue for capture (CI1 uses FastAPI `BackgroundTasks` — see D1).
- Article/contact/supplier facts beyond what customer-centric extraction yields (resolution supports article/rep, but rules/UI stay customer-focused).

## 3. Files

```
apps/api/valeri_api/
  kb/
    __init__.py
    models.py            # SQLAlchemy: ClientProfile, ClientFact, CommercialEvent,
                         #   ClientRelationship, KBExtraction, CustomerAlias, Clarification + enum tuples
    schemas.py           # Pydantic: ExtractedFact/Event/Relationship, ExtractionResult,
                         #   ResolutionCandidate/Result, ClarificationRead, KbItemRead,
                         #   PendingQueue, KnowledgeResponse, CaptureResponse, NoteCreate, ClarificationAnswer
    prompts.py           # Bosnian gate + extraction + profile-summary prompts (cache-stable prefix)
    gate.py              # is_relevant(session, masked_text, client) -> bool  (Tier-1, ROLE_KB_GATE)
    extraction.py        # extract_candidates(...) -> ExtractionResult via narrate_structured
                         #   (ROLE_KB_EXTRACTION, text_field=None); writes app.kb_extraction + ai_log
    resolution.py        # resolve_mention(session, name, context) -> ResolutionResult
                         #   (pg_trgm + customer_alias + focus; ranked candidates + distinguishing detail)
    stakes.py            # classify_stakes(candidate) -> 'low'|'high' (rule_config-driven)
    merge.py             # merge_fact() supersede; refresh_profile_summary() (Tier-1, Bosnian)
    clarification.py     # raise_clarification(...) per §8.3; reads rule_config thresholds
    apply.py             # apply_candidate(...) -> auto-save (active) or proposed; writes kb_capture decision
    pipeline.py          # run_capture(session, *, message_id|None, text, user_id, customer_focus_id=None)
    service.py           # confirm/reject/edit item, answer_clarification, pending_queue, knowledge_for_customer
  api/kb.py              # the KB endpoints (router)
  api/customers.py       # (edit) GET /customers/{id}/knowledge delegates to kb.service
  api/chat.py            # (edit) schedule run_capture via BackgroundTasks after the reply (non-blocking)
  main.py                # (edit) mount kb_router
  llm/router/roles.py    # (edit) ROLE_KB_GATE, ROLE_KB_EXTRACTION, ROLE_KB_SUMMARY → tier1
  audit/models.py        # (edit) add 'kb_capture' to decision_kind_enum + DECISION_KINDS
  seed/rule_config.py    # (edit) seed kb.* thresholds (autosave/auto_attach/high_stakes)
  migrations/versions/0018_kb_knowledge.py   # enums + tables + pg_trgm + trgm GIN index + ALTER decision_kind

apps/api/tests/
  fixtures/kb/fakes.py            # FakeKbLLM: canned gate/extraction/summary responses keyed by text
  test_kb_extraction.py          # typed candidates; reject+retry; kb_extraction + ai_log; PII masked
  test_kb_resolution.py          # pg_trgm ranks Fupy~Fupupu; alias short-circuit; focus tiebreak
  test_kb_capture.py             # stated deal → active event; same_owner → proposed; auto-save decision
  test_kb_merge.py               # repeated fact supersedes (one active, superseded_by set); profile refresh
  test_kb_clarification.py       # Fupupu high-stakes ambiguous → proposed + clarification; answer → alias + decision
  test_kb_api.py                 # endpoints + RBAC + pending queue + decisions visible via /audit/decisions

apps/web/src/
  lib/api/types.ts                # (edit) KB types
  lib/api/queries.ts              # (edit) useCustomerKnowledge, useKbPending, useConfirmKbItem,
                                  #   useRejectKbItem, useEditKbItem, useAnswerClarification, useCaptureNote
  components/widgets/KnowledgePanel.tsx     # "Šta VALERI zna" (profile + facts + events + relationships)
  components/widgets/KbFactRow.tsx          # fact row: source + confidence chip + Undo/Edit
  components/widgets/ClarificationCard.tsx  # question + tappable options
  components/widgets/CaptureChip.tsx        # in-chat "VALERI je zabilježio: …" + Potvrdi/Poništi
  features/kb/ReviewQueuePage.tsx           # Zabilješke: proposed items + clarifications
  features/customers/CustomerDetailPage.tsx # (edit) mount KnowledgePanel
  features/chat/ChatPage.tsx                # (edit) refetch capture/pending after 'done' → CaptureChip
  app/Sidebar.tsx + routes.tsx              # (edit) add Zabilješke nav + route
  lib/i18n/bs.ts + en.ts                    # (edit) kb strings (bs default)
  test/kb-knowledge.test.tsx                # panel renders profile/facts/events/rel with source+confidence chips
  test/kb-review.test.tsx                   # queue renders proposed items + a clarification with tappable options
```

## 4. Data-model touchpoints

New (migration **0018**, `app` schema), exactly per `client-intelligence.md` §2 + §8.4:

- **Enums:** `fact_source('data','inferred','stated')`, `kb_status('proposed','active','superseded','rejected')`, `event_kind('deal','meeting','call','complaint','quote','visit','note','other')`, `rel_type('same_owner','same_group','chain','shared_decision_maker','referral','competitor','geographic_cluster','behavioral_twin','supplier_of')`, `clar_kind('entity','reference','merge','value','conflict','new_entity')`.
- **Tables:** `app.client_profile`, `app.client_fact` (dedup `(customer_id, fact_type, fact_key)`; `superseded_by` self-FK; partial index `WHERE status='active'`), `app.commercial_event`, `app.client_relationship` (dedup `(from,to,rel_type)`; consequential edges default `status='proposed'`), `app.kb_extraction`, `app.customer_alias` (`alias` PK → `core.customer`), `app.clarification`.
- **Reads:** `core.customer`/`article`/`sales_rep` (resolution), `app.message` (`source_message_id` evidence), `app.rule_config` (thresholds).
- **Extension + index:** `CREATE EXTENSION IF NOT EXISTS pg_trgm`; GIN trgm index on `core.customer(name)` for resolution.
- **Enum extension:** `ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'kb_capture'` + extend `DECISION_KINDS` (D2). Confirm of a proposed item = `approval`; reject = `rejection`; undo = `undo`; auto-save/edit = `kb_capture`.
- `app.decision` + `audit.ai_log` reused (no new audit tables). `client_fact`/`commercial_event` columns `source_document_id`/`source_page` are **DI1**, not added here.

## 5. API touchpoints (per `api-spec.md`/`client-intelligence.md` §5)

- `POST /api/kb/capture` `{text, customer_id?}` → runs the pipeline synchronously; returns `CaptureResponse {auto_saved[], proposed[], clarifications[]}`.
- `POST /api/kb/notes` `{customer_id, text}` → logs a note (a `message`-less utterance) and captures from it.
- `GET /api/kb/pending` → `{facts[], events[], relationships[], clarifications[]}` (status `proposed` + pending clarifications), each with its source sentence.
- `POST /api/kb/items/{id}/confirm` · `POST /api/kb/items/{id}/reject` · `PATCH /api/kb/items/{id}` `{kind, ...fields}` → each writes a reversible `app.decision`; `kind ∈ {fact,event,relationship}` selects the table.
- `POST /api/kb/clarifications/{id}/answer` `{option}` → applies the chosen action (link / pick_other / create_prospect / merge / …); re-links + activates the target record, may write `customer_alias`, writes a reversible `decision` (D5).
- `GET /api/customers/{id}/knowledge` → `KnowledgeResponse {profile, facts[], events[], relationships[]}` (RBAC: a rep only its own customers).
- **Deferred (CI2):** `GET /api/kb/graph`.
- Capture also runs automatically (async) inside `POST /chat/sessions/{id}/messages`.

## 6. Tests (TDD on the trust-critical pipeline; fakes keep LLM off the network)

**Backend** (`FakeKbLLM` returns canned gate/extraction JSON; deterministic):

- `test_kb_extraction.py`
  - `test_extraction_returns_typed_candidates` — a deal sentence → `ExtractionResult` with one event + intent fact + the mentioned names.
  - `test_malformed_extraction_rejected_and_retried` — bad JSON then good → one accepted result; rejects logged to `ai_log`.
  - `test_extraction_logs_kb_extraction_and_ai_log` — one `app.kb_extraction` row + ≥1 `audit.ai_log` row per pass.
  - `test_pii_masked_before_model` — masked payload sent to the fake has a pseudonym for the known customer and **no** email/phone/address (assert on captured input).
  - `test_relevance_gate_skips_pure_question` — "koliki je promet?" → gate false → no extraction call.
- `test_kb_resolution.py`
  - `test_trgm_ranks_close_customer` — "Fupupu" → top candidate Fupy with similarity + distinguishing detail (segment, last order).
  - `test_alias_short_circuits` — a `customer_alias` "Fupupu"→142 resolves directly (no clarification).
  - `test_focus_breaks_ties` — current-customer focus wins among near-equal candidates.
- `test_kb_capture.py`
  - `test_stated_deal_creates_resolved_event` — deal sentence → one `commercial_event` (kind=deal), `customer_id` resolved, `value` stored (source=stated), `status='active'`, evidence = raw message, `confidence` set. *(acceptance 1)*
  - `test_same_owner_relationship_goes_to_queue` — "isti vlasnik kao …" → `client_relationship(rel_type=same_owner, status='proposed')`; **not** active, **no** scanner effect. *(acceptance 2)*
  - `test_autosave_writes_reversible_decision` — a low-stakes high-confidence fact auto-saves `status='active'` + one `decision(kind='kb_capture', reversible=true)`; `client_profile.summary` refreshed. *(acceptance 5)*
- `test_kb_merge.py`
  - `test_repeated_fact_supersedes` — same `(customer, fact_type, fact_key)` twice → first `status='superseded'` with `superseded_by`, exactly one `active`; no duplicate. *(acceptance 3)*
- `test_kb_clarification.py`
  - `test_high_stakes_ambiguous_name_not_autoattached` — "kupac Fupupu kasni s plaćanjem" → `client_fact(payment_late, status='proposed', customer_id NULL)` + a `clarification(kind='entity')` whose question is "da li ste mislili Fupy … ili novi kupac?" with link/pick_other/create_prospect options; nothing lands on Fupy. *(acceptance 4)*
  - `test_answer_links_and_writes_alias` — answering "Da, Fupy" → fact `status='active'`, `customer_id=142`, a `customer_alias('Fupupu'→142)`, one reversible `decision`. *(acceptance 4)*
  - `test_reject_does_not_relink` — "Nije" → fact stays unresolved/becomes prospect; no alias; bad match not re-suggested.
  - `test_low_confidence_fact_queued` — extraction confidence below `kb.fact_autosave_confidence` → proposed, not auto-saved.
- `test_kb_api.py`
  - `test_capture_and_pending_roundtrip` — `POST /kb/capture` then `GET /kb/pending` shows proposed items + clarifications.
  - `test_confirm_reject_edit_write_decisions` — each writes a `decision` visible via `GET /audit/decisions`; reject sets `status='rejected'`.
  - `test_knowledge_rbac` — a rep gets 403/empty for a customer not theirs; owner sees the full knowledge payload.
  - `test_notes_capture` — `POST /kb/notes` extracts and stores with provenance.

**Frontend** (vitest, mocked fetch):
- `kb-knowledge.test.tsx` — `KnowledgePanel` renders profile summary, facts grouped by type with source + confidence chips and Undo/Edit, an events timeline, and a relationships list.
- `kb-review.test.tsx` — `ReviewQueuePage` renders proposed items with their source sentence and a `ClarificationCard` with tappable options (link / novi kupac).

## 7. Acceptance criteria (matches IMPLEMENTATION-PLAN CI1)

1. A rep stating a deal → a **resolved** `commercial_event` linked to the right customer, raw message as evidence, a confidence.
2. A stated `same_owner` relationship lands in the **confirmation queue** (`status='proposed'`), **not** auto-applied.
3. A repeated fact **supersedes** (no duplicate; one `active`).
4. A high-stakes fact about an ambiguous name ('Fupupu' ~ Fupy) is **not** auto-attached — it raises a "da li ste mislili… / novi kupac?" clarification and stays `proposed` until answered; confirming writes a `customer_alias`.
5. Every KB write is **reversible and shown** (an `app.decision`, visible via `/audit/decisions`).
6. **No analysis number is computed by the LLM**; personal PII is **masked before the model**.
7. Reviewers green: `principle-reviewer`, `selfconfig-reviewer`, `/decision-audit`.

## 8. Principles compliance

| # | Principle | How CI1 honors it |
|---|-----------|-------------------|
| 1 | AI doesn't compute numbers | LLM extracts qualitative facts + a *stated* deal value tagged `source='stated'` (stored as data, not a computed aggregate); any trend/aggregate over events is SQL. `narrate_structured(text_field=None)` — no narrative-number contract needed because extraction emits structured fields, not prose figures. |
| 2 | Evidence on every record | Every fact/event/edge stores `source_message_id` (+ raw `evidence_span`); `kb_extraction.raw_text` keeps the full utterance. |
| 3 | Confidence on every conclusion | `confidence` + `conf_band` on every `client_fact`/`commercial_event`/`client_relationship`; low confidence → queue, never auto-save. |
| 4 | No writes to source ERP | KB writes only `app.*` (VALERI's own DB); no ERP connection touched. |
| 5 | Read-only/staging in phase 1 | Resolution does read-only SELECTs on `core.*`; KB is VALERI-native. |
| 6 | PII masking before AI | Extraction/gate/summary calls run on masked text (known customers → pseudonyms; email/phone/address stripped). Entity resolution runs server-side on real names, never via the model. Test asserts the masked payload. |
| 7 | Append-only logs | Each LLM pass → `audit.ai_log`; each apply/confirm/reject/edit/undo → append-only `app.decision`; `kb_extraction` is insert-only provenance. |
| 8 | Feedback loop is core | Confirmations/rejections/clarification answers are the loop: they write `customer_alias`, suppress bad matches, and improve resolution (§8.5). |
| 9 | Analysis/recommendation/action | Captured facts = Analiza; suggested links = Preporuka; auto-saved writes = Akcija (register surfaced on KB UI + decision feed). |
| 10 | Approval / reversible self-config | Consequential records (relationships, negative facts, large stated values) and any ambiguity require confirmation; auto-saves are **internal, reversible, and shown** (a `kb_capture` decision). Nothing customer-facing is sent. |

## 9. Open questions (decision defaults — confirm or override)

- **D1 — async transport for chat capture:** FastAPI `BackgroundTasks` (in-process, fresh session, non-blocking) **[recommended]** vs a worker-polled queue table. Default: BackgroundTasks; worker-poll deferred.
- **D2 — decision kinds:** add a single `kb_capture` value (auto-save + edit); reuse `approval`/`rejection`/`undo` for confirm/reject/undo **[recommended]** vs add `kb_confirm`/`kb_reject`/`kb_edit`.
- **D3 — high-stakes set:** `payment_*`, negative/`complaint` facts, relationships, and stated `value ≥ kb.high_stakes_value` are high-stakes (always confirm). Default set above; tunable in `rule_config`.
- **D4 — thresholds (`app.rule_config`, rule=`kb`):** `fact_autosave_confidence=0.75`, `auto_attach_similarity=0.80`, `high_stakes_always_confirm=true`, `high_stakes_value=10000`. Default these.
- **D5 — clarification answer endpoint:** add `POST /api/kb/clarifications/{id}/answer` (beyond the original api-spec list) **[recommended]**.
- **D6 — relationship graph / map:** defer `GET /kb/graph` + the map to **CI2** (per the plan). Confirm.
- **D7 — capture chip transport:** after the SSE `done`, the ChatPage refetches `/kb/pending` (+ knowledge) and renders `CaptureChip` for items from this message **[recommended]** vs a synchronous inline preview (would block — rejected).
- **D8 — resolution unification:** keep M9's `conversation/resolution.py` (substring, for tool param refs) and add the richer `kb/resolution.py` now; unify in a later pass **[recommended]**.
- **D9 — article/rep resolution:** support resolving article/rep mentions in `kb/resolution.py`, but keep CI1 rules/UI customer-centric (article/contact facts deferred). Default.
- **D10 — enum downgrade:** migration `0018` downgrade drops the new tables/enums but **leaves** the `decision_kind` `kb_capture` value (Postgres can't drop an enum value cleanly; standard Alembic practice). Confirm acceptable.
