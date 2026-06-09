# Spec — P2: Operational hardening (alerting, health, limits, backups)

**Track:** Improvement Roadmap P2 (`docs/IMPROVEMENT-ROADMAP.md`) · **Builds on:** P1 inbox (`alerts` field reserved at 0), scanner/scheduler (M4/M14), auth (M8), backup compose service (M14), CI1 chat capture · **Status:** draft (awaiting owner review)

## 1. Objective

A pilot must run unattended without silent failure or runaway spend. Today every scheduled job swallows its exception into a log nobody reads (`scanner/scheduler.py:55-58`), `/api/health` only pings the DB, the scanner happily runs over stale data, the API has no rate limiting, login has no throttle, backups are never restore-tested, and synchronous chat capture delays every reply. P2 ships: a **job-run ledger** with **consecutive-failure + freshness alerts surfaced in the P1 bell**, a **real health check** (DB + LiteLLM + worker heartbeat + migration head), a **scanner freshness guard**, **per-user rate limiting** (chat strictest) + login throttle, **sliding session renewal + CSRF double-submit**, **backup restore-verification**, and **non-blocking chat capture** (reply streams first; capture follows with a 5s cap, chip preserved).

## 2. Scope

### In scope
- `app.job_run` ledger (migration `0024`) written by scan/weekly/audit/restore-check jobs + a worker-heartbeat row; `record_job_run()` wrapper in the scheduler.
- Alert derivation (pure SQL): a job's last `ops.alert_consecutive_failures` runs all failed → alert; last successful daily scan older than `ops.scan_stale_days` → alert; restore-check failed/missing > 8 days → alert. Inbox `alerts` = count of active conditions; bell dropdown links to Postavke → Podaci; `GET /admin/ops/status` feeds that tab (per-job last run/status/consecutive failures + freshness + alert reasons).
- **Scanner freshness guard**: `run_scan` skips detection (status `skipped`, reason recorded) when `max(core.invoice.date)` is older than `ops.scan_stale_days`; thresholds seeded in `app.rule_config` (rule `ops`).
- **Health**: `/api/health` → `{status: ok|degraded, db, llm_gateway, worker, migrations}` (LiteLLM probe w/ 2s timeout; worker = heartbeat row fresher than 2× poll interval; migrations = `alembic_version` == repo head). Always HTTP 200 (liveness); `status` says degraded.
- **Rate limiting**: in-process token-bucket middleware — login 5/min/IP, chat-message 10/min/user, default 120/min/user; env-configurable; 429 with the error envelope. Exempt: `/api/health`.
- **Auth hardening**: sliding renewal (an authed `GET /auth/me` re-issues the cookie when >half-expired); CSRF double-submit (non-HttpOnly `valeri_csrf` cookie set at login + `X-CSRF-Token` header required on POST/PATCH/DELETE; web client attaches it; SameSite=Lax stays).
- **Backup verification**: `infra/backup/verify.sh` — weekly restore of the newest dump into a scratch DB on the `db` service (table-count sanity + row-count of `core.invoice`), sha256 recorded per dump, result written to `app.job_run('backup_restore_check')` via psql; compose wiring; RUNBOOK section.
- **Chat capture latency**: stream the reply events first, then run capture inside the SSE generator with a **5s cap** (thread + timeout), yielding the `capture` event before `done` only if it finishes; on timeout the capture continues server-side but the chip is skipped.

### Out of scope (deferred)
- E-mail/webhook alert delivery (bell-only now); X1 cost tracking/budgets (P3); distributed rate limiting (single api container); rotating `auth_secret`; PITR/WAL archiving (runbook note only); document-pipeline jobs (P5).

## 3. Files

