# VALERI — Implementation plan & prompt pack (for Claude Code)

The iteration spine. Detail lives in the companion specs; this file gives the **order**, the **acceptance gates**, and a **paste-ready prompt per milestone**. Work the milestones in sequence, one per session.

## Document set (save in the repo)

- `CLAUDE.md` (repo root) — the contract Claude reads every session.
- `docs/IMPLEMENTATION-PLAN.md` — this file.
- `docs/architecture.md` — topology, components, data flow, LLM boundary, conventions.
- `docs/data-model.md` — full PostgreSQL schema (DDL), by milestone.
- `docs/api-spec.md` — REST + SSE endpoint surface.
- `docs/frontend-spec.md` — component inventory + screen build + build order.
- `docs/ui-design.md` — visual tokens + component anatomy (the dashboard direction).
- `docs/principles.md` — the 10 principles (P0 writes it from the section below).
- Background (the “why”): `metarium-onprem-proposal.md`, `metarium-conversational-selfconfig-design.md` (“Metarium” = VALERI).

## How to use

Create an empty folder, `git init`, save the files above. Open with Claude Code. For each milestone: paste the prompt → Claude writes the spec to `docs/specs/` → you approve → it plans (Plan Mode) → you approve → it implements with tests → a reviewer subagent checks the diff → `/clear` → next. Never batch milestones.

## Prerequisites

Claude Code, Docker + Docker Compose, Node 20+, Git, and an **`ANTHROPIC_API_KEY`**. No GPU/local model — all LLM tiers are Claude via the API. Request a **Zero-Data-Retention agreement** for the key.

## Global rules (also in CLAUDE.md)

Numbers come from SQL, never the LLM · spec-first → Plan Mode → TDD on trust-critical code → reviewer subagent → stop on divergence · evidence + confidence on every signal/task · register tag (Analiza/Preporuka/Akcija) on every AI output · append-only logs · PII masked before any LLM call · human approval for customer-facing messages · self-config auto-applies only if reversible and logged as a `decision` · thresholds in DB, never literals · build only what proves the current milestone.

-----

## Principles (P0 writes verbatim to `docs/principles.md`)

1. AI does not compute financial numbers — SQL/Python computes, the AI interprets.
1. Every AI task carries evidence from the database.
1. Every AI conclusion carries a confidence score.
1. No writes to the source ERP without explicit approval.
1. Read-only / export / staging access in phase one.
1. PII masking before AI processing.
1. AI log + task log + decision log are mandatory and append-only.
1. The feedback loop is a core function, not an add-on.
1. Distinguish analysis / recommendation / action; nothing happens silently.
1. Human approval for every external customer communication; self-configuration is an internal action and may auto-apply only if reversible and recorded as a visible decision.

-----

## Subagents (P0 creates in `.claude/agents/`)

- **principle-reviewer** — after any backend diff, check against `docs/principles.md`: any LLM-computed number; signal/task without evidence or confidence; write to a source system; non-read-only access; unmasked PII in a prompt; missing ai_log/task_log/decision write; output missing a register tag; customer-facing send without approval. Report PASS/FAIL with file:line.
- **tool-catalog-guardian** — after editing `tools/`: typed Pydantic in/out, RBAC check, tool_call_log write, data only from SQL/semantic layer, mutations write a reversible decision.
- **selfconfig-reviewer** — after editing `selfconfig/`: every config change → reversible decision; suppressions write suppression_hit; auto-vs-confirm boundary enforced; Undo restores; over-suppression auditor exists.
- **investigation-agent-builder** — for the LangGraph agent: plan→act(tool-loop)→critic→synthesize; loop + token/time caps; Postgres checkpointing; interrupt_before any external/config action; report has evidence+confidence+next step+trace; no model-computed numbers.

## Commands (P0 creates in `.claude/commands/`)

- `/spec <feature>` — write a spec to `docs/specs/<feature>.md` (scope, files, data-model touchpoints, tests, principles) then stop for review.
- `/tool <name>` — scaffold a safe tool (typed, RBAC, logged, SQL-only) + a contract test that its numbers equal SQL; then run tool-catalog-guardian.
- `/rule <name>` — scaffold a rule: spec in `docs/rules/`, thresholds in `rule_config`, fixtures (true positive / must-not-fire / low-confidence borderline); tests first.
- `/numbers-check` — run golden metric/tool tests; grep `llm/` and `conversation/` for arithmetic on business data.
- `/decision-audit` — verify every rule/config-changing path writes a reversible `decision`.

-----

# MILESTONES

Each: **Objective · Builds on · Tasks · Files · DB · API · Acceptance**, then the **prompt**.

## M0 — Foundation, infra, contract

**Objective:** a running skeleton. **Builds on:** —
**Tasks:** repo layout (`apps/api`, `apps/web`, `db`, `infra`, `docs`, `.claude`); `docs/principles.md` + the four spec docs already provided; subagents + commands; FastAPI `/health`; Vite/React/Tailwind/shadcn shell; SQLAlchemy+Alembic wired; pytest smoke test; CI.
**Files:** `infra/docker-compose.yml` (db, api, worker, web, litellm, caddy — **no local-model service**), `infra/.env.example` (incl. `ANTHROPIC_API_KEY`, model IDs), `infra/litellm.config.yaml` (tier1→haiku, tier2→sonnet, tier2_strong→opus via anthropic provider), `infra/Caddyfile`.
**Acceptance:** `docker compose up --build` serves `/api/health` and a blank web app; `pytest` passes; CI green.

