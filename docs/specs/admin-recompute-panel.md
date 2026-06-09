# Spec — Admin "Podaci i metrike" recompute panel

## 1. Objective

Give the owner/admin **operational control over the derived-metrics pipeline** from the app
instead of only the worker's schedule (or a developer in the container). Today the derived
tables (`core.customer_metrics`, `cust_article_cadence`, `segment_basket`, `client_expectation`)
and `app.signal` are populated only by the scheduled worker job; if they're empty or stale, the
dashboard and `get_customer_360` silently fail and there is **no UI/API to refresh them or even
see their state**. This feature adds an admin status view plus two actions — *recompute metrics*
and *run scan (signals only)* — reusing the existing `recompute_all` and `run_scan`. It is a
cross-cutting operational/admin addition (akin to the M2 ingest admin surface), not a new
milestone; it builds on M3 (metrics), M4 (scanner), and M8 (settings/RBAC + web).

## 2. Scope

**In scope**
- `GET /api/admin/metrics/status` — derived-data state (last computed_at, per-table row counts,
  signal/task counts, last scan time).
- `POST /api/admin/metrics/recompute` — synchronous `recompute_all(as_of=today)`; returns row counts.
- `POST /api/admin/scan` — synchronous `run_scan(as_of=today, create_tasks=False)` (signals only,
  no LLM, no token cost); returns signal count.
- Admin-only RBAC (mirrors the ingest router).
- Frontend "Podaci i metrike" section in the existing **Postavke** screen: status + two action
  buttons with loading/empty/error states; invalidates dashboard/metrics queries on success.
- bs/en strings.

**Out of scope (deferred)**
- Task generation from the scan (`create_tasks=True`) — it calls the LLM per task (cost/latency);
  tasks keep coming from the worker's weekly cycle. (A future toggle could add it.)
