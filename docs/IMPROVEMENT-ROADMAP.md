# VALERI — Improvement Roadmap (`docs/IMPROVEMENT-ROADMAP.md`)

**Status:** proposed (2026-06-09) · **Source:** full-codebase audit (backend logic + LLM usage + frontend UX) on `main` @ `1c2a236`.
**How to use:** same working rhythm as `IMPLEMENTATION-PLAN.md` — one phase per session, `/spec` first, Plan Mode, TDD on trust-critical code, reviewer subagents, stop on divergence. A paste-ready prompt is included per phase.

---

## 1. Where the app stands (audit verdict)

**Architecture is sound.** Numbers-from-SQL, masking, append-only audit, register tags, graduated autonomy, approval gates, template fallbacks, tier routing + cascade — all verified working. M0–M14, C-CRM1/2, CI1/2, CSA phases 1–3b, admin recompute, and the data-ingest UI are live.

**The gaps are in three buckets:**

1. **Broken/missing loops in the UI** — backend capability exists with **no usable front door**:
   - There is **no approvals screen**: `useApprovals()`/`useApprovalDecision()` exist but are mounted nowhere — the owner cannot approve a customer draft in-app (`lib/api/queries.ts:326-347`).
   - The **notifications bell is decorative** (no badge, no click — `app/TopBar.tsx:63-69`); nobody learns that VALERI is waiting on them.
   - **Task completion and activity logging are disconnected** — `useLogActivity()` is never mounted; a rep closes a task but can't record what happened (`features/tasks/TasksPage.tsx:71-96`).
   - **Quick actions ("Nova analiza", "Novi zadatak") have no handlers** (`app/Sidebar.tsx:78-89`); investigations are buried two levels deep; customer-detail task/signal rows aren't clickable; no "Danas" view anywhere.

2. **Operational blind spots** — fine in dev, dangerous in a pilot:
   - **Worker jobs fail silently** (exception → log → continue; no failure counter, no alert — `scanner/scheduler.py:48-65`). A broken scan could go unnoticed for weeks.
   - **No LLM cost visibility**: `ai_log` stores tokens/latency but nothing aggregates them; no budget, no alerts (plan X1 unbuilt).
   - **No API rate limiting** (chat spam → unbounded LLM spend), **minimal health check** (DB only — no LiteLLM/worker probe), **no backup restore-verification**, no login throttle/CSRF/token-refresh.
   - **Scanner runs blind on stale data** — no freshness check that `core.invoice` has recent rows before scanning.