```
Build VALERI per docs/IMPLEMENTATION-PLAN.md, docs/architecture.md and CLAUDE.md. This is M0.
/spec m0-foundation first; after I approve, use Plan Mode.
Deliver the repo layout, docs/principles.md (verbatim from the plan), the .claude/agents and .claude/commands exactly as specified, infra/docker-compose.yml (db, api, worker, web, litellm, caddy — no Ollama/vLLM), infra/.env.example (ANTHROPIC_API_KEY + model IDs claude-haiku-4-5-20251001 / claude-sonnet-4-6 / claude-opus-4-8), infra/litellm.config.yaml routing tier1/tier2/tier2_strong to those via the anthropic provider, a FastAPI app with GET /api/health, SQLAlchemy 2.x + Alembic against the db service, a Vite+React+TS+Tailwind+shadcn shell, pytest with a /health smoke test, and CI. Pin latest stable, commit lockfiles. Acceptance: docker compose up works; /api/health returns ok; pytest passes. Run principle-reviewer.
```

## M1 — Domain model + migrations + synthetic seed

**Objective:** the business graph + realistic test data. **Builds on:** M0
**Tasks:** implement all `core.*` graph tables (data-model.md, core section) as SQLAlchemy models + Alembic migration + Pydantic schemas; build `db/seed/` resembling Ultra Higijena (5 hotels with 2–3 objects under one legal_entity; segments hotel/restoran/kafić/klinika/škola; categories papir/hemija/dispenzeri/rukavice/kozmetika/tekstil/oprema; ~120 articles; ~80 customers; ~18 months invoices+lines with per-customer/article cadence; planted: 3 real declines, 2 seasonal cafés (must-not-flag later), 4 lost articles, 2 code-swaps, 3 narrow-basket, 3 sleeping).
**DB:** `core.legal_entity, customer, contact, sales_rep, customer_rep, category, article, article_alias, invoice, invoice_line`.
**Acceptance:** seed loads; a sampled customer enumerates legal entity, objects, 12-month invoices, assigned rep correctly (Capability A, no invented links).

```
M1. /spec m1-domain then Plan Mode. Implement the core.* tables exactly as in docs/data-model.md (core graph section) with SQLAlchemy 2.x + an Alembic migration + Pydantic schemas in domain/. Then build db/seed/ as described in the M1 section of the plan (hotels with multiple objects under one legal_entity, the listed segments/categories, ~18 months of invoices, and all planted cases). Write a test that enumerates a sampled customer's legal entity, objects, last-12-months invoices and rep with no invented relationships. Run principle-reviewer.
```

## M2 — Ingestion / staging / data-quality

**Objective:** read-only import path. **Builds on:** M1
**Tasks:** `ingest/` loads CSV/Excel into `staging.*`, idempotent upsert to `core.*`; data-quality report (dupe codes, renamed articles, code-swap candidates, missing segments, orphan lines); API trigger + report fetch; CLI path.
**API:** `POST /ingest/import`, `GET /ingest/report/{id}`.
**Acceptance:** importing the seed export twice is idempotent; totals preserved to the cent; the report detects planted code-swaps and a rename.

```
M2. /spec m2-ingest then Plan Mode. Build ingest/ per docs/architecture.md: CSV/Excel → staging → idempotent upsert to core; a data-quality report (dupes, renamed articles, code-swap candidates, missing segments, orphan lines); endpoints POST /api/ingest/import and GET /api/ingest/report/{id} per api-spec.md; plus a CLI. Tests: double-import idempotent, totals to the cent, report finds the planted code-swaps and a rename. Run principle-reviewer.
```

## M3 — Metrics & semantic layer (trust foundation)

**Objective:** deterministic numbers. **Builds on:** M2. **TDD: tests first.**
**Tasks:** `metrics/` SQL (window functions): turnover by customer/article/period, last_order_date, avg interval (customer & customer×article), 6-month baseline normalised to 60-day window, segment_basket prevalence; recompute job populating the derived tables. `semantic/`: YAML metric registry + validated query builder (used by tools + later NL→SQL). LLM not involved.
**DB:** `core.customer_metrics, cust_article_cadence, segment_basket`.
**Acceptance:** golden tests — every metric’s SQL output equals fixtures to the cent.

```
M3. /spec m3-metrics then Plan Mode. TDD. Build metrics/ (deterministic SQL with Postgres window functions) computing the metrics in docs/architecture.md §3 and populating core.customer_metrics, cust_article_cadence, segment_basket; and semantic/ (YAML metric registry + validated query builder). Write golden tests first using tests/fixtures/ so each metric equals expected values exactly. The LLM must not compute anything here. Run /numbers-check then principle-reviewer.
```

## M4 — Rule engine + scanner

**Objective:** detection. **Builds on:** M3
**Tasks:** per rule run `/rule <name>`: customer-decline (seasonal guard), lost-article (code-swap guard), lost-category, sleeping-customer, narrow-basket (recommendation). Thresholds in `app.rule_config`. Each emits `app.signal` with evidence (exact rows/dates/values) + confidence (0–1 + band). `scanner/` (APScheduler weekly+daily) runs rules; **must consult active `app.learned_rule`** and skip/soften matches (write the read/consult hook now; the writing of learned_rule is M10 — test with a hand-inserted rule).
**DB:** `app.rule_config, app.signal`.
**Acceptance:** each planted case fires; seasonal cafés do NOT fire; code-swap not flagged; a hand-inserted suppression learned_rule hides the right future signal.

