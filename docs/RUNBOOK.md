# VALERI — Operations Runbook

How to run, upgrade, back up, and tune VALERI on the on-prem server. Audience: the
person operating the deployment (not necessarily the person who built it). Every
procedure here is copy-pasteable.

All commands run from `infra/` unless noted. The stack is Docker Compose; the only
published ports are Caddy's (80/443). See `docs/architecture.md` §1 for the topology.

---

## 0. Services at a glance

| Service | What it does | Restart-safe? |
|---|---|---|
| `db` | PostgreSQL 16 — business graph + app + audit + LangGraph checkpoints | yes (named volume `pgdata`) |
| `api` | FastAPI — REST + SSE; runs migrations on start | yes |
| `worker` | Scheduled jobs: daily/weekly scans, weekly over-suppression audit, investigation poll | yes |
| `web` | React build, served via Caddy | yes |
| `litellm` | LiteLLM gateway → Claude tiers (Anthropic API) | yes |
| `caddy` | TLS + reverse proxy (`/` → web, `/api` → api) | yes |
| `backup` | Daily `pg_dump` into the `pg_backups` volume | yes |

Logs are **structured JSON, one object per line** on each container's stdout:
`docker compose logs -f api` / `worker`. Fields: `ts, level, logger, message` plus
any call-specific extras. No request bodies or PII are ever logged.

---

## 1. First deploy

```sh
cd infra
cp .env.example .env          # then edit .env — see "Secrets" below
docker compose up --build -d
docker compose ps             # all services healthy
curl -k https://localhost/api/health   # {"status":"ok"}
```

The `api` container runs `alembic upgrade head` on start, so the schema is created
automatically. To load data, see **§7 Real-data import** (or `db/seed` for a demo).

### Secrets (set in `.env` before first deploy)

| Variable | What | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key | **Request a Zero-Data-Retention agreement for this key.** |
| `LITELLM_MASTER_KEY` | gateway auth | any long random string |
| `POSTGRES_PASSWORD` | DB password | strong, unique |
| `PII_SALT` | pseudonym salt | **load-bearing — see §5 before rotating** |
| `AUTH_SECRET` | JWT signing key | ≥ 32 bytes |
| `LLM_TIER1/2/2_STRONG_MODEL` | tier → Claude model | see §6 |
| `BACKUP_HOUR`, `BACKUP_RETENTION_DAYS` | backup schedule/retention | defaults 02:00, 14 days |

Generate a random secret: `openssl rand -hex 32`.

---

## 2. Upgrade (new version)

```sh
cd infra
docker compose pull            # if using prebuilt images; else skip
git pull                       # new code
docker compose up --build -d   # rebuild changed services
# Migrations run automatically when the api container starts. Confirm:
docker compose logs api | grep -i "alembic"
```

Always **back up first** (§3). Migrations are forward-only in normal operation; a
bad upgrade is recovered by restoring the pre-upgrade dump (§4) and redeploying the
previous version.

To check the current migration:
```sh
docker compose exec api alembic current
```

---

## 3. Backup

A daily dump runs automatically (the `backup` service, at `BACKUP_HOUR`). Dumps
live in the `pg_backups` volume as `valeri_<db>_<timestamp>.dump` (pg_dump custom
format), pruned after `BACKUP_RETENTION_DAYS`.

**Run a backup now:**
```sh
docker compose exec backup sh /scripts/backup.sh
```

**List dumps:**
```sh
docker compose exec backup ls -lh /backups
```

**Copy a dump off-host (do this regularly — a backup on the same machine does not
survive that machine):**
```sh
# from the host:
docker compose cp backup:/backups/valeri_valeri_20260603_020000.dump ./
# then ship ./valeri_*.dump to off-site storage (rsync/scp/object store)
```

---

## 4. Restore

Restore is **destructive** (it drops existing objects first), so the script
requires an explicit `--yes`.

**Restore the production DB from a dump:**
```sh
# 1. stop the app + worker so nothing writes mid-restore
docker compose stop api worker
# 2. restore (the dump path is inside the backup container)
docker compose exec backup sh /scripts/restore.sh /backups/valeri_valeri_<ts>.dump --yes
# 3. bring the app back
docker compose start api worker
curl -k https://localhost/api/health
```

**Verify a backup without touching production** (restore into a scratch DB):
```sh
docker compose exec db createdb -U "$POSTGRES_USER" valeri_verify
docker compose exec -e TARGET_DB=valeri_verify backup \
  sh /scripts/restore.sh /backups/valeri_valeri_<ts>.dump --yes
# restore.sh prints per-table row counts; compare to production, then drop:
docker compose exec db dropdb -U "$POSTGRES_USER" valeri_verify
```

The backup/restore round-trip is covered by an automated test
(`tests/test_hardening.py::test_backup_restore_roundtrip`).

---

## 5. Rotate secrets

Edit `.env`, then `docker compose up -d <service>` to apply (most secrets are read
at process start). General order: rotate at the source (e.g. issue a new API key),
update `.env`, recreate the affected service.

