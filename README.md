# VALERI

**On-prem AI business operating layer** for SME B2B distributors (pilot: Ultra Higijena,
Sarajevo). VALERI reads company data read-only, finds problems/opportunities, turns each
finding into an assigned task with evidence, lets the owner talk to the business in Bosnian,
and learns from feedback through reversible, logged rules.

The MVP is **AI Sales Recovery** (customers, articles, invoices). The full plan lives in
[`docs/IMPLEMENTATION-PLAN.md`](docs/IMPLEMENTATION-PLAN.md); the project contract Claude
reads every session is [`CLAUDE.md`](CLAUDE.md).

## Repository layout

```
apps/api    FastAPI backend (Python 3.12, SQLAlchemy 2.x, Alembic) — managed with uv
apps/web    React + TypeScript + Vite + Tailwind + shadcn/ui dashboard
db          seed data (from M1)
docs        the contract documents, specs, and rules
infra       docker-compose.yml, .env.example, litellm.config.yaml, Caddyfile
.claude     Claude Code subagents and commands for the working rhythm
```

## Run everything (Docker Compose)

```bash
cd infra
cp .env.example .env          # fill in ANTHROPIC_API_KEY, passwords
docker compose up --build
```

Then open `http://localhost/` (web) — the API answers at `http://localhost/api/health`.

Services: `db` (PostgreSQL 16) · `api` (FastAPI) · `worker` · `web` · `litellm` (Claude
gateway) · `caddy` (reverse proxy, TLS-ready).

## Backend — test / migrate / lint

```bash
cd apps/api
uv sync                        # install deps from uv.lock (Python 3.12)
uv run pytest                  # tests
uv run alembic upgrade head    # migrations (needs DATABASE_URL or a local postgres)
uv run ruff check . && uv run black --check .   # lint/format
```

## Web — dev server / build / lint

```bash
cd apps/web
npm ci                         # install deps from package-lock.json
npm run dev                    # dev server (proxies /api to localhost:8000)
npm run build                  # production build
npm run lint                   # eslint
```

## Client distribution (IP protection)

Images delivered to clients contain **no readable backend source** — the `dist` Docker
target compiles all VALERI code to native binaries:

```bash
docker build --target dist -t valeri-api:dist apps/api
```

The dev/pilot stack (`infra/docker-compose.yml`) uses the normal `dev` target.

## LLM tiers

All tiers are hosted Claude models via the Anthropic API, routed through LiteLLM
(`infra/litellm.config.yaml`): **tier1** → Claude Haiku 4.5, **tier2** → Claude Sonnet 4.6,
**tier2_strong** → Claude Opus 4.8. Only masked, SQL-computed payloads ever reach the API
(see `docs/principles.md`). Request a Zero-Data-Retention agreement for the API key.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push/PR: backend lint
(ruff + black) and pytest against PostgreSQL 16, plus the web lint and production build.