```
M4. Build detection. For each of customer-decline, lost-article, lost-category, sleeping-customer, narrow-basket: run /rule <name> (spec in docs/rules/, thresholds in app.rule_config, fixtures true-positive / must-not-fire / low-confidence). Implement per docs/data-model.md (app.signal evidence/confidence shape) and docs/architecture.md. Build scanner/ (APScheduler weekly+daily) emitting signals, and add the hook that consults active app.learned_rule to suppress/soften matches. Tests: planted cases fire, seasonal cafés don't, code-swap not flagged, a hand-inserted learned_rule suppresses the right future signal. Run principle-reviewer.
```

## M5 — Signal → Task pipeline + feedback + task log

**Objective:** insight → assigned task. **Builds on:** M4
**Tasks:** `signals/` turns each confirmed signal into exactly one `app.task` (assignee = customer’s rep; owner_cc if top-10 by turnover; title/body/proposed_action/due_date/evidence/register); feedback capture (`task_feedback`); write every lifecycle event to `audit.task_log`.
**DB:** `app.task, app.task_feedback, audit.task_log`. **API:** `/tasks`, `/tasks/{id}`, `/tasks/{id}/status`, `/tasks/{id}/feedback`.
**Acceptance:** one task per signal with correct assignee; feedback persists; task_log records the lifecycle.

```
M5. /spec m5-tasks then Plan Mode. Build signals/ per docs/architecture.md and the task schema in data-model.md: signal → exactly one app.task (assignee = rep, owner_cc if top-10, evidence carried, register); task_feedback; audit.task_log for every lifecycle event; endpoints per api-spec.md. Tests: one task per signal with correct assignee, feedback persists, task_log complete. Run principle-reviewer.
```

## M6 — LLM gateway + PII masking + narration + register tagging

**Objective:** the language layer. **Builds on:** M5
**Tasks:** `llm/` OpenAI-compatible client → LiteLLM (default narration Tier-1 = Claude Haiku 4.5); **PII masking** (pseudonymise customer/contact identity, strip email/phone/address) before any prompt; Pydantic output schemas (narration, register, confidence) with reject+retry; prompt templates taking finished numbers. Use the LLM to write Bosnian task bodies, classify register, attach confidence; rehydrate names for humans; `audit.ai_log` per call.
**DB:** `audit.ai_log`.
**Acceptance (contract):** output validates against schema; rendered numbers equal SQL numbers; no raw PII in the prompt (assert on masked payload).

```
M6. /spec m6-llm then Plan Mode. Build llm/ per docs/architecture.md §4: LiteLLM client (narration on Tier-1 Claude Haiku 4.5), a PII masking step (pseudonyms + segment; strip email/phone/address) applied before every prompt, Pydantic output schemas with reject+retry, prompt templates that consume already-computed numbers. Use it to write Bosnian task bodies, classify Analiza/Preporuka/Akcija, and attach confidence; write audit.ai_log per call. Contract tests: schema valid, rendered numbers == SQL numbers, no raw PII in the payload. Run /numbers-check then principle-reviewer.
```

## M7 — Owner report + “Your decisions” + approval workflow

**Objective:** owner-facing weekly value. **Builds on:** M6
**Tasks:** scheduled weekly report (aggregate top declines, lost articles, top tasks + a “recently suppressed” placeholder filled in M11); numbers from SQL, LLM narrative, register-tagged; approval workflow (`app.approval`: draft→pending→approved/rejected) — internal actions (create task, send report) auto, customer-facing items are drafts.
**DB:** `app.approval`. **API:** `/reports/owner/weekly`, `/reports/owner/summary`, `/approvals`, `/approvals/{id}/decide`.
**Acceptance:** report aggregates match SQL; no customer-facing item can send without an approval row; internal actions auto-run.

```
M7. /spec m7-owner-report then Plan Mode. Build the weekly owner report (SQL aggregates + LLM narrative, register-tagged) and the summary block, plus the approval workflow (app.approval) per data-model.md/api-spec.md: internal actions auto, customer-facing items are approval-gated drafts. Tests: aggregates match SQL, nothing customer-facing sends without approval, internal actions auto-run. Run principle-reviewer.
```

## M8 — Web app: the dashboard + auth/RBAC

**Objective:** the owner command dashboard. **Builds on:** M7
**Tasks:** follow `docs/frontend-spec.md` build order and `docs/ui-design.md` tokens. Auth + RBAC (owner/sales_rep/finance/admin); Tailwind theme from tokens; primitives → widgets → shell → assemble **Početna** (KPI row, ComboChart+SubStatStrip, AI uvidi, Customers-at-risk + Lost-articles tables, Owner-report summary; rep-activity + opportunities as labeled Phase-2 placeholders) → Zadaci → Artikli (lost articles) → Kupci → AI Report tabs → Postavke. Every AI surface shows RegisterChip + ConfidenceLabel + EvidenceExpander; AIInsightItem dismiss opens the RuleCard (wired in M10). Light/dark + i18n (bs default).
**DB:** `app.app_user`. **API:** `/auth/*`, `/dashboard`, `/metrics/*`, `/customers/*`, `/articles/*`, `/tasks/*`, `/reports/owner/*`, `/settings/*`.
**Acceptance:** RBAC gating (a rep can’t load finance data); dashboard renders seeded data with skeleton/empty/error; register+confidence+evidence everywhere; light/dark correct; Bosnian throughout with EN toggle.