```
apps/api/
  migrations/versions/0024_job_runs.py     # app.job_run + ops.* rule_config seeds
  valeri_api/ops/__init__.py
  valeri_api/ops/models.py                 # JobRun model
  valeri_api/ops/runs.py                   # record_job_run() ctx-mgr; heartbeat(); freshness +
                                           #   consecutive-failure + alert-derivation SQL
  valeri_api/api/ops.py                    # GET /admin/ops/status (owner/admin)
  valeri_api/api/inbox.py                  # EDIT: alerts = derived count (replaces hardcoded 0)
  valeri_api/api/health.py                 # EDIT: db + llm_gateway + worker + migrations
  valeri_api/scanner/scheduler.py          # EDIT: wrap jobs in record_job_run; heartbeat in poll
  valeri_api/scanner/scan.py               # EDIT: freshness guard (skip + reason)
  valeri_api/middleware.py                 # NEW: RateLimitMiddleware + CSRFMiddleware
  valeri_api/main.py                       # EDIT: add middlewares + ops router
  valeri_api/api/auth.py                   # EDIT: csrf cookie at login; sliding renewal in /auth/me
  valeri_api/auth/tokens.py                # EDIT: issued-at claim (for renewal half-life)
  valeri_api/config.py                     # EDIT: rate-limit knobs, llm health timeout
apps/api/tests/
  test_ops.py                              # ledger, alerts, freshness guard, ops status (TDD)
  test_health.py                           # degraded states per dependency
  test_middleware.py                       # rate limit 429s, login throttle, CSRF 403/pass
  test_inbox.py                            # EDIT: alerts wired into summary/total
infra/
  backup/backup.sh                         # EDIT: sha256 per dump
  backup/verify.sh                         # NEW: weekly scratch-restore + job_run write
  docker-compose.yml                       # EDIT: verify wiring (backup service loop)
docs/RUNBOOK.md                            # EDIT: alerting, restore-verify, rate limits, CSRF
apps/web/src/
  lib/api/client.ts                        # EDIT: send X-CSRF-Token from the csrf cookie
  lib/api/types.ts + queries.ts            # EDIT: OpsStatus + useOpsStatus
  app/TopBar.tsx                           # EDIT: alerts entry in the bell dropdown
  features/settings/SettingsPage.tsx       # EDIT: Podaci tab shows the ops-status table
  lib/i18n/bs.ts / en.ts                   # EDIT: ops strings
apps/web/src/test/ops-status.test.tsx      # NEW: panel renders job statuses + alert reasons
```

## 4. Data-model touchpoints

- **NEW (migration `0024`)**: `app.job_run` — `id`, `job TEXT`, `started_at`, `finished_at`, `status TEXT ('running'|'ok'|'failed'|'skipped')`, `error TEXT`, `detail JSONB`; index `(job, id DESC)`. **Operational telemetry, not an audit log** — prunable (the worker keeps the last 90 days), explicitly distinct from the append-only `audit.*`/`app.decision` family. The worker heartbeat is a single upserted row (`job='worker_heartbeat'`).
- **`app.rule_config` seeds** (rule `ops`): `alert_consecutive_failures=2`, `scan_stale_days=7`, `restore_check_max_age_days=8` — thresholds in DB, never code.
- Reads: `core.invoice` (freshness), `alembic_version` (health). No changes to existing tables.

## 5. API touchpoints

- **EDIT `GET /api/health`** → `{status, db, llm_gateway, worker, migrations}` (always 200).
- **NEW `GET /api/admin/ops/status`** (owner/admin) → `{jobs: [{job, last_status, last_ok_at, last_run_at, consecutive_failures}], data_freshness: {last_invoice_date, stale}, alerts: [{kind, message}]}` — all SQL.
- **EDIT `GET /api/inbox/summary`** → `alerts` becomes the derived count (owner/admin only; others 0).
- **Auth**: login also sets the `valeri_csrf` cookie; mutating endpoints require `X-CSRF-Token` matching it (401/403 envelope on mismatch); `GET /auth/me` re-issues a fresh session cookie past half-life.
- **Cross-cutting**: 429 envelope `{error: {code: "rate_limited", …}}` from the limiter.

## 6. Tests

