# Spec — M0: Foundation, infra, contract

**Milestone:** M0 · **Builds on:** — · **Status:** approved (D1 + D3 resolved by owner, 2026-06-02)

## 1. Objective

A running skeleton: the repo layout from the plan, the project contract documents in place,
the Claude Code subagents/commands, a Docker Compose stack (db, api, worker, web, litellm,
caddy), a FastAPI app with `GET /api/health`, SQLAlchemy 2.x + Alembic wired to PostgreSQL 16,
a Vite + React + TypeScript + Tailwind + shadcn/ui shell, a pytest smoke test, and CI.

**No business logic, no business tables, no LLM calls in M0.** Build only what proves the
skeleton runs; everything else is deferred to M1+.

## 2. Scope

### In scope
1. Repo layout: `apps/api`, `apps/web`, `db`, `infra`, `docs`, `.claude`.
2. Move the existing root-level spec documents into `docs/` (so the references in
   `CLAUDE.md` and the plan resolve).
3. `docs/principles.md` — the 10 principles, verbatim from the plan's Principles section.
4. `.claude/agents/` — `principle-reviewer`, `tool-catalog-guardian`, `selfconfig-reviewer`,
   `investigation-agent-builder`.
5. `.claude/commands/` — `spec`, `tool`, `rule`, `numbers-check`, `decision-audit`.
6. `infra/` — `docker-compose.yml`, `.env.example`, `litellm.config.yaml`, `Caddyfile`.
7. `apps/api` — FastAPI app, `GET /api/health`, SQLAlchemy 2.x + Alembic against the `db`
   service, Pydantic v2 settings, pytest smoke test, worker placeholder entrypoint.
8. `apps/web` — Vite + React + TypeScript + Tailwind + shadcn/ui shell (blank app, theme
   tokens stubbed, no screens).
9. Root `README.md` with run/test/migrate commands.
10. CI (GitHub Actions) running lint + pytest (+ web build).
11. Lockfiles committed (`uv.lock`, `package-lock.json`).

### Out of scope (deferred)
- Any `core.*` / `app.*` / `audit.*` business tables (M1+). M0's Alembic migration only
  creates the four empty Postgres **schemas** (`staging`, `core`, `app`, `audit`).
- The backend packages `domain/`, `ingest/`, `metrics/`, `semantic/`, `rules/`, `scanner/`,
  `signals/`, `tools/`, `conversation/`, `selfconfig/`, `investigation/`, `llm/`, `audit/`,
  `auth/` — created in their own milestones, **not** as empty stubs now.
- Any LLM call, masking code, or gateway client code (M6). M0 only stands up the LiteLLM
  **service** and its routing config.
- Auth/RBAC, dashboard screens, seed data.

## 3. Repo layout (deliverable)