```
M8. /spec m8-web then Plan Mode. Build the frontend exactly per docs/frontend-spec.md (build order §7) and docs/ui-design.md (tokens, component anatomy), binding to docs/api-spec.md. Include auth + RBAC and the app.app_user table. Assemble the Početna dashboard to match the dashboard direction, with rep-activity and opportunities as labeled Phase-2 placeholders (use the MVP recovery tiles, not fake pipeline data). Wire the AIInsightItem dismiss to open the RuleCard (the apply call lands in M10). Acceptance per frontend-spec.md §8. Run principle-reviewer.
```

> **End of MVP (Sales Recovery).** Run the MVP acceptance tests (below) before the C-track.

## M9 — Safe tool catalog + intent router + chat (Ask VALERI)

**Objective:** conversation. **Builds on:** M8
**Tasks:** `tools/` via `/tool <name>` — query_metric, compare_periods, list_signals, explain_signal, get_customer_360, create_task_draft, propose_rule_change (stub), start_investigation (stub). `conversation/`: intent router (Tier-1) → question|feedback_config|investigation|action|help; tool dispatcher; SSE; session memory; register tag per reply. Chat screen per frontend-spec.
**DB:** `app.conversation, message, tool_call_log`. **API:** `/chat/*`.
**Acceptance:** a Bosnian question routes to query_metric/compare_periods and returns SQL-correct numbers tagged Analiza; a rep is RBAC-blocked from finance tools; every call in tool_call_log. Run tool-catalog-guardian + /numbers-check + principle-reviewer.

```
M9. /spec m9-chat then Plan Mode. Build tools/ (the safe catalog listed in api-spec.md/architecture.md) each via /tool; conversation/ (Tier-1 intent router, tool dispatcher, SSE, session memory, register tagging); and the Ask VALERI chat screen per frontend-spec.md. Numbers only from SQL via tools. Tests: Bosnian Q routes to metric tools and returns SQL numbers tagged Analiza, RBAC blocks finance tools from a rep, every call logged. Run tool-catalog-guardian, /numbers-check, principle-reviewer.
```

## M10 — Self-configuration loop (“ignore that” → reversible rule)

**Objective:** the learning loop. **Builds on:** M9
**Tasks:** `selfconfig/`: dismissal + reason → Tier-1 structures a rule change (`scope` JSONB, narrowest fit; description; predicted effect; interpretation confidence); graduated autonomy (low/medium-value suppression auto-applies reversibly; high-value scope requires confirm; customer-facing never auto — boundary in `rule_config`); on apply write `learned_rule` + reversible `decision` + return an inline confirmation; scanner (M4 hook) now consults learned_rule and writes `suppression_hit`; Undo reverts + writes a decision. Wire the Inbox/chat dismissal and the RuleCard.
**DB:** `app.learned_rule, decision, suppression_hit`. **API:** `/signals/{id}/dismiss`, `/rules/apply`, `/learned-rules*`, `/audit/decisions`.
**Acceptance:** a dismissal creates exactly one reversible decision + an active learned_rule; the scanner suppresses the right future signal and logs suppression_hit; vague+broad triggers confirm; Undo restores. Run selfconfig-reviewer + /decision-audit + principle-reviewer.

```
M10. /spec m10-selfconfig then Plan Mode. Build selfconfig/ per docs/architecture.md §3(6) and data-model.md (learned_rule/decision/suppression_hit, scope JSONB shape): dismissal+reason → structured rule change → graduated autonomy → learned_rule + reversible decision → scanner suppression + suppression_hit → Undo. Wire endpoints per api-spec.md and the RuleCard from frontend-spec.md. Tests: exactly one reversible decision + active rule per dismissal; correct future suppression; vague+broad requires confirm; Undo restores. Run selfconfig-reviewer, /decision-audit, principle-reviewer.
```

## M11 — “Šta je VALERI naučio” + over-suppression auditor

**Objective:** transparency + safety. **Builds on:** M10
**Tasks:** AI Report tab listing every learned_rule (origin, effect, status, Undo/Edit-scope) + the decision feed; an over-suppression auditor (scheduled) that re-examines suppressed streams and raises a `Na provjeri` decision when a suppressed pattern drifts (uses Tier-2; until M12 use Tier-1); expiry handling; fill the report’s “recently suppressed” line.
**API:** `/learned-rules*`, `/audit/decisions`.
**Acceptance:** the screen renders origin/effect; Undo works; the auditor re-surfaces a deliberately drifted suppressed stream; expired rules stop suppressing. Run selfconfig-reviewer + principle-reviewer.

```
M11. /spec m11-learned then Plan Mode. Build the "Šta je VALERI naučio" tab (LearnedRuleCard list + decision feed) per frontend-spec.md, the over-suppression auditor (scheduled; re-surfaces drifted suppressions as a Na provjeri decision), expiry handling, and the report's recently-suppressed line. Tests: render origin/effect, Undo works, auditor re-surfaces a drifted stream, expired rules stop suppressing. Run selfconfig-reviewer, principle-reviewer.
```