**Backend (TDD):**
- `test_ops.py::test_job_run_recorded_ok_and_failed` — wrapper writes `running→ok` and `running→failed` (+error) rows.
- `test_ops.py::test_consecutive_failures_alert` — 2 failed runs → alert; an `ok` in between → none (threshold from `rule_config`).
- `test_ops.py::test_scan_freshness_guard` — stale `core.invoice` → scan skipped + `job_run(status='skipped')` + freshness alert; fresh → runs (planted dates).
- `test_ops.py::test_ops_status_matches_sql_and_rbac` — payload == SQL; rep/finance 403.
- `test_inbox.py::test_alerts_wired` — derived alert count appears in `alerts` and `total` for owner; 0 for rep.
- `test_health.py::test_degraded_states` — unreachable LiteLLM → `llm_gateway: unavailable` + `status: degraded`; stale/missing heartbeat → `worker: stale`; migration mismatch → `migrations: behind` (monkeypatched probes).
- `test_middleware.py::test_chat_rate_limit` — burst over the chat limit → 429 envelope; under limit → 200.
- `test_middleware.py::test_login_throttle` — 6th login attempt/min from one IP → 429.
- `test_middleware.py::test_csrf_required_on_mutations` — POST without `X-CSRF-Token` → 403; with matching header → passes; GETs unaffected.
- `test_middleware.py::test_sliding_renewal` — `/auth/me` with a >half-aged token re-issues the cookie.

**Frontend:** `ops-status.test.tsx` — Podaci tab renders per-job rows + alert reasons; bell shows the alerts entry. (Client CSRF header covered implicitly by all existing mutation tests once attached.)

**Infra (manual/acceptance):** `verify.sh` against the seed dump restores into scratch and writes the `job_run` row.

## 7. Acceptance criteria

1. A deliberately failing scan produces a `job_run(failed)` row and, on the 2nd consecutive failure, an alert visible in the owner's bell within one cycle.
2. Stale `core.invoice` (≥ `ops.scan_stale_days`) → the scan **skips** (recorded, alerted) instead of silently scanning old data.
3. `/api/health` reports `degraded` when LiteLLM is unreachable, the worker heartbeat is stale, or migrations are behind.
4. Chat-message bursts over the limit get 429 (proper envelope); the 6th login/min from one IP is throttled.
5. Mutating requests without the CSRF header are rejected; the web app works unchanged (client attaches it automatically); a >half-aged session is silently renewed on `/auth/me`.
6. The restore-verification job restores the newest dump into a scratch DB, sanity-checks it, and records `job_run('backup_restore_check', ok)`; its absence/failure raises an alert.
7. A chat reply streams its text without waiting for capture; the capture chip still appears when capture completes within 5s; a slow capture never blocks the stream.
8. Full backend + frontend suites green; RUNBOOK updated.

## 8. Principles compliance

| # | Principle | How P2 honors it |
|---|-----------|------------------|
| 1 | No LLM-computed numbers | No LLM use added; all counts/alerts/freshness are SQL; health probes are infrastructure. |
| 2/3 | Evidence/confidence on AI output | N/A — no AI conclusions; alerts are deterministic ops facts carrying their reason + job rows. |
| 4/5 | No ERP writes / read-only staging | Untouched; `job_run` lives in VALERI's own `app` schema; the scratch restore DB is dropped after the check. |
| 6 | PII masking | Untouched; the capture refactor changes WHEN capture runs, not its masking path. |
| 7 | Append-only logs | `audit.*`/`app.decision` untouched; `job_run` is documented as prunable telemetry (not audit) so retention can't be mistaken for tampering. |
| 8 | Feedback loop | Strengthened — the system now reports on itself; failures reach a human. |
| 9 | Analysis/recommendation/action | Alerts are plain system notices (no register needed — not business AI output); nothing happens silently is *extended* to the platform itself. |
| 10 | Approval/reversibility | No new auto-actions on business data; rate-limit/CSRF are request gates; thresholds live in `rule_config`. |

## 9. Open questions (defaults — confirm or override)

- **D1 alert recipients:** alerts appear for owner+admin only (reps/finance see 0). *(default)*
- **D2 rate limits:** login 5/min/IP, chat 10/min/user, default 120/min/user — env-tunable, in-process. *(default)*
- **D3 CSRF scheme:** double-submit cookie+header on POST/PATCH/DELETE (SameSite=Lax kept). Pure-API clients must send the header. *(default)*
- **D4 session:** keep 12h tokens + sliding renewal on `/auth/me` (no separate refresh token). *(default)*
- **D5 job_run retention:** prune > 90 days inside the weekly job. *(default)*
- **D6 restore-verify cadence:** weekly (Sun 04:00) in the backup container; scratch DB `valeri_restore_check` created/dropped per run. *(default)*
- **D7 capture cap:** 5 seconds; on timeout the capture still completes server-side, only the inline chip is skipped. *(default)*
