# Spec — C-CRM2: Rep activity & forecasting

**Track:** Phase-2 CRM (optional, owner-approved) · **Builds on:** C-CRM1 (opportunities, `app.activity` table), M7 (owner report), M8 (dashboard/RBAC) · **Status:** awaiting owner review

## 1. Objective

Complete the Phase-2 CRM: turn the dormant `app.activity` table into **rep activity
logging** with the "Aktivnosti komercijalista" widget (per-rep activity counts +
completion), add **targets/plan** to compute **revenue-vs-plan + a simple forecast**,
and enrich the AI Owner Report with **opportunity-source attribution** and
**average-opportunity-value**. Every figure is SQL-computed (activity rollups,
revenue-vs-plan, run-rate forecast, source breakdowns); the only AI is the report
narrative, which carries a register tag and goes through the existing M6 discipline
(masking → number contract → ai_log). No ERP writes — activity and targets are
VALERI-native data.

## 2. Scope

### In scope

1. **Migration 0017**: `app.revenue_target` (company monthly plan) + demo-target seeds
   in the table; no other schema change (`app.activity` already exists from C-CRM1).
2. **Activity logging** (`crm/activity.py`): `POST /activity` (a rep logs
   meeting/call/offer/follow_up/analysis with a done flag) + `GET /reps/activity?date=`
   (per-rep rollup: counts by kind + completion %), RBAC-scoped.
3. **Forecasting** (`crm/forecast.py`): revenue-vs-plan (actual MTD vs the month's
   target) + a **simple run-rate forecast** (MTD revenue ÷ days elapsed × days in month) —
   pure SQL/Python.
4. **Dashboard**: the "Aktivnosti komercijalista" widget (real per-rep rows), replacing
   the `rep_activity` placeholder; a revenue-vs-plan + forecast tile.
5. **Owner report**: two new sections — **opportunity-source attribution + average
   opportunity value**, and **revenue-vs-plan + forecast** — each register-tagged, numbers
   from SQL, narrative through the M6 discipline (template fallback).
6. **Seed**: demo activities (across reps/kinds, some done) + monthly revenue targets so
   the widgets/report show real data and tests have fixtures.

### Out of scope (deferred)

- Per-rep targets/quotas (company-level monthly plan only; per-rep is a later refinement).
- Editing/deleting activities or targets through the UI (log + view in C-CRM2; the targets
  table is seeded/admin-managed; CRUD on targets is deferred).
- Multi-model forecasting (the run-rate projection is deliberately "simple" per the plan).
- Activity↔opportunity linking and activity-driven signals.
- Any change to the MVP recovery widgets or the C-CRM1 opportunity pipeline.

## 3. Files

### Backend

```
migrations/versions/0017_revenue_targets.py   app.revenue_target (period PK 'YYYY-MM', target_amount)
valeri_api/crm/models.py (edit)               + RevenueTarget model
valeri_api/crm/activity.py                     log_activity(rep, kind, customer?, done) ;
                                               rep_activity_rollup(session, as_of, scope) → per-rep
                                               counts by kind + completion %
valeri_api/crm/forecast.py                     revenue_vs_plan(session, as_of) (actual MTD vs target) ;
                                               run_rate_forecast(session, as_of) (MTD ÷ elapsed × days)
valeri_api/crm/schemas.py (edit)               ActivityCreate/Read, RepActivityRow, ActivityRollup,
                                               RevenueVsPlan, OpportunitySourceRow, OpportunityStats
valeri_api/api/reps.py                          GET /reps/activity?date= ; POST /activity (RBAC)
valeri_api/main.py (edit)                       mount reps_router
valeri_api/metrics/dashboard.py (edit)          assemble_dashboard → rep_activity block + forecast tile
valeri_api/metrics/schemas.py (edit)            DashboardResponse.rep_activity: RepActivityBlock | None ;
                                               + revenue_forecast field
valeri_api/reports/builder.py (edit)            + _opportunity_source_section + _revenue_plan_section
valeri_api/reports/sql/weekly_aggregates.sql (edit)  opportunity_source, opportunity_stats queries
valeri_api/crm/sql/ (new, optional)             activity_rollup / forecast SQL if too big for inline
valeri_api/seed/activity.py                     demo activities + revenue targets
valeri_api/seed/generate.py + loader.py + types.py (edit)   wire activities + targets into SeedData
tests/test_activity.py                          activity rollups + RBAC (TDD, §6)
tests/test_forecast.py                          revenue-vs-plan + run-rate forecast == SQL/Python
tests/test_reports.py (edit)                    the two new sections render with register tags
tests/test_dashboard.py (edit)                  rep_activity block + forecast match SQL
```

