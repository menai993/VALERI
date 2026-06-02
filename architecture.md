# VALERI — Architecture (`docs/architecture.md`)

On-prem AI business operating layer for an SME B2B distributor (pilot: Ultra Higijena, Sarajevo). MVP = **AI Sales Recovery** over read-only invoice/ERP data. This document is the technical map; it is binding together with `docs/principles.md`. Companion specs: `data-model.md`, `api-spec.md`, `frontend-spec.md`, `ui-design.md`.

## 1. Deployment topology (on-prem)

Everything runs on one server/VM inside the company, via Docker Compose. The only data that moves is a read-only export from the ERP into staging; the live ERP is never touched.

```
Docker Compose services:
  db       PostgreSQL 16            — business graph + app + audit + LangGraph checkpoints
  api      FastAPI (REST + SSE)     — application, RBAC, tool catalog, LLM gateway client
  worker   Python worker            — scheduled scans, async investigations (Postgres-backed jobs)
  web      React/TS (Vite build)    — the dashboard UI, served via the proxy
  litellm  LiteLLM gateway          — OpenAI-compatible surface; routes to Claude API tiers
  caddy    Caddy reverse proxy      — TLS, routes / → web, /api → api
```

Data posture: app + DB + all business data stay on the server. The LLM tiers are **hosted Claude via the Anthropic API**; only **masked, SQL-computed** payloads (pseudonyms + segment + finished numbers) leave the building. Request a **Zero-Data-Retention agreement** for the API key; commercial API data is not used for training. Backups via `pg_dump` cron; secrets via `.env`/Docker secrets.

## 2. Component map (backend packages → responsibility)

`apps/api/valeri_api/`
- `domain/` — SQLAlchemy models + Pydantic schemas for the business graph and app objects.
- `ingest/` — staging loaders (CSV/Excel/export), idempotent upsert to `core.*`, data-quality report.
- `metrics/` — deterministic SQL metrics (turnover, intervals, baselines); the only place numbers are produced.
- `semantic/` — metric registry (YAML: metric → SQL, entities, grain) + validated query builder used by tools and (later) NL→SQL.
- `rules/` — the rule engine and each detection rule; reads `app.rule_config` **and** active `app.learned_rule`.
- `scanner/` — scheduled scans (weekly/daily) that run rules and emit `app.signal`.
- `signals/` — signal → task pipeline (assignee, due, evidence, register).
- `tools/` — the **safe tool catalog**: typed, RBAC-checked, audited tools wrapping SQL/the semantic layer or guarded mutations. No tool returns a model-computed number.
- `conversation/` — chat sessions, intent router (Tier-1), tool dispatcher, SSE streaming.
- `selfconfig/` — feedback → structured rule change → graduated apply → `learned_rule` + reversible `decision`; the over-suppression auditor.
- `investigation/` — LangGraph agent (plan→act→critic→synthesize), Postgres checkpointer, loop/budget caps, HITL gates; async runner.
- `llm/` — gateway client, **PII masking**, prompt templates, Pydantic output schemas, `ai_log`; `llm/router/` for role-based + cascade routing and `llm_route_log`.
- `audit/` — append-only writers for `ai_log`, `task_log`, `decision`.
- `auth/` — users, sessions/JWT, RBAC (owner, sales_rep, finance, admin).
- `api/` — FastAPI routers (see `api-spec.md`).

## 3. Data flow

1. **Ingest → trust core:** export → `staging.*` → idempotent upsert → `core.*`; quality report flags dupes/renames/code-swaps.
2. **Metrics:** SQL recompute → `core.customer_metrics`, `cust_article_cadence`, `segment_basket`.
3. **Detect:** scanner runs rules over the graph (consulting `learned_rule`) → `app.signal` with evidence + confidence.
4. **Act:** signal → `app.task` (assignee, due, evidence); LLM narrates the Bosnian task text from finished numbers and tags the register; `ai_log`/`task_log` written.
5. **Report:** weekly owner report aggregates (SQL) + LLM narrative + register tags; customer-facing items become approval-gated drafts.
6. **Learn:** a dismissal + reason → Tier-1 structures a rule change → graduated apply → `learned_rule` + reversible `decision`; scanner suppresses matching future signals (`suppression_hit`); the auditor re-surfaces drifted suppressions.
7. **Converse:** chat message → intent router → tool calls (numbers from SQL) → register-tagged answer; "Istraži" → investigation.
8. **Investigate:** Tier-2 LangGraph agent decomposes → tool loop → critic → report (narrative + evidence + confidence + trace), async, HITL before any external draft.

## 4. LLM integration (the boundary the product depends on)

- **The LLM never computes a business number.** SQL/Python computes; the LLM interprets, narrates, classifies, drafts. Contract tests assert rendered numbers equal SQL output.
- **Tiers (hosted Claude via LiteLLM, OpenAI-compatible):** Tier-1 = Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for narration/intent/NL→rule/simple Q&A; Tier-2 = Claude Sonnet 4.6 (`claude-sonnet-4-6`) default, escalating to Claude Opus 4.8 (`claude-opus-4-8`) for the hardest investigations. Confirm models/limits at https://docs.claude.com.
- **Routing:** role-based assignment; optional cascade escalation on low self-confidence/validator-reject; `audit.llm_route_log` for every decision; keep ~60–70% on Haiku; prompt caching + Batch API for non-interactive jobs.
- **PII masking (load-bearing):** before any prompt, replace customer/contact identity with stable pseudonyms (+segment, +tier) and strip email/phone/address; the app rehydrates real names for humans only. No raw business identifier appears in any API payload.
- **Structured outputs:** every LLM response is parsed into a Pydantic model; malformed output is rejected and retried, never shown raw.

## 5. Security & privacy

Read-only ERP access; PII masking; ZDR; append-only audit (`ai_log`, `task_log`, `decision`); human approval for every customer-facing message; self-config auto-applies only if reversible and logged; RBAC on every endpoint and tool; secrets out of code; TLS at the proxy.

## 6. Engineering conventions

- Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, pytest, httpx, ruff+black. Typed everywhere; thresholds in DB, never literals; every config-changing path writes a reversible `decision`.
- Web: React 18 + TypeScript + Vite + Tailwind + shadcn/ui + TanStack Query + Zustand + Recharts + React Router (see `frontend-spec.md`). No `localStorage`.
- Tests: golden tests for metrics; labeled fixtures for rules; contract tests for tools (numbers == SQL) and LLM output schemas; HITL/loop-cap tests for the agent.
- Migrations via Alembic; one migration per schema-changing milestone.

## 7. Background (the "why")

Product rationale and competitive landscape live in `metarium-onprem-proposal.md` and `metarium-conversational-selfconfig-design.md` (product name "Metarium" in those = VALERI).
