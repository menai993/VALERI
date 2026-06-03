# Spec — M14: Hardening, backups, runbook, pilot readiness

**Milestone:** M14 · **Builds on:** M0–M13 (the complete system) · **Status:** approved (D1–D5 defaults OK'd by owner, 2026-06-03)

## 1. Objective

Make VALERI **operable by someone who didn't build it**. Backups run on a schedule and restore
provably; every service emits structured JSON logs; the scanner/metrics/dashboard hot paths get a
measured perf pass with regression guards; `docs/RUNBOOK.md` covers every operational task (deploy,
upgrade, backup/restore, secret rotation, Tier-2 model swap, threshold tuning); the real-data
import path and the pilot tuning checklist are written down; and the **full acceptance suite
(items 1–13 from the plan)** is executed and documented in `docs/ACCEPTANCE-REPORT.md`. This is
the last milestone before the Ultra Higijena pilot.

## 2. Scope

### In scope

1. **Backups**: a `backup` compose service (pg_dump on a daily schedule, rotation), a manual
   `backup.sh`, and a `restore.sh` that provably restores — with a test that round-trips
   dump → restore → table-count comparison.
2. **Structured JSON logging**: one `logging_config.py` used by the API and the worker — one JSON
   object per line (ts, level, logger, message, extras); test asserts parseability and fields.
3. **Perf pass**: EXPLAIN-driven review of the scanner / metrics-recompute / dashboard SQL; add
   any missing indexes (migration 0015, only if needed); a perf regression test with generous
   budgets so CI stays stable.
4. **`docs/RUNBOOK.md`**: deploy · upgrade (incl. migrations) · backup/restore · rotate secrets
   (PII salt caveat!) · switch the Tier-2 model (both paths: .env and Settings) · tune thresholds ·
   read the logs · common failures.
5. **`docs/real-data-import.md`**: the export format the ERP must produce, the import procedure,
   and the **pilot tuning checklist** (load real export → verify counts → label known cases →
   tune thresholds → validate detection quality).
6. **`docs/ACCEPTANCE-REPORT.md`**: run the full suite; map every acceptance item (1)–(13) to its
   test evidence and result; mark pilot-time items explicitly as "measured during pilot".
7. **Housekeeping found along the way**: the worker compose comment still says "Placeholder
   worker (M0)"; backup volume; compose healthchecks for worker.

### Out of scope (deferred)

- The C-CRM / CI / DI / X tracks (separate, optional tracks per the plan).
- Off-site backup shipping (the runbook documents the hook; the pilot decides the destination).
- Log aggregation/shipping (ELK etc.) — JSON logs are the interface; aggregation is a pilot choice.
- Load testing beyond the seed-scale perf budgets (real-data scale is a pilot activity).
- Acceptance items that are pilot measurements by definition: (8) useless-task share falling over
  4–6 weeks, and the "voluntary usage" gate — the report defines HOW they will be measured.

## 3. Files

```
infra/backup/backup.sh                      pg_dump (custom format) + rotation; usable manually and by cron
infra/backup/restore.sh                     pg_restore into a target DB with an explicit confirmation arg
infra/docker-compose.yml (edit)             + backup service (postgres:16 image, daily loop, backups volume);
                                            worker comment/healthcheck cleanup
infra/.env.example (edit)                   + BACKUP_RETENTION_DAYS, BACKUP_HOUR
apps/api/valeri_api/logging_config.py       setup_json_logging(): JSON formatter + uvicorn/worker wiring
apps/api/valeri_api/main.py (edit)          call setup_json_logging() at startup
apps/api/valeri_api/worker.py (edit)        use setup_json_logging() (replaces basicConfig)
apps/api/migrations/versions/0015_*.py      ONLY if the perf pass finds missing indexes
apps/api/tests/test_hardening.py            JSON logging test · backup/restore round-trip test ·
                                            perf regression test (scan/recompute/dashboard budgets)
docs/RUNBOOK.md                             the operations manual (§4 below)
docs/real-data-import.md                    ERP export contract + import procedure + pilot tuning checklist
docs/ACCEPTANCE-REPORT.md                   the executed acceptance suite, item by item
docs/specs/m14-hardening.md                 this spec
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| (possibly) indexes on `app.signal`, `app.task`, `core.invoice`, `core.invoice_line` | **create** (0015, only if EXPLAIN shows them missing) | No new tables, no column changes — M14 changes no schema shape |
| Everything | read | the backup dumps all schemas; the acceptance suite exercises everything |

## 5. API touchpoints

None — no new or changed endpoints. (The perf pass may change SQL *inside* existing endpoints;
contracts stay identical, proven by the existing test suites.)

## 6. Tests (`tests/test_hardening.py`, new)

1. `test_json_logging_format` — `setup_json_logging()` makes a log record render as one parseable
   JSON line containing `ts`, `level`, `logger`, `message`; extra fields pass through.
2. `test_backup_restore_roundtrip` — run `backup.sh` against the test DB → restore into a scratch
   DB → row counts per table match the source (the backup is provably restorable).
3. `test_perf_budgets` — on the seeded DB: `run_scan` (no recompute) < 10s, `recompute_all` < 10s,
   `assemble_dashboard` < 3s. Generous budgets = regression guard, not a benchmark.
4. `test_scanner_query_plans_use_indexes` — EXPLAIN the heaviest scanner/dashboard queries; assert
   no sequential scan over `core.invoice_line` / `core.invoice` (the only tables that grow
   unboundedly with real data).

Everything else M14 produces is documentation + the executed acceptance run:

5. **The full suite run** (`uv run pytest` + `npx vitest run`) is itself the acceptance evidence —
   the report records counts, versions, and the mapping below.

**Acceptance item → evidence mapping (what ACCEPTANCE-REPORT.md will contain):**

| # | Plan item | Evidence |
|---|---|---|
| 1 | numbers match the export to the cent | `test_ingest.py` (idempotent double-import, totals to the cent) |
| 2 | sampled customer model correct, no invented links | `test_capability_a.py` |
| 3 | lost articles correct, code-swaps not flagged | `test_scanner.py` |
| 4 | decline-vs-seasonal accuracy with explanations | `test_scanner.py` (planted + seasonal guards) + signal evidence |
| 5 | weekly scan surfaces signals with no user query | `test_scanner.py` + `test_reports.py` |
| 6 | one task per signal, correct assignee | `test_tasks.py` |
| 7 | 100% customer-facing comms pass approval | `test_approvals.py` + `test_reports.py` (drafts never auto-send) |
| 8 | useless-task share falls over 4–6 weeks | **pilot measurement** — method: weekly ratio of task_feedback useful=false; baseline defined in the report |
| 9 | Bosnian question → SQL numbers, register, logged | `test_chat.py` |
| 10 | dismissal → decision + rule + suppression + Undo | `test_selfconfig.py` |
| 11 | auditor re-surfaces drifted suppression | `test_auditor.py` |
| 12 | agent: caps, HITL, no invented numbers, checkpoint resume | `test_investigation.py` |
| 13 | Tier-2 swap config-only, masking intact | `test_router.py` + `test_settings_api.py` |
| — | voluntary usage gate | **pilot measurement** — method: weekly active reps / owner ERP-open frequency |

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN M14)

1. **The full suite passes** — backend + web, all green, recorded in ACCEPTANCE-REPORT.md.
2. **Backups restore provably** — the round-trip test passes; the runbook procedure works.
3. **Structured logging** — every service emits parseable JSON lines.
4. **The runbook covers**: deploy, upgrade, backup/restore, rotate secrets, switch Tier-2 model,
   tune thresholds — each as a copy-pasteable procedure.
5. **principle-reviewer + /decision-audit pass** one final time over the M14 diff.

## 8. Principles compliance

| # | Principle | How M14 honors it |
|---|---|---|
| 1 | AI computes no numbers | No LLM-related changes; perf pass touches SQL only |
| 2–3 | Evidence/confidence | Unchanged |
| 4–5 | No source writes / read-only | The backup reads; restore targets VALERI's own DB only; runbook warns against touching the ERP |
| 6 | PII masking | Logging config must NOT log prompt payloads/PII — the JSON formatter logs metadata, never request bodies; the runbook's secret-rotation section covers PII_SALT implications |
| 7 | Append-only logs | Backups preserve them; restore procedure documents that audit history comes back as-is |
| 8 | Feedback loop | The acceptance report defines how item 8 (feedback trend) is measured in the pilot |
| 9–10 | Register/approval | Unchanged; the acceptance report proves them (items 7, 9, 12) |

## 9. Open questions (decide before implementation)

- **D1 — Backup schedule/retention:** daily at 02:00 (Europe/Sarajevo), 14-day retention, dumps in
  a named Docker volume (`pg_backups`), `pg_dump -Fc` custom format. The runbook documents copying
  dumps off-host. OK?
- **D2 — Perf budgets** (regression guards on seed-scale data): scan < 10s, recompute < 10s,
  dashboard < 3s. Generous on purpose — they catch order-of-magnitude regressions, not noise. OK?
- **D3 — Logging:** app + worker loggers → JSON lines on stdout (Docker-native); uvicorn access
  logs stay default (Caddy already logs requests); no payload/PII content is ever logged. OK?
- **D4 — Pilot-only items:** acceptance items 8 + the voluntary-usage gate are documented as
  pilot measurements with a defined method, not faked as "passed". OK?
- **D5 — Documentation language:** RUNBOOK / real-data-import / ACCEPTANCE-REPORT in **English**
  (consistent with all other docs/; the UI and AI outputs stay Bosnian). OK?