```
/
├── CLAUDE.md                          (unchanged, stays at root)
├── README.md                          (new — run/test/migrate commands)
├── .gitignore                         (new — python, node, env, docker)
├── .github/
│   └── workflows/
│       └── ci.yml                     (new — lint + pytest + web build)
├── .claude/
│   ├── agents/
│   │   ├── principle-reviewer.md
│   │   ├── tool-catalog-guardian.md
│   │   ├── selfconfig-reviewer.md
│   │   └── investigation-agent-builder.md
│   └── commands/
│       ├── spec.md
│       ├── tool.md
│       ├── rule.md
│       ├── numbers-check.md
│       └── decision-audit.md
├── docs/
│   ├── IMPLEMENTATION-PLAN.md         (git mv from /VALERI-IMPLEMENTATION-PLAN.md)
│   ├── architecture.md                (git mv from /architecture.md)
│   ├── data-model.md                  (git mv from /data-model.md)
│   ├── api-spec.md                    (git mv from /api-spec.md)
│   ├── frontend-spec.md               (git mv from /frontend-spec.md)
│   ├── ui-design.md                   (git mv from /ui-design.md)
│   ├── principles.md                  (new — verbatim from the plan)
│   ├── rules/                         (empty, .gitkeep — used by /rule from M4)
│   └── specs/
│       └── m0-foundation.md           (this file)
├── apps/
│   ├── api/
│   │   ├── pyproject.toml             (uv project; deps pinned)
│   │   ├── uv.lock                    (committed lockfile)
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── migrations/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       └── 0001_create_schemas.py   (creates staging/core/app/audit schemas)
│   │   ├── valeri_api/
│   │   │   ├── __init__.py
│   │   │   ├── main.py                (FastAPI app factory + router mount)
│   │   │   ├── config.py              (pydantic-settings: DATABASE_URL, env)
│   │   │   ├── db.py                  (SQLAlchemy 2.x engine/session + Base)
│   │   │   ├── worker.py              (placeholder worker loop)
│   │   │   └── api/
│   │   │       ├── __init__.py
│   │   │       └── health.py          (GET /api/health)
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── conftest.py
│   │       └── test_health.py         (smoke test)
│   └── web/
│       ├── package.json
│       ├── package-lock.json          (committed lockfile)
│       ├── Dockerfile                 (multi-stage: node build → nginx static)
│       ├── nginx.conf
│       ├── index.html
│       ├── vite.config.ts
│       ├── tsconfig.json / tsconfig.app.json / tsconfig.node.json
│       ├── components.json            (shadcn/ui config)
│       ├── eslint.config.js
│       └── src/
│           ├── main.tsx
│           ├── App.tsx                (blank shell: "VALERI" placeholder page)
│           ├── index.css              (Tailwind + token CSS variables stub)
│           ├── components/ui/         (shadcn primitives: button, card — proves setup)
│           └── lib/utils.ts           (shadcn cn() helper)
├── db/
│   └── .gitkeep                       (seed data lands here in M1)
└── infra/
    ├── docker-compose.yml
    ├── .env.example
    ├── litellm.config.yaml
    └── Caddyfile
```