- Async/job-queue execution + progress streaming — synchronous is fine for pilot data sizes.
- Editing metric **definitions/SQL** from the UI — definitions stay code-governed in
  `semantic/registry.yaml` (hard rule #1; no free-form SQL).
- Interactive single-metric runner and a full threshold-config surface — separate follow-ups.
- A scheduler-status/next-run view.

## 3. Files

```
apps/api/valeri_api/
  api/admin_metrics.py            NEW  admin router: status + recompute + scan endpoints
  api/schemas/admin_metrics.py    NEW  Pydantic: RecomputeStatus, RecomputeResult, ScanResult
                                       (or inline in the router module if simpler)
  main.py                         EDIT register the admin_metrics router under /api
apps/api/tests/
  test_admin_metrics.py           NEW  RBAC + recompute populates + status counts

apps/web/src/
  features/settings/SettingsPage.tsx        EDIT add the "Podaci i metrike" section (admin-only)
  components/widgets/DataMetricsPanel.tsx    NEW  status card + two action buttons + states
  lib/api/queries.ts                         EDIT useMetricsStatus, useRecompute, useRunScan hooks
  lib/api/types.ts                           EDIT response types
  lib/i18n/bs.ts, lib/i18n/en.ts             EDIT strings
  test/data-metrics-panel.test.tsx           NEW  renders status; buttons trigger mutations
```

## 4. Data-model touchpoints

Read-only over existing tables — **no migration**.

- Reads: `core.customer_metrics` (count + `MAX(computed_at)`), `core.cust_article_cadence` (count),
  `core.segment_basket` (count), `core.client_expectation` (count), `app.signal` (count + `MAX(created_at)`),
  `app.task` (count).
- Writes (via the reused jobs only): `recompute_all` truncates+repopulates the four derived
  `core.*` tables; `run_scan` writes `app.signal` (and consults `app.learned_rule`). No new columns.
- **No `app.decision` write.** Recompute/scan are *operational refreshes of derived data*, not
  configuration changes — principle 10 governs config changes (reversible, logged decisions). The
  inputs (`rule_config`, `learned_rule`) are unchanged; the action only recomputes outputs. Logged
  via structured app logging, not the decision feed. (Documented here so the principle-reviewer
  doesn't flag the missing decision.)

## 5. API touchpoints

New admin endpoints (add to `docs/api-spec.md` §Settings/admin):

- `GET /api/admin/metrics/status` → 
  ```json
  { "customer_metrics": {"rows": 82, "computed_at": "2026-06-03T20:00:00Z"},
    "cust_article_cadence": {"rows": 1007}, "segment_basket": {"rows": 24},
    "client_expectation": {"rows": 82},
    "signals": {"rows": 55, "last_scan_at": "2026-06-03T20:05:00Z"},
    "tasks": {"rows": 0} }
  ```
- `POST /api/admin/metrics/recompute` → `{ "rows": { "core.customer_metrics": 82, ... }, "as_of": "2026-06-03" }`
- `POST /api/admin/scan` → `{ "signals": 55, "as_of": "2026-06-03" }`

All three: `require_roles("admin")` (router-level dependency, like `api/ingest.py`). Errors use the
standard `{ "error": { code, message } }` envelope.

## 6. Tests

Backend — `tests/test_admin_metrics.py`:
- `test_recompute_requires_admin` — owner/finance/sales_rep → 403; admin → 200.
- `test_status_requires_admin` — non-admin → 403.
- `test_recompute_populates_derived_tables` — after a wipe of `core.customer_metrics`, POST
  recompute returns rows>0 and the table is repopulated (count matches response).
- `test_scan_creates_signals_without_tasks` — POST scan returns signals>0 and `app.task` count is
  unchanged (create_tasks=False).
- `test_status_returns_counts` — status row counts equal direct `SELECT COUNT(*)` per table
  (numbers-from-SQL contract).

Web — `test/data-metrics-panel.test.tsx`:
- renders the status (row counts + last computed time) from a mocked `useMetricsStatus`.
- clicking "Preračunaj sada" calls the recompute mutation; success shows updated status / toast.
- the panel is admin-gated (absent/disabled for a non-admin role in SettingsPage).

## 7. Acceptance criteria

- An admin can open **Postavke → Podaci i metrike**, see the last-computed time and per-table row
  counts, click **Preračunaj sada**, and the derived tables are repopulated (counts update);
  clicking **Pokreni skeniranje** refreshes `app.signal` without creating tasks or making an LLM call.
- A non-admin (owner/finance/sales_rep) cannot reach any of the three endpoints (403) and does not
  see the panel.
- Status numbers equal direct SQL counts; recompute/scan invoke the existing `recompute_all` /
  `run_scan` with no new SQL and no LLM call.
- Dashboard/metrics views reflect the refreshed data after the action (query invalidation).

## 8. Principles compliance

| # | Principle | How honored |
|---|-----------|-------------|
| 1 | AI computes no numbers | Recompute/scan are pure SQL/Python; no LLM in this path. Status counts come from SQL. |
| 2 | Evidence on signals | Unchanged — `run_scan` still emits signals with evidence; this only triggers it. |
| 3 | Confidence on conclusions | Unchanged — signal confidence is produced by the existing scanner. |
| 4 | No writes to source ERP | N/A — operates only on `core.*`/`app.*` derived tables. |
| 5 | Read-only/staging in phase 1 | N/A — no source access; recompute reads `core.invoice*`, writes derived `core.*`. |
| 6 | PII masked before LLM | N/A — no LLM call in this feature. |
| 7 | Append-only AI/task/decision logs | No new AI/task/decision rows; action logged via app logging. Recompute is not a config change, so no `app.decision` (documented §4). |
| 8 | Feedback loop is core | N/A — operational refresh, orthogonal to learning. |
| 9 | Analysis/recommendation/action tags | The endpoints are operational admin actions, not AI-tagged outputs; the UI labels them as admin actions, not register-tagged AI surfaces. |
| 10 | Approval for external; self-config auto only if reversible+logged | No external/customer-facing effect; no config change. Recompute/scan are internal, repeatable, idempotent refreshes — re-running reproduces state, so reversibility is inherent. |

## 9. Open questions

1. **Scan default**: confirm `POST /admin/scan` uses `create_tasks=False` (signals only, no cost).
   Should a separate explicit "generiši zadatke" admin action (LLM-backed) be a later add?
2. **`as_of`**: use `date.today()` (matches the worker's daily scan)? Or expose an optional `as_of`
   in the request body for back-dated recompute/testing?
3. **Synchronous vs async**: recompute over pilot data is quick (~sub-second to a few seconds).
   Keep it a blocking request, or move to the worker/job with a polled status? (Default: synchronous.)
4. **Placement**: a section inside the existing **Postavke** screen (recommended) vs. a dedicated
   nav item.
5. **Status freshness**: should `/admin/metrics/status` also surface the scheduler's next-run time,
   or is last-run + counts enough for now? (Default: last-run + counts.)
```