### Frontend

```
src/components/widgets/RepActivityRow.tsx       per frontend-spec §4: avatar/name + count chip +
                                               activity summary + completion progress bar
src/features/dashboard/DashboardPage.tsx (edit) real "Aktivnosti komercijalista" widget (replaces the
                                               placeholder) + revenue-vs-plan/forecast in the KPI area
src/lib/api/types.ts + queries.ts (edit)        RepActivity types + useRepActivity/useLogActivity
src/lib/i18n/bs.ts + en.ts (edit)               activity + forecast strings (replace the placeholder)
src/test/rep-activity.test.tsx                  the widget renders per-rep rows + completion
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.activity` | **read + write** (created in C-CRM1) | rep_id, customer_id?, kind, done, at — rollups + logging |
| `app.revenue_target` | **create** (0017) + read | `period TEXT PK` ('YYYY-MM'), `target_amount NUMERIC(14,2)`, `created_at` — company monthly plan; seeded |
| `core.invoice` | read | actual revenue for revenue-vs-plan + the run-rate forecast |
| `app.opportunity` | read | source attribution + average opportunity value (owner report) |
| `core.sales_rep` | read (+ RBAC) | per-rep activity rollup |
| `app.rule_config` | (no new seeds) | forecast method is deterministic; no tunable threshold needed |

Migration **0017** is the one schema-changing migration of this milestone (one new table).

**The numbers (all SQL/Python, the trust-critical part):**
- *Activity rollup* per rep = `COUNT(*)` by `kind` + `done`; completion = `done / total`.
- *Revenue-vs-plan* = actual MTD revenue (`SUM(invoice.total)` this month) vs
  `revenue_target.target_amount` for the period; variance = actual − target.
- *Run-rate forecast* = `actual_MTD / days_elapsed × days_in_month` (Python over the SQL MTD
  value; `days_elapsed`/`days_in_month` from the calendar).
- *Opportunity source* = `COUNT(*)`, `SUM(value)`, `SUM(weighted_value)` grouped by `source`.
- *Average opportunity value* = `AVG(value)` over opportunities (open + all, both reported).

## 5. API touchpoints (per docs/api-spec.md "Reps & activity (Phase 2)")

- `GET /api/reps/activity?date=YYYY-MM-DD` → `{as_of, reps: [{sales_rep_id, name, total,
  done, completion, by_kind: {meeting, call, ...}}]}`. RBAC: owner/admin/finance see all; a
  sales_rep sees only their own row.
- `POST /api/activity` `{kind, customer_id?, done?, at?}` → 201 ActivityRead. RBAC: a
  sales_rep logs their own activity (sales_rep_id forced to theirs); owner/admin may log for
  any rep via `sales_rep_id`. Finance → 403.
- `GET /api/dashboard` (extended) → `rep_activity` block (per-rep rows) + `revenue_forecast`
  (actual MTD, target, variance, forecast).
- `GET /api/reports/owner/weekly` (extended) → two new register-tagged sections.

RBAC: **view activity** = owner/admin/finance/sales_rep (rep → own); **log activity** =
owner/admin/sales_rep (rep → own); finance read-only. The ERP is never written.

## 6. Tests

### `tests/test_activity.py` (TDD)

1. `test_activity_rollup_matches_sql` — `GET /reps/activity` per-rep totals + by-kind counts +
   completion equal an independent SQL `COUNT(*) GROUP BY rep, kind` / `done`. *(acceptance)*
2. `test_completion_rate` — completion = done/total per rep; 0 when a rep has no activities.
3. `test_log_activity_rep_scoped` — a rep's POST forces `sales_rep_id` to theirs; an owner may
   set any rep; finance POST → 403.
4. `test_rep_activity_view_scoped` — a rep's `GET /reps/activity` returns only their own row;
   owner/admin/finance see all reps.
5. `test_activity_api_envelopes` — invalid `kind` → 422; bad date → 422.

### `tests/test_forecast.py` (TDD — these are numbers)

6. `test_revenue_vs_plan_matches_sql` — actual MTD == `SUM(invoice.total)` for the month;
   target == `revenue_target` for the period; variance == actual − target. *(acceptance)*
7. `test_run_rate_forecast` — forecast == `actual_MTD / days_elapsed × days_in_month`, computed
   independently; handles day-1 (no divide-by-zero) and a missing target (variance null). *(acceptance)*
8. `test_forecast_no_target_is_honest` — a period with no target → target null, variance null,
   forecast still computed from actuals.