3. **Planned features not yet built:** the **Daily Radar / Airtable bridge** (the new business requirement — plan approved, nothing implemented), **DI1 document pipeline** (migration `0023` + models exist; **no** upload API, parsing, OCR, classification, extraction→KB, or UI — a dead schema), **DI2 pgvector RAG**, **X2 language enforcement** (column exists; prompts don't honor it), **customer-message transport** (approval gate exists, send is a stub — `approvals/workflow.py:128-147`), email ingestion.

---

## 2. LLM usage today & the strategy

**Measured today (per the audit):**

| Path | Calls | Tier | Mode |
|---|---|---|---|
| Chat — simple question | 2 (intent + answer narration) | tier1 | interactive |
| Chat — agentic analysis (CSA) | up to 6 (intent + ≤4 act loop + synthesis) | tier1, cascade↑ | interactive |
| Chat — KB capture (after reply) | 2–3 (gate + extraction + summary) | tier1 | synchronous, adds latency |
| Daily scan narration (task bodies) | per new signal | tier1 | scheduled |
| Weekly cycle (report + drafts + audit) | ~10–15 | tier1/tier2 | scheduled, **not** Batch API |
| Investigations | bounded by caps | tier2/tier2_strong | async |

Prompt caching ✅, role routing ✅, cascade ✅, Pydantic-validated outputs ✅. **Missing:** Batch API on scheduled work, any cost accounting/budget, per-feature caps, answer caching, rate limiting.

**The strategy (what "best LLM usage" means for this platform):**

1. **Keep the discipline that already works** — LLM never computes numbers; masked payloads; tight Pydantic outputs; explicit JSON-shape prompts (the CI1 fix proved this cuts calls ~6×); template fallbacks everywhere.
2. **Make spend visible before making it bigger** — ship X1 (cost columns + `llm_pricing`/`llm_budget` + "Troškovi AI" dashboard + 80% alerts + per-feature daily caps) **before** Daily Radar multiplies scheduled narration. Optimize **cost per useful task**, not raw spend.
3. **Move every non-interactive call to the Batch API** (weekly report sections, customer drafts, over-suppression audit, bulk task narration) — ~50% price for the same output.
4. **Cut interactive latency, don't add calls** — make chat KB-capture truly non-blocking again (emit the `capture` SSE event from a post-reply task with a 5s cap), cache repeated dashboard/chat answers for a short TTL, keep ~60–70% of calls on Haiku (measure it once X1 exists).
5. **Ground, then generate (after DI2)** — retrieval feeds passages as *evidence with citations*; the vector index never holds numbers. New LLM surfaces (Radar day-summary, document field-mapping) follow the same `narrate_structured` + number-contract pattern — no new free-form paths.
6. **Guard the gates** — rate-limit chat per user, cap investigations/day, keep the KB relevance gate; cascade stays the exception, not the norm.

---

# PHASES

Ordered by value-vs-risk: close the human loop first (the pilot's daily experience), make operations safe, make spend visible, then ship the big new capability (Daily Radar/Airtable), then documents, then polish.

## P1 — Close the loop: approvals, notifications, activity, "Danas" (UX)

**Objective:** every approval/confirmation VALERI produces is reachable, visible, and one tap away; reps log what happened where they work.
**Builds on:** M7 approvals API, C-CRM2 activity API, CI1 review queue — all backend-complete, UI-absent.
**Tasks:**
- **Odobrenja screen** (`/odobrenja`): pending approvals list (`useApprovals`) with one-tap Odobri/Odbij/Odgodi (`useApprovalDecision`), the draft text + customer + evidence shown; sidebar item.
- **Functional notifications bell**: badge = pending approvals + pending KB clarifications + tasks due today (one cheap aggregate endpoint, e.g. `GET /inbox/summary`); dropdown links to /odobrenja, /zabiljeske, /zadaci. Badge on the Zabilješke nav item too.
- **Task → activity in one flow**: completing a task offers an inline "šta je urađeno?" (kind: poziv/sastanak/ponuda/…) that calls `useLogActivity`; feedback gets a visible toast instead of a bare ✓.
- **"Danas" preset** in DateRangePicker + due-today/overdue sort-filter on Zadaci.
- **Wire or remove quick actions**: "Novi zadatak" → task form; "Nova analiza" → investigation dialog (also adds an "Istraži" button on CustomerDetail — fixes discoverability).
- **Clickable cross-links**: customer-detail task/signal rows link to /zadaci and /ai-report; remove the wrong "Uskoro" badge on Prilike.
**Acceptance:** the owner approves a pending draft entirely in-app; the bell shows a real count that clears; closing a task can log an activity in the same dialog; a "Danas" view exists on Početna and Zadaci; no dead buttons remain.

```
Phase P1 per docs/IMPROVEMENT-ROADMAP.md. /spec p1-close-the-loop first, then Plan Mode.
Build the Odobrenja screen on the existing /approvals API with one-tap decisions; a real
notifications bell fed by a new GET /inbox/summary aggregate (approvals + pending
clarifications + tasks due today) with badges on the bell and Zabilješke; inline activity
logging on task completion via the existing useLogActivity; a "Danas" DateRangePicker preset
+ due-today/overdue filters on Zadaci; wire "Novi zadatak"/"Nova analiza" quick actions
(investigation dialog + Istraži button on CustomerDetail); make customer-detail task/signal
rows clickable; remove the stale "Uskoro" badge on Prilike. Bosnian-first i18n, register/
confidence/evidence discipline untouched. Tests: approvals round-trip in UI, badge counts
== SQL, task-completion logs an activity, Danas filters correct. Run principle-reviewer.
```

## P2 — Operational hardening: alerting, health, limits, backups

**Objective:** a pilot can run unattended without silent failure or runaway spend.
**Builds on:** M14 hardening, scanner/scheduler.
**Tasks:**
- **Job run ledger + alerting**: `app.job_run` (job, started, finished, status, error) written by every scheduled job; consecutive-failure threshold raises an owner-visible alert (notifications bell + optional e-mail later); "last successful scan" surfaced in Settings → Data and on `/health`.
- **Real health check**: `/api/health` probes DB, LiteLLM gateway, worker heartbeat (latest `job_run`), migration head.
- **Scanner freshness guard**: skip + alert when `core.invoice` has no rows in N days (threshold in `rule_config`) instead of silently scanning stale data.
- **Rate limiting**: per-user token bucket middleware (chat tighter than the rest; thresholds in config); login attempt throttle.
- **Auth hardening**: short-lived token + refresh, CSRF check on state-changing endpoints.
- **Backup verification**: weekly automatic restore test into a scratch schema + checksum log; runbook update (offsite copy instructions).
- **Chat capture latency**: run capture post-stream with a hard 5s cap, emitting the `capture` SSE event when ready (keeps the inline chip, removes blocking).
**Acceptance:** a deliberately failing scan shows up in the bell within one cycle; `/health` fails when LiteLLM is down; chat spam is throttled; the restore test passes on the seed dump; chat reply latency no longer includes capture.

```
Phase P2 per docs/IMPROVEMENT-ROADMAP.md. /spec p2-ops-hardening first, then Plan Mode.
Add app.job_run written by every scheduled job with consecutive-failure alerting into the
P1 inbox; extend /api/health to probe DB + LiteLLM + worker heartbeat + migration head; add
a scanner data-freshness guard (threshold in rule_config, alert not silence); per-user rate
limiting (chat strictest) + login throttle; token refresh + CSRF on mutations; a weekly
automated pg_dump restore-verification job; and make chat KB-capture non-blocking (post-
stream task, 5s cap, capture SSE event preserved). Tests: failing job → alert row; health
degrades correctly; freshness guard skips+alerts; rate limit 429s; restore test green.
Run principle-reviewer and /decision-audit.
```

## P3 — X1: LLM cost tracking, budgets & Batch API

**Objective:** see and control LLM spend before scaling usage (the plan's X1, now urgent).
**Builds on:** M6 gateway, M12 router, `docs/llm-cost.md` (the binding spec).
**Tasks:** extend `audit.ai_log` (feature, user_id, tier, input/output tokens, cached, batched, cost_usd); `app.llm_pricing` + `app.llm_budget` (seed from current Anthropic prices — never hard-code); per-call cost computed in the gateway; **"Troškovi AI" admin dashboard** (spend today/month vs budget, trend, by feature/model/user, cost-per-useful-task, recent expensive calls); 80% budget alert into the P1 inbox; per-feature daily caps + near-cap throttle of non-essential jobs; **move the weekly cycle (report sections, customer drafts, over-suppression audit) to the Batch API**; short-TTL answer cache for repeated identical questions.
**Acceptance:** per `llm-cost.md` — cost = tokens × price exactly; dashboard == `ai_log`; alert fires at 80%; the weekly-scan path measurably cheaper via Batch; masking untouchable.

```
Phase P3 per docs/IMPROVEMENT-ROADMAP.md = the X1 prompt in docs/IMPLEMENTATION-PLAN.md,
plus: route the weekly cycle through the Anthropic Batch API and add a short-TTL answer
cache for identical chat/dashboard questions. /spec x1-llm-cost first, then Plan Mode.
Tests per the X1 acceptance + "weekly cycle calls are batched=true in ai_log".
Run principle-reviewer.
```

## P4 — Daily Radar + Airtable bridge (the new business requirement)

**Objective:** every morning, a list — *koji kupac, koji problem/prilika, šta predlaže, kome dati zadatak* — with safe facts auto-synced to Airtable and business actions confirm-gated. The full design is already approved: **OB0–OB5** in the Operational-Bridge plan.
**Builds on:** scanner (daily 06:00), rule engine, signal→task, approvals/autonomy, P1 inbox, P3 cost guards.
**Tasks (summary — see the OB plan for detail):** OB0 spec + field mapping + AR export contract → OB1 AR/collections ingest (`staging.uplate`/`otvorene_stavke` → `core.payment`/`open_item` → SQL `core.customer_ar`) → OB2 rules (`debt_uncontacted`, `payment_settled`, `new_customer`, `offer_no_followup`) → OB3 Airtable connector (idempotent upsert by ERP code, `app.airtable_link`, every write a reversible decision; auto = dug/zadnja uplata/zadnja narudžba/“uplata evidentirana” aktivnost; confirm = zadatak/novi kupac/prioritet/obilazak) → OB4 `GET /radar/daily` + the Radar screen with one-tap confirms → OB5 backfill + runbook.
**Blocking inputs:** Bilans payments/open-items export format; Airtable base + PAT; explicit OK that real customer identity + debts go to Airtable (it is the chosen CRM; different posture than the masked LLM path).
**Acceptance:** per the OB plan — AR numbers to the cent; planted collection cases fire; nothing business-facing reaches Airtable without a confirm; every sync reversible + logged; the daily list renders by 06:30.

```
Phase P4 per docs/IMPROVEMENT-ROADMAP.md. Execute the Operational-Bridge plan OB0→OB5,
one OB per session, /spec first each time. Start with OB0 (field mapping + AR export
contract) — ask me for the Bilans export columns and the Airtable base/PAT before OB1.
Numbers from SQL; Airtable writes auto only for ERP-derived facts, confirm-gated for
business actions; every write a reversible app.decision. Run principle-reviewer,
tool-catalog-guardian (if a sync tool is exposed), /decision-audit per OB.
```

## P5 — DI1: bring the documents schema to life

**Objective:** the dead `0023` schema becomes the working pipeline of `docs/document-intelligence.md` §1–§6: upload → parse/OCR → classify → extract → resolve (§8 clarifications) → KB with document+page provenance → review UI.
**Builds on:** CI1 KB + clarification machinery (reused verbatim), migration `0023`, the worker.
**Tasks:** documents API router (upload/list/detail/file/reprocess) + on-prem file storage; born-digital parsing (PyMuPDF/pdfplumber, python-docx, openpyxl); scanned detection + OCR (Tesseract/OCRmyPDF, `bos`/`hrv`); Tier-1 classification + field-mapping (structured outputs, `ai_log.feature='doc_extraction'`); KB write-back behind the confirmation queue (scanned/high-stakes always confirm; ERP numbers never overwritten — discrepancies flagged); upload/library/detail/review UI.
**Acceptance:** per the DI1 prompt in `IMPLEMENTATION-PLAN.md` (born-digital invoice resolves to the right customer with page evidence; scan OCRs with diacritics and routes to confirm; re-upload deduped; ERP conflict flagged not written; ambiguous name → §8 clarification).

```
Phase P5 per docs/IMPROVEMENT-ROADMAP.md = the DI1 prompt in docs/IMPLEMENTATION-PLAN.md,
noting migration 0023 and documents/models.py already exist — build the pipeline, API,
worker processing and UI on top of them. /spec di1-documents-pipeline first, then Plan Mode.
Run principle-reviewer, selfconfig-reviewer, /decision-audit.
```

## P6 — DI2: retrieval (pgvector RAG) + grounded chat

**Objective:** the LLM can *read* documents as cited context.
**Tasks:** per the DI2 prompt — pgvector + `doc_chunk` + HNSW; local multilingual embeddings (bge-m3 / multilingual-e5, CPU); semantic search endpoint; read-only `search_documents` tool for chat + the investigation agent; cited passages in answers. Recall only — no facts/numbers in the index.

```
Phase P6 per docs/IMPROVEMENT-ROADMAP.md = the DI2 prompt in docs/IMPLEMENTATION-PLAN.md.
/spec di2-retrieval first, then Plan Mode. Run tool-catalog-guardian, principle-reviewer.
```

## P7 — Platform polish: language, mobile, transport, consistency

**Objective:** finish the cross-cutting promises.
**Tasks:**
- **X2 language enforcement**: "respond in {preferred_language}" in every prompt template; stored human-readable text follows it (per `architecture.md` §8) — the column/settings already exist.
- **Mobile**: sidebar → 5-item bottom tab bar ≤720px (per `ui-design.md`); responsive pass on the dense screens.
- **Customer-message transport**: implement the first real channel (e-mail via SMTP, or Viber later) strictly behind the existing approval gate; sent-status + delivery errors into the inbox.
- **Consistency sweep**: money shows cents (`formatMoney` 2 decimals), i18n the stragglers (bell aria-label, ✓/✗, emoji buttons→icons), context-aware empty states, learned-rules filter/search, "(samo admin)" labels on admin tabs, a help/shortcuts dialog.
- **Email ingestion** (.eml/.msg → DI pipeline) stays deferred until DI1/DI2 prove out.

```
Phase P7 per docs/IMPROVEMENT-ROADMAP.md. /spec p7-platform-polish first, then Plan Mode.
Implement X2 (the x2-language prompt in IMPLEMENTATION-PLAN.md), the ≤720px bottom-tab
mobile layout per ui-design.md, the first real customer-message transport behind the
existing approval gate (e-mail), and the consistency sweep (money cents, i18n stragglers,
contextual empty states, learned-rules filters, admin-tab labels, help dialog).
Tests per X2 acceptance + transport never sends without an approved approval row.
Run principle-reviewer.
```

---

## Sequencing & dependencies

```
P1 (UX loop) ──► P2 (ops; alerts feed P1 inbox) ──► P3 (cost; before scale-up)
                                                      │
                                  P4 Daily Radar/Airtable (needs P1 confirms, P3 guards,
                                                           + Bilans export & Airtable PAT)
P5 DI1 (independent; after CI1 ✓) ──► P6 DI2
P7 polish — anytime after P1, ideally last
```

**Recommended order: P1 → P2 → P3 → P4 → P5 → P6 → P7.** P4 is the highest *business* value but depends on external inputs (Bilans AR export, Airtable PAT) — start collecting those during P1–P3 so nothing blocks.
