# VALERI — Project Contract (Claude reads this every session)

VALERI is an **on-prem AI business operating layer** for an SME B2B distributor (pilot: **Ultra Higijena**, Sarajevo). It reads company data read-only, understands it with built-in business definitions, proactively finds problems/opportunities, turns each finding into an assigned task **with evidence**, lets the owner **talk to the business in Bosnian**, **learns from feedback by writing its own reversible, logged rules**, and can **investigate** hard questions with a stronger model.

The MVP is **AI Sales Recovery** (customers, articles, invoices). **Build only what proves the MVP; defer everything else.** Full plan and prompt sequence: `@docs/IMPLEMENTATION-PLAN.md`.

## HARD RULES — MUST (a violation is a bug, not a style choice)

1. **The LLM never computes a business number.** All figures/aggregates/trends/scores come from SQL (PostgreSQL) or Python over the DB. The LLM only interprets, narrates, classifies, and drafts. Tests assert that rendered numbers equal SQL output.
1. **Every AI signal/task carries evidence from the DB** — the exact invoices/lines/dates/values it came from.
1. **Every AI conclusion carries a confidence score** (0–1 + band). Low confidence → a softer task (“verify…”) or no task.
1. **No writes to any external/source ERP system.** VALERI reads a copy/staging only.
1. **Phase-1 data access is read-only / export / staging.** Never modify live source data.
1. **PII is masked before any LLM call.** Customer/contact identity, email, phone, address → pseudonym + segment for the model; the app rehydrates real names for humans only.
1. **AI log + task log + decision log are mandatory and append-only.** Every LLM call, every task lifecycle event, every self-configuration is recorded.
1. **The feedback loop is core.** Outcome capture (useful / not / reason) and self-configuration ship from the start and change behaviour.
1. **Every user-facing output is tagged ANALYSIS / RECOMMENDATION / ACTION.** Actions also carry a status (draft / pending_approval / executed). The user must never be unsure whether something already happened.
1. **Human approval is required for every external/customer-facing communication** — such messages are drafts until approved. **Self-configuration is an INTERNAL action and may auto-apply, but only if it is reversible and recorded as a visible `app.decision`.**

## How the model touches data

The model **never** queries the DB freely. It calls **typed, validated, RBAC-checked, audited tools** from the tool catalog (`apps/api/valeri_api/tools/`). Each tool wraps deterministic SQL / the semantic layer or a guarded mutation. **No tool returns a number the model computed.**

## Stack (pin the latest stable at install; commit lockfiles)

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, pytest, httpx. SSE for streaming.
- **DB:** PostgreSQL 16.
- **LLM (hosted Claude via API — no local model/GPU):** all tiers are Anthropic API models, reached through a **LiteLLM** gateway (one place for routing, role assignment, retries, cost/usage logging). **Tier-1 (small/fast/cheap):** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) — narration, intent, NL→rule, simple Q&A. **Tier-2 (strong):** Claude Sonnet 4.6 (`claude-sonnet-4-6`) as the default for most chat and first-pass investigation, escalating to Claude Opus 4.8 (`claude-opus-4-8`) for the hardest cases. **LangGraph** for the investigation agent (Postgres checkpointer). Confirm models/pricing/limits at <https://docs.claude.com>.
- **Because every LLM call leaves the building, Rule 6 (PII masking) is load-bearing.** “On-prem” here means the app, the database, and ALL business data stay on your server; only **masked, SQL-computed** payloads (pseudonyms + segment + already-computed numbers) transit to the API. Request a **Zero-Data-Retention (ZDR) agreement** for the commercial API key so inputs/outputs aren’t stored at rest; commercial API data is not used for training. Docs: <https://platform.claude.com/docs/en/manage-claude/api-and-data-retention>
- **Frontend:** React + TypeScript + Vite + Tailwind + **shadcn/ui** + TanStack Query + Zustand + **Recharts**. The UI is a dense owner **command dashboard** — build to `docs/ui-design.md` (tokens/anatomy) and `docs/frontend-spec.md` (components/screens/build order).
- **Deploy:** Docker Compose. **Backups:** `pg_dump` cron. **Secrets:** `.env` / Docker secrets.

## Commands

- Run everything: `docker compose up --build`
- Backend tests: `cd apps/api && pytest`
- Migrations: `cd apps/api && alembic upgrade head`
- Web dev server: `cd apps/web && npm run dev`
- Lint/format: `ruff` + `black` (Python), `eslint` + `prettier` (web)

## Conventions

- Typed everywhere. **All LLM I/O goes through Pydantic models; malformed output is rejected and retried, never shown raw.**
- Thresholds live in `app.rule_config` / `app.learned_rule` — **never hard-coded**.
- No secrets in code. **No `localStorage`/`sessionStorage` in the web app** (use React state).
- **Every config-changing path writes an append-only `app.decision` and is reversible.**
- **Language:** Bosnian-first. A configurable `preferred_language` (default `'bs'`) sets the LLM’s output language AND the language of stored human-readable text (task bodies, report narrative, KB summaries/descriptions, clarification questions); enums, keys, identifiers, columns, and comments stay English. Every prompt template includes “respond in {preferred_language}”. See `docs/architecture.md` §8.
- **Cost:** LLM calls are billed per token — keep ~60–70% on Haiku, cache stable prompt prefixes, Batch non-interactive jobs, send finished numbers (not raw data) with tight output schemas; never disable masking to save tokens. See `docs/llm-cost.md`.

## Working rhythm (follow for every work-package)

1. **Spec-first** — write the spec to `docs/specs/<feature>.md` before coding; wait for my review.
1. **Plan Mode** — list the files to create/edit, the functions in each, and the order of operations; wait for approval. Do not write code before the plan is approved.
1. **TDD on trust-critical code** (metrics, rules, tools) — write the test/fixture first.
1. After implementing, ask the relevant reviewer subagent (`principle-reviewer`, `tool-catalog-guardian`, `selfconfig-reviewer`) to check the diff.
1. **If execution diverges from the approved plan, STOP and surface it before continuing.**
1. Keep context lean: one work-package per session, `/clear` between unrelated tasks, compact around 70%.

@docs/principles.md
@docs/architecture.md
@docs/data-model.md
@docs/api-spec.md
@docs/frontend-spec.md
@docs/ui-design.md
@docs/client-intelligence.md
@docs/document-intelligence.md
@docs/llm-cost.md
@docs/IMPLEMENTATION-PLAN.md