## 4. Key decisions (flagged for review)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Move root docs into `docs/`** (`git mv`, with `VALERI-IMPLEMENTATION-PLAN.md` → `docs/IMPLEMENTATION-PLAN.md`) — **RESOLVED: approved** | `CLAUDE.md` and the plan reference `docs/...` paths; the files currently sit at the repo root, so those references are broken. |
| D2 | **Python deps managed with `uv`** (`pyproject.toml` + `uv.lock`) | CLAUDE.md requires committed lockfiles; uv is the current standard, fast in CI and Docker. |
| D3 | **React 19 + Tailwind v4 + Vite 7** (latest stable) — **RESOLVED: approved (best long-run choice)** | CLAUDE.md: "pin the latest stable at install." `frontend-spec.md` mentions React 18 / `tailwind.config.ts` (written pre-React-19/Tailwind-4). Tokens map to Tailwind v4's CSS-first `@theme` instead of `tailwind.config.ts` — same semantic-token outcome. React 18/Tailwind 3 are maintenance-only; starting on them would force a mid-project migration. |
| D4 | **DB driver: `psycopg` (v3, binary)** | Modern pairing with SQLAlchemy 2.x; `DATABASE_URL=postgresql+psycopg://...`. |
| D5 | **Worker = same image as api, different command** (`python -m valeri_api.worker`) | Architecture defines worker as a Python worker over the same DB; sharing the image avoids a second Python project. M0 placeholder logs a heartbeat and sleeps; APScheduler lands in M4. |
| D6 | **M0 Alembic migration creates only the 4 schemas** (`staging`, `core`, `app`, `audit`) | Proves migrations run end-to-end against the db service without front-running M1's tables ("one migration per schema-changing milestone"). |
| D7 | **Web container: multi-stage build → nginx:alpine static serve; Caddy proxies `/` → web, `/api` → api** | architecture.md: "web React/TS (Vite build) — served via the proxy". |
| D8 | **`/api/health` reports app + db status** | Proves SQLAlchemy wiring, not just FastAPI. Returns 200 `{"status":"ok","db":"ok"}`; if DB unreachable, still 200 with `"db":"unavailable"` (the service is up; the dependency isn't). |
| D9 | **CI uses a `postgres:16` service container** | So pytest + `alembic upgrade head` run against a real PostgreSQL 16, same as compose. |

## 5. Component specs

### 5.1 `docs/principles.md` (verbatim from the plan)

Exact content (heading + the 10 numbered principles, word-for-word from
`docs/IMPLEMENTATION-PLAN.md` § "Principles"):

1. AI does not compute financial numbers — SQL/Python computes, the AI interprets.
2. Every AI task carries evidence from the database.
3. Every AI conclusion carries a confidence score.
4. No writes to the source ERP without explicit approval.
5. Read-only / export / staging access in phase one.
6. PII masking before AI processing.
7. AI log + task log + decision log are mandatory and append-only.
8. The feedback loop is a core function, not an add-on.
9. Distinguish analysis / recommendation / action; nothing happens silently.
10. Human approval for every external customer communication; self-configuration is an
    internal action and may auto-apply only if reversible and recorded as a visible decision.

### 5.2 `.claude/agents/` (four subagents)

Each is a Markdown agent definition (YAML frontmatter: `name`, `description`, `tools`;
body = the reviewer's system prompt). Checks are exactly the ones the plan specifies:

- **principle-reviewer** — run after any backend diff. Checks against `docs/principles.md`:
  any LLM-computed number; signal/task without evidence or confidence; write to a source
  system; non-read-only access; unmasked PII in a prompt; missing ai_log/task_log/decision
  write; output missing a register tag; customer-facing send without approval.
  Reports **PASS/FAIL with file:line**.
- **tool-catalog-guardian** — run after editing `tools/`: typed Pydantic in/out; RBAC check;
  `tool_call_log` write; data only from SQL/semantic layer; mutations write a reversible
  decision.
- **selfconfig-reviewer** — run after editing `selfconfig/`: every config change → reversible
  decision; suppressions write `suppression_hit`; auto-vs-confirm boundary enforced; Undo
  restores; over-suppression auditor exists.
- **investigation-agent-builder** — for the LangGraph agent: plan→act(tool-loop)→critic→
  synthesize; loop + token/time caps; Postgres checkpointing; `interrupt_before` any
  external/config action; report has evidence+confidence+next step+trace; no model-computed
  numbers.

### 5.3 `.claude/commands/` (five commands)

Markdown command definitions (frontmatter: `description`, `argument-hint`; body = prompt):

- **/spec `<feature>`** — write a spec to `docs/specs/<feature>.md` (scope, files, data-model
  touchpoints, tests, principles), then stop for review.
- **/tool `<name>`** — scaffold a safe tool (typed, RBAC, logged, SQL-only) + a contract test
  that its numbers equal SQL; then run tool-catalog-guardian.
- **/rule `<name>`** — scaffold a rule: spec in `docs/rules/`, thresholds in `rule_config`,
  fixtures (true positive / must-not-fire / low-confidence borderline); tests first.
- **/numbers-check** — run golden metric/tool tests; grep `llm/` and `conversation/` for
  arithmetic on business data.
- **/decision-audit** — verify every rule/config-changing path writes a reversible `decision`.

### 5.4 `infra/docker-compose.yml`

Six services, no Ollama/vLLM:

| Service | Image / build | Notes |
|---|---|---|
| `db` | `postgres:16` | env from `.env`; named volume `pgdata`; healthcheck `pg_isready`. |
| `api` | build `apps/api` | runs `uvicorn valeri_api.main:app --host 0.0.0.0 --port 8000`; `depends_on: db (healthy)`; runs `alembic upgrade head` on start (entrypoint). |
| `worker` | same build as `api` | command `python -m valeri_api.worker`; `depends_on: db (healthy)`. Placeholder. |
| `web` | build `apps/web` | multi-stage: node build → nginx serving `dist/` on port 80. |
| `litellm` | `ghcr.io/berriai/litellm` (pinned stable tag) | mounts `infra/litellm.config.yaml`; `ANTHROPIC_API_KEY` from env; port 4000 (internal only). |
| `caddy` | `caddy:2` | mounts `infra/Caddyfile`; ports 80/443; routes `/api/*` → `api:8000`, everything else → `web:80`. TLS-ready (internal/self-signed by default, real certs configurable). |

Compose reads `infra/.env` (`env_file` + variable interpolation). Internal Docker network;
only caddy publishes ports.

### 5.5 `infra/.env.example`

```dotenv
# ── Anthropic API (hosted Claude; request ZDR for this key) ──
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME

# ── Model IDs per tier (also referenced by infra/litellm.config.yaml) ──
LLM_TIER1_MODEL=claude-haiku-4-5-20251001
LLM_TIER2_MODEL=claude-sonnet-4-6
LLM_TIER2_STRONG_MODEL=claude-opus-4-8

# ── LiteLLM gateway ──
LITELLM_MASTER_KEY=REPLACE_ME
LITELLM_BASE_URL=http://litellm:4000

# ── PostgreSQL ──
POSTGRES_USER=valeri
POSTGRES_PASSWORD=REPLACE_ME
POSTGRES_DB=valeri
DATABASE_URL=postgresql+psycopg://valeri:REPLACE_ME@db:5432/valeri

# ── App ──
APP_ENV=development
```

### 5.6 `infra/litellm.config.yaml`

Routes the three tiers to Anthropic models, key from env:

```yaml
model_list:
  - model_name: tier1          # narration, intent, NL→rule, simple Q&A
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: tier2          # default chat + first-pass investigation
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: tier2_strong   # hardest investigations
    litellm_params:
      model: anthropic/claude-opus-4-8
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  drop_params: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

### 5.7 `infra/Caddyfile`

- `:80` (and TLS-ready `:443` with internal certs by default).
- `handle /api/*` → `reverse_proxy api:8000`.
- `handle` (fallback) → `reverse_proxy web:80`.

### 5.8 `apps/api`

- **`pyproject.toml`** (uv): `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `alembic`,
  `psycopg[binary]`, `pydantic>=2`, `pydantic-settings`. Dev: `pytest`, `httpx`, `ruff`,
  `black`. All pinned to the latest stable resolved at install; `uv.lock` committed.
- **`config.py`** — `Settings(BaseSettings)`: `database_url`, `app_env`. Read from env
  (no secrets in code).
- **`db.py`** — SQLAlchemy 2.x `create_engine`, `sessionmaker`, `DeclarativeBase` subclass
  (`Base`). No models yet.
- **`main.py`** — FastAPI app, title "VALERI API", mounts the health router under `/api`.
- **`api/health.py`** — `GET /api/health` → `{"status": "ok", "db": "ok" | "unavailable"}`
  (db status = `SELECT 1` via the engine, exceptions caught).
- **`worker.py`** — placeholder loop: log "VALERI worker idle (scheduler lands in M4)" every
  60 s. Clean shutdown on SIGTERM.
- **Alembic** — `migrations/env.py` wired to `Settings().database_url` and `Base.metadata`;
  version `0001_create_schemas` runs `CREATE SCHEMA IF NOT EXISTS staging/core/app/audit`
  (downgrade drops them).
- **`Dockerfile`** — `python:3.12-slim`, uv install, non-root user; entrypoint runs
  `alembic upgrade head` then `uvicorn`.

### 5.9 `apps/web`

- Vite + React + TypeScript scaffold; Tailwind; shadcn/ui initialised (`components.json`,
  `lib/utils.ts`, Button + Card primitives generated to prove the toolchain).
- `index.css`: Tailwind entry + the CSS-variable token names from `ui-design.md` §3 declared
  on `:root` / `.dark` (values copied; full theme work is M8).
- `App.tsx`: a minimal placeholder page ("VALERI — sistem je pokrenut") rendered with the
  shadcn Card — enough to verify the toolchain and the served bundle through Caddy.
- No router, no state libs, no screens (M8). No `localStorage`.
- `package-lock.json` committed.

### 5.10 Root `README.md`

Project one-liner + the commands from CLAUDE.md:

- Run everything: `docker compose --env-file infra/.env -f infra/docker-compose.yml up --build`
  (plus the `cp infra/.env.example infra/.env` first-run step)
- Backend tests: `cd apps/api && pytest`
- Migrations: `cd apps/api && alembic upgrade head`
- Web dev server: `cd apps/web && npm run dev`
- Lint/format: `ruff` + `black` (Python), `eslint` + `prettier` (web)
- Repo map + pointer to `docs/` and `CLAUDE.md`.

### 5.11 CI — `.github/workflows/ci.yml`

On push/PR:

- **api job:** Python 3.12 + uv → `ruff check` → `black --check` → `alembic upgrade head`
  (against a `postgres:16` service container) → `pytest`.
- **web job:** Node LTS → `npm ci` → `eslint` → `npm run build`.

## 6. Data-model touchpoints

M0 creates **no tables**. One Alembic migration creates the four empty schemas
(`staging`, `core`, `app`, `audit`) so that M1's migration has a home and
`alembic upgrade head` is meaningful. Money/enums/business DDL: untouched until M1.

## 7. Tests (pytest, written before the endpoint)

`apps/api/tests/test_health.py`:

1. `test_health_returns_ok` — `GET /api/health` → 200, `{"status": "ok", ...}`.
2. `test_health_reports_db_status` — with the test DB reachable → `"db": "ok"`.
3. `test_health_degrades_gracefully_without_db` — with an unreachable `DATABASE_URL` →
   still 200, `"db": "unavailable"` (the API never 500s on a down dependency).

CI runs these against a real `postgres:16` service. Test client: `httpx` + FastAPI
`ASGITransport` (no running server needed).

## 8. Acceptance criteria

1. `docker compose up --build` (from `infra/`) brings up **db, api, worker, web, litellm,
   caddy**; all reach healthy/running state.
2. `GET /api/health` (via Caddy and directly) returns `{"status":"ok","db":"ok"}`.
3. The web shell loads at `/` through Caddy.
4. `cd apps/api && pytest` passes locally and in CI.
5. `alembic upgrade head` runs cleanly against the db service; the four schemas exist.
6. CI is green (lint + tests + web build).
7. Lockfiles (`uv.lock`, `package-lock.json`) are committed.
8. After implementation, the diff is reviewed against `docs/principles.md`
   (principle-reviewer) and violations reported.

## 9. Principles compliance (how M0 honors them)

| Principle | M0 impact |
|---|---|
| 1. No LLM-computed numbers | No LLM calls exist in M0; the LiteLLM service is config-only. |
| 2. Evidence on every signal/task | No signals/tasks yet; schemas reserved. |
| 3. Confidence on every conclusion | N/A in M0 (no AI conclusions). |
| 4./5. No ERP writes; read-only posture | M0 touches no source system; DB is the app's own staging/core. |
| 6. PII masking before LLM | No LLM calls; masking lands in M6. `ANTHROPIC_API_KEY` only in env, never code. |
| 7. Append-only logs | `audit` schema created (empty) — the structural home for ai_log/task_log/decision. |
| 8. Feedback loop | Not in M0 scope. |
| 9. Register tags | Not in M0 scope (no AI output). |
| 10. Approval gates | Not in M0 scope. |
| Conventions: secrets out of code; thresholds in DB; no localStorage | `.env.example` placeholders only; no thresholds exist yet; web shell uses no storage APIs. |

## 10. Open questions — resolved at review (2026-06-02)

1. **D3 (React 19 / Tailwind v4)** — ✅ approved: latest stable (best long-run choice).
2. **Doc move (D1)** — ✅ approved: move the six root docs into `docs/`.
3. `.env.example` contents — no changes requested; spec stands as written.