| Secret | Procedure | Caveat |
|---|---|---|
| `ANTHROPIC_API_KEY` | new key in `.env` → `docker compose up -d litellm` | none |
| `LITELLM_MASTER_KEY` | new value → `up -d litellm api worker` (both sides must match) | brief in-flight call failures → template fallbacks |
| `AUTH_SECRET` | new value → `up -d api` | **all sessions invalidated — users re-login** |
| `POSTGRES_PASSWORD` | change in DB + `.env` → `up -d` | coordinate; DB password change is a DB-admin step |
| **`PII_SALT`** | new value → `up -d api worker` | **see below — read before rotating** |

**`PII_SALT` rotation caveat.** The salt makes pseudonyms stable across calls
(`Kupac-xxxxxx` for a given customer). Rotating it:
- does **not** weaken masking — masking still happens on every call (Principle 6 holds);
- **does** change every customer's pseudonym, so prompt-cache prefixes and any
  cross-call pseudonym correlation reset. Stored data is unaffected (the app stores
  real names + ids; pseudonyms are derived on the fly). Rotate only if the salt may
  be compromised; expect a one-time cache-miss cost afterwards.

---

## 6. Switch the Tier-2 model (Sonnet ↔ Opus, or any tier's model)

The app addresses models by **tier alias** (`tier1`/`tier2`/`tier2_strong`); the
alias → Claude-model mapping is config. Two independent levers:

**A. Change which Claude model a tier maps to** (e.g. make Tier-2 use Opus):
```sh
# infra/.env
LLM_TIER2_MODEL=anthropic/claude-opus-4-8
# apply:
docker compose up -d litellm
```
No code change, no app restart needed — only the gateway re-reads the mapping.

**B. Change which tier a task role uses** (e.g. send the audit to the strong tier),
in the UI: **Postavke → AI model → Routing**, pick the tier per role. Each change
is admin-only and written as a reversible `app.decision`. (API: `PATCH
/api/settings/llm`.)

Masking is shown locked-on in that screen and **cannot be disabled** through the
API (Principle 6). Confirm models/pricing at <https://docs.claude.com>.

---

## 7. Real-data import & threshold tuning

The full export contract, import procedure, and the **pilot tuning checklist** live
in `docs/real-data-import.md`. Summary:
1. The ERP produces four exports (kupci, artikli, fakture, stavke).
2. Import via `POST /api/ingest/import` (multipart) or the CLI; read the
   data-quality report at `GET /api/ingest/report/{id}`.
3. Recompute metrics, run a scan, then tune detection thresholds in **Postavke →
   Pragovi detekcije** against labeled known cases.

---

## 8. Tune detection thresholds

All detection/agent/router thresholds live in `app.rule_config` — never in code.
Change them in **Postavke → Pragovi detekcije** (admin). Every change writes a
reversible `app.decision` (visible in AI Report → the decision feed). Examples:
- `customer_decline.decline_ratio_threshold` — how steep a drop counts as a decline;
- `investigation.max_steps` — the agent's loop cap;
- `llm_router.role_tiers` — role → tier routing.

After changing detection thresholds, run a scan to see the effect:
```sh
docker compose exec api python -c "from valeri_api.scanner.scan import run_scan; \
from valeri_api.db import get_engine; from sqlalchemy.orm import Session; \
s=Session(get_engine()); run_scan(s); s.commit()"
```

---

## 9. Reading the logs

```sh
docker compose logs -f api        # API: requests, LLM calls (metadata), errors
docker compose logs -f worker     # scans, audit, investigations
docker compose logs -f backup     # daily dump status
```
Each line is JSON. To filter by level with `jq`:
```sh
docker compose logs api | sed 's/^[^{]*//' | jq 'select(.level=="ERROR")'
```

---

## 10. Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| Tasks/reports show template text, not rich narration | LLM gateway unreachable | Check `litellm` logs + `ANTHROPIC_API_KEY`; the app degrades to templates by design (no data loss) |
| A queued investigation never finishes | `worker` stopped | `docker compose start worker`; it polls the queue every 10s |
| `/api/health` fails after deploy | migration error on start | `docker compose logs api | grep alembic`; fix + redeploy, or restore (§4) |
| Login fails for everyone after a deploy | `AUTH_SECRET` changed | expected — users re-login |
| Dashboard slow on large data | missing index after a manual schema change | `alembic current` should be at head; re-run `alembic upgrade head` |
| Backup volume filling up | retention too long | lower `BACKUP_RETENTION_DAYS`, recreate `backup` |

---

## 11. The discipline that must never be bypassed

These are product invariants, not options (see `docs/principles.md`):
- **PII masking** before every LLM call — never disable it to save tokens or debug.
- **Numbers come from SQL**, never the model.
- **Append-only audit** (`audit.ai_log`, `audit.task_log`, `app.decision`,
  `audit.llm_route_log`, `app.investigation_step`) — never edit/delete these tables.
- **No writes to the source ERP** — VALERI reads a copy/staging only.
- **Human approval** for every customer-facing message; the investigation agent's
  actions stay behind the HITL gate.