### `tests/test_reports.py` (edit)

9. `test_owner_report_crm_sections` — the report now includes `prilike_po_izvoru` and
   `prihod_vs_plan`; both carry a register tag; numbers equal SQL; SECTION_KEYS updated.
   *(acceptance: owner-report additions render with register tags)*
10. `test_opportunity_source_and_avg_value_match_sql` — source breakdown counts/values and the
    average opportunity value equal independent SQL.

### `tests/test_dashboard.py` (edit)

11. `test_dashboard_rep_activity_block` — the `rep_activity` block is no longer null; per-rep
    rows + completion match SQL; replaces the placeholder.
12. `test_dashboard_revenue_forecast` — actual/target/variance/forecast match SQL/Python.

### Web (`src/test/rep-activity.test.tsx`)

13. The "Aktivnosti komercijalista" widget renders per-rep rows with the count chip, the
    activity summary, and the completion progress bar.

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN C-CRM2)

1. **Activity rollups match SQL** — the per-rep widget/endpoint never disagrees with an
   independent SQL count. *(tests 1, 2, 11)*
2. **Revenue-vs-plan and forecast correct** — actual/target/variance and the run-rate forecast
   equal independent computations. *(tests 6, 7, 8, 12)*
3. **Owner-report additions render with register tags** — the opportunity-source and
   revenue-vs-plan sections appear, register-tagged, numbers from SQL. *(tests 9, 10)*
4. **Writes are RBAC-gated** — reps log only their own activity; finance read-only; ERP never
   written. *(tests 3, 4)*

## 8. Principles compliance

| # | Principle | How C-CRM2 honors it |
|---|---|---|
| 1 | AI computes no numbers | Activity rollups, revenue-vs-plan, the run-rate forecast, source breakdowns, avg value — all SQL/Python; the report narrative passes the M6 number contract; tests assert API == SQL |
| 2 | Evidence on signals/tasks | N/A — activity/targets are user/SQL data, not AI signals |
| 3 | Confidence on conclusions | The owner-report narrative sections carry the register tag and (via M6) log their narration to ai_log; the figures themselves are SQL facts, not AI conclusions, so no confidence band applies to the data |
| 4 | No writes to source ERP | Activity + targets are `app.*` rows; revenue is read from `core.invoice`; the ERP is never written |
| 5 | Read-only/staging | Unchanged |
| 6 | PII masking before LLM | The two new report sections mask customer/rep identity before narration (the existing `_mask_items` discipline) — only finished SQL numbers + pseudonyms reach the prompt |
| 7 | Append-only logs | `app.activity` is append-style logging (rows inserted; a `done` flag toggle is the one allowed mutation, and is an activity-state update, not an audit log); revenue_target is reference data |
| 8 | Feedback loop | N/A for this track |
| 9 | Register/visibility | Both new report sections are register-tagged (`analiza`); the dashboard activity/forecast widgets are clearly labeled user/SQL data, not AI output |
| 10 | Approval/reversible self-config | N/A — activity logging + targets are direct RBAC-gated data entry, not AI self-config; no `app.decision` needed |

## 9. Open questions (decide before implementation)

- **D1 — Targets granularity:** company-level **monthly** revenue targets
  (`app.revenue_target`, period 'YYYY-MM') only; per-rep quotas deferred. OK?
- **D2 — Forecast method:** simple **run-rate** = `actual_MTD / days_elapsed × days_in_month`.
  Deterministic, no model, no tunable. OK, or a trailing-3-month average instead?
- **D3 — Owner-report sections:** add **two** new sections — `prilike_po_izvoru`
  (opportunity-source + avg value) and `prihod_vs_plan` (revenue-vs-plan + forecast) — both
  LLM-narrated with template fallback + register tag, like the existing decline/lost sections.
  OK, or template-only (cheaper, no LLM) like the suppressed/drafts sections?
- **D4 — Activity `done` is mutable:** an activity can be toggled done/not-done (a planned
  activity gets completed). This is an activity-state update, not an audit-log mutation. OK?
- **D5 — RBAC:** log = owner/admin/sales_rep (rep → own); view = +finance; finance read-only.
  Owner/admin may log on behalf of any rep. OK?
- **D6 — Seed:** demo activities (across reps/kinds, ~40, some done) + 6 monthly targets
  around `as_of`. OK?
- **D7 — Dashboard activity widget scope:** the dashboard is owner/admin/finance-gated, so the
  widget shows **all** reps (unrestricted). Reps see their own activity via `/reps/activity`
  (the dashboard isn't a rep surface). OK?