## M12 — Tiered LLM router (role-based + cascade)

**Objective:** cost-aware routing. **Builds on:** M11
**Tasks:** `llm/router/`: role-based assignment (narration/intent/NL→rule/simple-Q&A → Tier-1 Haiku; investigation/ambiguous/complex/over-suppression re-check → Tier-2 Sonnet default, escalate to Opus for hardest); optional cascade on low confidence/validator-reject; keep ~60–70% on Haiku; prompt caching + Batch API for non-interactive jobs; `audit.llm_route_log` for every decision; models in `litellm.config.yaml`/`.env`.
**DB:** `audit.llm_route_log`. **API:** `/settings/llm`.
**Acceptance:** each role maps to the right tier; cascade escalates on low confidence; every route logged; swapping Sonnet↔Opus is config-only and masking holds. Run principle-reviewer.

```
M12. /spec m12-router then Plan Mode. Build llm/router/ per docs/architecture.md §4: role-based tier assignment (Haiku vs Sonnet→Opus), optional cascade escalation, ~60-70% on Haiku, prompt caching + Batch API for non-interactive jobs, audit.llm_route_log, settings endpoint. Tests: roles map correctly, cascade escalates, routes logged, Sonnet↔Opus is config-only with masking intact. Run principle-reviewer.
```

## M13 — Investigation agent (LangGraph, async, HITL)

**Objective:** the “smarter LLM for hard tasks”. **Builds on:** M12
**Tasks:** `investigation/` LangGraph state machine on Tier-2: plan → act (tool loop, safe catalog only) → critic/validate → synthesize; hard loop + token/time caps; Postgres checkpointing (thread_id); `interrupt_before` any task/draft/config change (HITL); report = narrative (Bosnian) + findings + confidence + next step + full step trace; async via worker. Wire start_investigation (M9 stub) + an “Istraži” button + the Investigations UI.
**DB:** `app.investigation, investigation_step`. **API:** `/investigations*`.
**Acceptance:** loop cap enforced; HITL gate blocks an external draft until approval; no model-computed numbers; a run resumes from its checkpoint after a simulated restart. Run investigation-agent-builder + /numbers-check + principle-reviewer.

```
M13. /spec m13-investigation then Plan Mode. Build investigation/ as a LangGraph agent on Tier-2 per docs/architecture.md and data-model.md: plan→act(safe tools)→critic→synthesize, loop/token/time caps, Postgres checkpointing, interrupt_before any external/config action, report with evidence+confidence+next step+trace, async via the worker; wire start_investigation, an Istraži button, and the Investigations UI from frontend-spec.md. Tests: loop cap enforced, HITL blocks external drafts, numbers from SQL only, run resumes from checkpoint. Run investigation-agent-builder, /numbers-check, principle-reviewer.
```

## M14 — Hardening, backups, runbook, pilot

**Objective:** production-readiness. **Builds on:** M13
**Tasks:** pg_dump backup cron + restore; structured JSON logging; perf pass (scanner, metrics, dashboard); `docs/RUNBOOK.md` (deploy, upgrade, backup/restore, rotate secrets, switch Tier-2 model, tune thresholds); real-data import path doc + a “load real export + tune thresholds with labeled cases” checklist; run the full acceptance suite → `docs/ACCEPTANCE-REPORT.md`.
**Acceptance:** the full suite (below) passes. Run principle-reviewer + /decision-audit.

```
M14. /spec m14-hardening then Plan Mode. Deliver backups (pg_dump + restore), structured logging, a perf pass, docs/RUNBOOK.md, the real-data import + threshold-tuning checklist, then run the full acceptance suite and write docs/ACCEPTANCE-REPORT.md. Run principle-reviewer and /decision-audit.
```

-----

## Phase-2 CRM track (optional — only if the opportunity/pipeline product is approved)

Decide first (see Decision Defaults). If approved:

- **C-CRM1 — Opportunity model & pipeline:** add `app.opportunity`, `opportunity_stage_history`, `activity` (data-model.md Phase-2 section); CRUD endpoints; the Prilike screen (kanban + table + weighted value); replace the dashboard placeholders with real Otvorene prilike / Stopa konverzije / Najveće prilike. **Note:** introduces data entry — gate writes by RBAC; keep ERP read-only.
- **C-CRM2 — Rep activity & forecasting:** activity logging → “Aktivnosti komercijalista”; targets/plan → revenue-vs-plan and forecast; opportunity-source attribution and avg-opportunity-value in the owner report.

-----

## Acceptance suite

**MVP (after M8):** (1) numbers match the source export to the cent; (2) a sampled customer’s model is correct, no invented links; (3) lost-article detection correct and code-swaps not flagged; (4) decline-vs-seasonal hits the agreed accuracy with rule explanations; (5) the weekly scan surfaces relevant signals with no user query; (6) one task per signal with correct assignee; (7) 100% of customer-facing comms pass human approval (provable from task_log/approval); (8) over 4–6 weeks the share of rejected/“useless” tasks falls.
**Full (after M14), additionally:** (9) a Bosnian question returns SQL-correct numbers, register-tagged, every tool call logged; (10) a dismissal → one reversible decision + active learned rule, right future signal suppressed, Undo restores; (11) the auditor re-surfaces a drifted suppressed stream; (12) the investigation agent respects caps, blocks external drafts behind HITL, invents no numbers, resumes from checkpoint; (13) swapping the Tier-2 model is config-only with masking intact.
**The gate above all:** the team uses it voluntarily — reps open VALERI’s tasks to start the day; the owner stops opening the ERP for the operational picture.

## Decision defaults (change in Settings/config)

- **LLM tiers:** Tier-1 = Claude Haiku 4.5; Tier-2 = Claude Sonnet 4.6 default → Claude Opus 4.8 for hardest. Hosted via API, masked. Confirm models/pricing at <https://docs.claude.com>.
- **Data posture:** app+DB+data on-prem; only masked, SQL-computed payloads to the API; request ZDR; not used for training.
- **Auto-vs-confirm:** auto (reversible) for low/medium-value suppression; confirm for high-value scope; never-auto for customer-facing.
- **CRM scope:** default = keep pipeline widgets as labeled placeholders and ship MVP recovery-equivalents; enable the Phase-2 CRM track only if you want a managed opportunity pipeline + data entry.
- **Bosnian narration:** Haiku 4.5 narrates; spot-check in M6 and bump to Sonnet for richer phrasing if desired.

-----

## Client Intelligence track (conversational knowledge capture) — optional, after MVP + M9–M11

Users talk to VALERI and the LLM builds a structured, queryable knowledge base about customers (facts, deals/events, relationships) used for deeper analysis. Full spec: `docs/client-intelligence.md`. Depends on the conversation layer (M9) and self-config provenance (M10–M11).

### CI1 — Knowledge base & conversational capture

**Objective:** capture structured knowledge from what users say. **Builds on:** M9–M11
**Tasks:** add the `app` KB tables from `docs/client-intelligence.md` §2 (client_profile, client_fact, commercial_event, client_relationship, kb_extraction) with migrations; a relevance gate + extraction step (Tier-1, structured Pydantic output, reject+retry) run async on every chat message and on notes; **server-side entity resolution** (fuzzy + article_alias + context) to connect mentions to core.customer/article/rep; merge/dedup (supersede stale facts; maintain profile summary); graduated apply (auto-save low-stakes reversible; consequential/low-confidence → confirmation queue); provenance + confidence + evidence on every record; reuse `app.decision` (reversible) and `audit.ai_log`. Frontend: the “Šta VALERI zna” client-360 panel, the in-chat capture chip, and the review queue per §6.
**DB:** `app.client_profile, client_fact, commercial_event, client_relationship, kb_extraction`. **API:** `/kb/capture`, `/kb/notes`, `/kb/pending`, `/kb/items/{id}/confirm|reject`, PATCH `/kb/items/{id}`, `/customers/{id}/knowledge`.
**Acceptance:** a rep stating a deal creates a resolved commercial_event linked to the right customer, with the raw message as evidence + a confidence; a stated relationship (e.g. same_owner) lands in the confirmation queue (NOT auto-applied); a repeated fact supersedes rather than duplicates; every write is reversible and shown; no analysis number is computed by the LLM; personal PII is masked before the model. Run principle-reviewer + selfconfig-reviewer + /decision-audit.

```
Client Intelligence CI1. /spec ci1-knowledge first, then Plan Mode.
Build the conversational knowledge-capture module exactly per docs/client-intelligence.md: the KB tables (§2) with migrations; a relevance gate + Tier-1 extraction (structured Pydantic output, reject+retry) run async on every chat message and on POST /api/kb/notes; server-side entity resolution to connect mentions to core.customer/article/rep; merge/dedup with profile-summary maintenance; the entity-resolution & clarification policy from §8 (ranked candidates with similarity+confidence; when a match is ambiguous OR the fact is high-stakes, ask ONE short specific question — e.g. "da li ste mislili Fupy ili je to novi kupac?" — with tappable options instead of guessing; the app.customer_alias and app.clarification tables; non-blocking review queue; applies to ANY ambiguity, not just names — entity/reference/merge/value/conflict); graduated apply (auto-save low-stakes reversible, consequential/low-confidence to a confirmation queue); provenance + confidence + evidence on every record, reusing app.decision and audit.ai_log; endpoints per §5; and the frontend "Šta VALERI zna" panel, in-chat capture chip, and review queue per §6. Numbers for analysis stay in SQL; the LLM only extracts/narrates. Tests: a stated deal → a resolved commercial_event with raw-message evidence + confidence; a stated same_owner relationship → confirmation queue (not auto-applied); a repeated fact supersedes (no duplicate); a high-stakes fact about an ambiguous name (e.g. 'Fupupu' ~ Fupy) is NOT auto-attached — it raises a "da li ste mislili…/novi kupac?" clarification and stays proposed until answered, and confirming it writes a customer_alias; every write reversible and shown; personal PII masked before the model. Run principle-reviewer, selfconfig-reviewer, /decision-audit.
```

### CI2 — Graph-aware analysis & behavioral expectations

**Objective:** use the KB for deeper analysis. **Builds on:** CI1
**Tasks:** the relationship-map view per `docs/client-intelligence.md` §6; a per-client behavioral-expectation model (so deviations flag earlier); graph-aware rules (group/owner-level risk over confirmed edges, behavioral-twin early warning, referral-source risk); surface captured deals/events/facts in the weekly owner report; add a read-only, evidence-carrying `get_client_knowledge` tool to the safe catalog so the investigation agent can use the KB. Confirmed edges only; numbers from SQL; register + confidence + evidence on every AI line.
**API:** `/kb/graph`. **Acceptance:** a confirmed same_owner edge produces a group-level risk signal treating both objects together; a behavioral-twin early-warning fires on a planted case; the owner report includes captured events; the investigation agent can cite KB facts with evidence. Run principle-reviewer.

```
Client Intelligence CI2. /spec ci2-graph first, then Plan Mode.
Build graph-aware analysis per docs/client-intelligence.md §7: the relationship-map view; a per-client behavioral-expectation model; graph-aware rules (group/owner-level risk over confirmed edges, behavioral-twin early warning, referral-source risk); inclusion of captured deals/events/facts in the weekly owner report; and a read-only get_client_knowledge tool (via /tool) for the investigation agent. Use confirmed edges only; numbers from SQL; tag every AI line with register + confidence + evidence. Tests: a confirmed same_owner edge yields a group-level risk signal; a behavioral-twin early warning fires on a planted case; the owner report includes captured events; the agent can cite KB facts with evidence. Run tool-catalog-guardian, principle-reviewer.
```

-----

## Cross-cutting modules (cost & language)

### X1 — LLM usage, expense & optimization (build with/after M12)

**Objective:** see and control LLM spend. **Builds on:** M6 (gateway) + M12 (router). Spec: `docs/llm-cost.md`.
**Tasks:** extend `audit.ai_log` with feature/user/tier/input_tokens/output_tokens/cached/batched/cost_usd; add `app.llm_pricing` + `app.llm_budget`; compute per-call cost; the “Troškovi AI” admin dashboard (spend vs budget, trend, breakdown by feature/model/user, cost-per-useful-task, recent expensive calls); budget alerts + per-feature daily caps + near-cap throttle of non-essential jobs; the optimization levers (prompt caching of stable prefixes, Batch API for non-interactive jobs, tight output schemas + capped max_tokens, answer caching, gating). Seed pricing from current Anthropic figures (confirm at docs.claude.com).
**DB:** `audit.ai_log` (+cols), `app.llm_pricing`, `app.llm_budget`. **API:** `/admin/llm/usage`, `/admin/llm/recent`, `/admin/llm/budget`, `/admin/llm/pricing`.
**Acceptance:** per-call cost computed correctly from tokens × price; dashboard aggregates match `ai_log`; an 80% budget alert fires; prompt caching + Batch reduce measured cost on the weekly-scan path; disabling PII masking is NOT an allowed optimization. Run principle-reviewer.

```
X1. /spec x1-llm-cost first, then Plan Mode.
Build LLM usage/expense tracking and optimization exactly per docs/llm-cost.md: the ai_log cost columns + app.llm_pricing + app.llm_budget; per-call cost computation in the gateway; the "Troškovi AI" admin dashboard (spend vs budget, trend, breakdown by feature/model/user, cost-per-useful-task, recent expensive calls); budget alerts, per-feature daily caps, near-cap throttle; and the optimization levers (prompt caching of stable prefixes, Batch API for non-interactive jobs like the weekly report and over-suppression audits, tight output schemas + capped max_tokens, answer caching, gating). Seed app.llm_pricing from current Anthropic prices (I will confirm at docs.claude.com); never hard-code prices.
Tests: per-call cost = tokens × price; dashboard aggregates match ai_log; an 80% budget alert fires; caching/Batch reduce cost on the weekly-scan path; PII masking cannot be disabled as an "optimization". Run principle-reviewer.
```

### X2 — Language policy & preferred language (small; mostly already Bosnian)

**Objective:** make Bosnian the explicit, configurable default for LLM output and stored text. **Builds on:** M6 (and applies to all later text). Spec: `docs/architecture.md` §8.
**Tasks:** add `app_user.preferred_language` (default `'bs'`) + a system-default setting; enforce “respond in {preferred_language}” in every LLM prompt template; ensure stored human-readable text (task.body, report narrative, client_profile.summary, client_fact values, commercial_event.summary, learned_rule.description, clarification.question, investigation.report) is in the preferred language while enums/keys/columns stay English; UI defaults to `bs` with an EN toggle.
**API:** `/settings/language`. **Acceptance:** changing `preferred_language` changes LLM output and newly-stored summaries; identifiers/enums remain English; a non-Bosnian input still stores a Bosnian summary with the original utterance kept as evidence. Run principle-reviewer.

```
X2. /spec x2-language first, then Plan Mode.
Implement the language policy from docs/architecture.md §8: add app_user.preferred_language (default 'bs') and a system-default setting; enforce "respond in {preferred_language}" in every LLM prompt template; make all stored human-readable text (task.body, weekly-report narrative, client_profile.summary, client_fact values, commercial_event.summary, learned_rule.description, clarification.question, investigation.report) be written in the preferred language, while enums/keys/column names stay English; the UI defaults to Bosnian with an EN toggle.
Tests: changing preferred_language changes LLM output and newly-stored summaries; identifiers/enums remain English; a non-Bosnian input still stores a Bosnian summary with the original kept as evidence. Run principle-reviewer.
```

-----

## Document Intelligence track (import & understand documents) — after CI1

Import PDF/DOCX/XLSX incl. scanned paper, extract structured knowledge into the KB, and (DI2) make documents readable as LLM context. Full spec: `docs/document-intelligence.md`. Reuses the KB + clarification policy from `client-intelligence.md`; build after CI1. pgvector is the one new dependency (DI2).

### DI1 — Ingestion, OCR & extraction → KB

**Objective:** turn uploaded documents (incl. scans) into structured KB records. **Builds on:** CI1
**Tasks:** file storage (originals on‑prem) + the `document`/`document_page`/`document_extraction` tables; born‑digital parsing (PDF/DOCX/XLSX) and scanned‑paper OCR (Tesseract + OCRmyPDF with `bos`/`hrv` data, pdf2image/poppler), with scanned‑vs‑digital detection and an OCR confidence; classification (invoice/contract/price_list/…); deterministic table parsing then LLM field‑mapping (structured Pydantic output); resolution via `client-intelligence.md` §8; KB write‑back to `client_fact`/`commercial_event` with `source_document_id`+page provenance and the confirmation queue (high‑stakes/scanned → confirm); the upload screen, documents library, document detail (file viewer + per‑page text with a low‑trust badge for OCR + extracted records), and the extraction‑review queue. Processing runs async in the worker; `ai_log.feature='doc_extraction'`.
**DB:** `app.document, document_page, document_extraction`; +`source_document_id`/`source_page` on `client_fact`/`commercial_event`. **API:** `/documents/upload`, `/documents`, `/documents/{id}`, `/documents/{id}/file`, `/documents/{id}/reprocess` (+ reuse `/kb/pending|confirm`).
**Acceptance:** a born‑digital invoice imports and extracts customer+lines+total, resolved to the right `core` customer, with the document+page as evidence; a **scanned** invoice OCRs (Bosnian diacritics intact), is tagged lower‑trust, and its consequential extractions land in the confirmation queue (not auto‑applied); a re‑uploaded identical file is deduped by hash; an OCR’d total that disagrees with the ERP is **flagged, not written** over the ERP number; ambiguous customer names trigger the §8 clarification. Run principle-reviewer + selfconfig-reviewer + /decision-audit.

```
Document Intelligence DI1. /spec di1-documents first, then Plan Mode.
Build document ingestion exactly per docs/document-intelligence.md (§1–§6, §8–§9): on‑prem file storage + the document/document_page/document_extraction tables; born‑digital parsing (PyMuPDF/pdfplumber, python‑docx, openpyxl) and scanned‑paper OCR (Tesseract + OCRmyPDF with bos/hrv language data, pdf2image/poppler) with scanned‑vs‑digital detection and an OCR confidence; document classification; deterministic table parsing then LLM field‑mapping (structured Pydantic output, reject+retry); entity resolution + the clarification policy from client-intelligence.md §8; KB write‑back to client_fact/commercial_event with source_document_id+page provenance and the confirmation queue (scanned/high‑stakes → confirm); async processing in the worker with ai_log.feature='doc_extraction'; and the upload screen, documents library, document detail (file viewer + per‑page text with a low‑trust badge for OCR + extracted records) and the extraction‑review queue. Documents add context but NEVER override ERP numbers — flag discrepancies; numbers stay in SQL; the LLM extracts/reads only.
Tests: a born‑digital invoice → extracted customer+lines+total resolved to the right core customer with document+page evidence; a scanned invoice → OCR with Bosnian diacritics intact, tagged lower‑trust, consequential extractions in the confirmation queue (not auto‑applied); identical re‑upload deduped by hash; an OCR'd total disagreeing with the ERP is flagged not written; an ambiguous customer name triggers the §8 clarification. Run principle-reviewer, selfconfig-reviewer, /decision-audit.
```

### DI2 — Document retrieval (pgvector RAG)

**Objective:** let the LLM read document context. **Builds on:** DI1
**Tasks:** enable the pgvector extension; the `doc_chunk` table + an HNSW index; chunk+embed page text with a **local multilingual embedding model** (e.g. bge‑m3 / multilingual‑e5; or hosted embeddings under a data agreement — generative tiers stay hosted Claude); semantic passage search; a read‑only `search_documents` tool (via /tool) for the investigation agent; and cited passages (file/page) in chat and investigation reports. The vector index is for recall only — it holds no facts/numbers.
**API:** `/documents/search`. **Acceptance:** a semantic query returns the right passages with file/page citations; the investigation agent can pull and cite a document passage as context; no number is computed from retrieved text (figures still come from SQL); embedding dim matches the model. Run tool-catalog-guardian + principle-reviewer.

```
Document Intelligence DI2. /spec di2-retrieval first, then Plan Mode.
Build document retrieval per docs/document-intelligence.md §7: enable pgvector; add the doc_chunk table + HNSW index; chunk+embed page text with a local multilingual embedding model (bge‑m3 or multilingual‑e5, on CPU; or hosted embeddings under a data agreement — keep the generative tiers on hosted Claude); semantic passage search; a read‑only search_documents tool (via /tool) for the investigation agent; and cited passages (file/page) in chat and investigation reports. The vector index is for recall only and holds no facts/numbers; figures still come from SQL.
Tests: a semantic query returns the right passages with file/page citations; the investigation agent pulls and cites a document passage; no number is computed from retrieved text; embedding dimension matches the model. Run tool-catalog-guardian, principle-reviewer.
```