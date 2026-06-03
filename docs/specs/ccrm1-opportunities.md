# Spec — C-CRM1: Opportunity model & pipeline

**Track:** Phase-2 CRM (optional, owner-approved) · **Builds on:** M1 (customers/reps), M8 (auth/RBAC, dashboard), M14 (the complete system) · **Status:** awaiting owner review

## 1. Objective

Turn VALERI from read-only Sales-Recovery analytics into a system that also tracks a
**managed opportunity pipeline**. Reps and the owner record deals (customer, value,
probability, stage), move them through stages (lead → … → won/lost) with an
append-only stage history, and see a **kanban + table + probability-weighted
pipeline value** on the Prilike screen — plus real *Otvorene prilike / Stopa
konverzije / Najveće prilike* on the dashboard, replacing the Phase-2 placeholders.
This is the first track where VALERI accepts **data entry**; it introduces no LLM
and no ERP writes — opportunity data is VALERI-native, RBAC-gated, and all pipeline
figures are SQL-computed.

## 2. Scope

### In scope

1. **Migration 0016**: `opp_stage` enum + `app.opportunity`, `app.opportunity_stage_history`,
   `app.activity` (exactly per data-model.md Phase-2 section) + stage→default-probability
   seeds in `app.rule_config` (never hard-coded).
2. **`crm/` package**: typed CRUD (create/update with RBAC scope), stage transitions that
   append `opportunity_stage_history`, and the **SQL pipeline aggregation** (weighted value
   per stage + conversion rate).
3. **API**: `GET /opportunities?stage=`, `POST /opportunities`, `PATCH /opportunities/{id}`,
   `GET /opportunities/pipeline` (kanban columns + weighted value + conversion).
4. **Dashboard**: a real `opportunities` summary block (Otvorene prilike, Stopa konverzije,
   Najveće prilike) in the payload + the Prilike-tiles on Početna, replacing the placeholder.
5. **Prilike screen**: kanban by stage (drag-free; a stage dropdown per card) + a DataTable +
   the weighted-value header; "Nova prilika" create form.
6. **Seed**: demo opportunities across stages (linked to seeded customers/reps) so the screen
   and the dashboard show real data and tests have fixtures.

### Out of scope (deferred)

- **`app.activity` usage** → C-CRM2. The *table* is created here (one migration per
  schema-changing milestone, and it sits in the same Phase-2 DDL block), but rep-activity
  logging, the "Aktivnosti komercijalista" widget, forecasting, and revenue-vs-plan are C-CRM2.
- Drag-and-drop kanban (a stage `<Select>` per card is the MVP interaction).
- Opportunity↔commercial_event linking (the CI track's `opportunity_id` field), targets/quotas,
  opportunity-source analytics, and the weekly report's opportunity section.
- Any LLM involvement — there is none in C-CRM1.

## 3. Files

### Backend

```
migrations/versions/0016_crm_opportunities.py   opp_stage enum + opportunity / opportunity_stage_history
                                                / activity tables + stage-probability rule_config seeds
valeri_api/crm/__init__.py
valeri_api/crm/models.py                         Opportunity, OpportunityStageHistory, Activity (SQLAlchemy)
valeri_api/crm/schemas.py                        OpportunityCreate/Update/Read, PipelineStage, PipelineResponse,
                                                 OpportunitySummary (dashboard block)
valeri_api/crm/probability.py                    stage_probability(session): stage→default prob from rule_config;
                                                 effective_probability(opp): explicit value OR stage default
valeri_api/crm/service.py                        create_opportunity / update_opportunity (RBAC scope + stage
                                                 history append) · pipeline(session, scope) (SQL weighted value
                                                 + conversion) · dashboard_summary(session, scope)
valeri_api/api/opportunities.py                  the 4 endpoints (RBAC-gated; rep scoped to own customers)
valeri_api/main.py (edit)                        mount opportunities_router
valeri_api/metrics/dashboard.py (edit)           assemble_dashboard → include opportunities summary
valeri_api/metrics/schemas.py (edit)             DashboardResponse.opportunities: OpportunitySummary | None
valeri_api/seed/opportunities.py                 generate demo opportunities across stages
valeri_api/seed/generate.py + loader.py (edit)   + opportunities to SeedData + load()
tests/test_opportunities.py                      pipeline math, RBAC, CRUD, stage history (TDD, §6)
tests/test_dashboard.py (edit)                   the opportunities block is present + matches SQL
```

### Frontend

```
src/features/opportunities/OpportunitiesPage.tsx (rewrite)  kanban (stage columns) + DataTable + weighted-value
                                                            header + Nova prilika form + stage <Select> per card
src/components/widgets/OpportunityCard.tsx                  one kanban card (title, customer, value, prob, stage select)
src/features/dashboard/DashboardPage.tsx (edit)             Prilike tiles: Otvorene prilike / Stopa konverzije /
                                                            Najveće prilike (replaces the placeholder)
src/lib/api/types.ts + queries.ts (edit)                   Opportunity types + useOpportunities/usePipeline/
                                                            useCreateOpportunity/useUpdateOpportunity
src/lib/i18n/bs.ts + en.ts (edit)                          opportunity strings (replace the "uskoro" placeholder)
src/test/opportunities.test.tsx                            kanban renders by stage; weighted value; create + stage move
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `opp_stage` enum | **create** (0016) | lead/qualified/proposal/negotiation/won/lost |
| `app.opportunity` | **create** (0016) + CRUD | customer_id, title, value, probability, stage, source, expected_close, owner_rep_id — exactly per data-model.md |
| `app.opportunity_stage_history` | **create** (0016) + append-only writes | one row per stage transition (incl. the initial stage at create) |
| `app.activity` | **create** (0016) only | table created now; used in C-CRM2 |
| `app.rule_config` | **seed** (0016) + read | rule=`crm`: `stage_probability` (JSONB map: lead 0.1 … negotiation 0.7, won 1.0, lost 0.0) — tunable, never hard-coded |
| `core.customer`, `core.sales_rep` | read (FK + RBAC scope) | opportunity belongs to a customer; owner_rep_id is the rep |

Migration **0016** is the one schema-changing migration of this track.

**Pipeline math (the trust-critical, SQL-only part):**
- *Effective probability* of an opportunity = its explicit `probability` if set, else the
  `stage_probability` default for its stage.
- *Weighted value* = `SUM(value × effective_probability)` over **open** stages
  (lead/qualified/proposal/negotiation; won/lost are closed and excluded from pipeline value).
- *Conversion rate* = `won / (won + lost)` over closed opportunities (0 when none closed).
- All three computed in SQL; tests assert the API numbers equal an independent SQL query.

## 5. API touchpoints (per docs/api-spec.md "Opportunities — CRM (Phase 2)")

- `GET /api/opportunities?stage=&customer_id=` → `{items: OpportunityRead[]}` (rep: own only).
- `POST /api/opportunities` `{customer_id, title, value?, probability?, stage?, source?,
  expected_close?, owner_rep_id?}` → 201 OpportunityRead; appends the initial stage_history row.
  RBAC: owner/admin any; sales_rep only for their own customers (owner_rep_id forced to the rep).
- `PATCH /api/opportunities/{id}` `{title?, value?, probability?, stage?, source?,
  expected_close?}` → OpportunityRead; a stage change appends a stage_history row. RBAC as above
  (rep only on their own opportunities).
- `GET /api/opportunities/pipeline` → `{stages: [{stage, count, value, weighted_value,
  opportunities[]}], total_weighted_value, conversion_rate}` (kanban + weighted value).
- `GET /api/dashboard` (extended) → `+ opportunities: {open_count, conversion_rate,
  weighted_value, top: [{id, title, customer_name, value, probability, weighted_value}]}`.

RBAC matrix: **view** = owner/admin/finance/sales_rep (rep → own customers' opportunities);
**create/update** = owner/admin/sales_rep (rep → own customers only); finance is read-only.

## 6. Tests (`tests/test_opportunities.py`, TDD — pipeline math is numbers, trust-critical)

1. `test_pipeline_weighted_value_matches_sql` — `GET /pipeline` `total_weighted_value` equals an
   independent `SUM(value × COALESCE(probability, stage_default))` over open stages; per-stage
   `weighted_value` matches too. *(acceptance: pipeline math == SQL)*
2. `test_conversion_rate_matches_sql` — `conversion_rate` == `won / (won + lost)` from SQL; 0.0
   when nothing is closed.
3. `test_effective_probability_uses_stage_default` — an opportunity with `probability=NULL`
   contributes its stage's default; an explicit probability overrides it.
4. `test_stage_probability_lives_in_rule_config` — changing `crm.stage_probability` in the DB
   changes the weighted value; nothing hard-coded.
5. `test_create_appends_initial_stage_history` — POST creates the opportunity + exactly one
   stage_history row (the initial stage).
6. `test_stage_change_appends_history` — PATCH that changes stage appends a stage_history row;
   a PATCH that doesn't change stage appends none; history is append-only (no update/delete).
7. `test_rbac_rep_own_customers_only` — a rep can create/patch opportunities for their own
   customers; a foreign customer → 403; finance create/patch → 403; finance GET → 200.
8. `test_rbac_rep_list_scoped` — a rep's `GET /opportunities` returns only their customers'
   opportunities (the at-risk RBAC scope pattern).
9. `test_pipeline_kanban_columns` — `/pipeline` returns all six stages in order, each with its
   count/value/weighted_value and opportunity rows.
10. `test_api_envelopes` — 404 on a missing opportunity; 422 on an invalid stage; numbers are
    returned as exact strings (client formats).

`tests/test_dashboard.py` additions:

11. `test_dashboard_opportunities_block` — the dashboard payload's `opportunities` block
    (open_count, conversion_rate, weighted_value, top[]) equals independent SQL; replaces the
    placeholder (the field is no longer null when opportunities exist).

Web (`src/test/opportunities.test.tsx`):

12. The Prilike screen renders kanban columns by stage with cards, the weighted-value header,
    and the table; creating an opportunity calls POST; changing a card's stage calls PATCH.

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN C-CRM1)

1. **Pipeline math (weighted value, conversion) matches SQL** — the API never returns a figure
   that disagrees with an independent SQL computation. *(tests 1–4, 11)*
2. **Writes are RBAC-gated** — reps write only their own customers' opportunities; finance is
   read-only; the ERP is never written. *(tests 7, 8)*
3. **The dashboard placeholders are replaced with real data** — Otvorene prilike / Stopa
   konverzije / Najveće prilike render from `app.opportunity`, not a labeled "uskoro". *(test 11
   + the web test)*
4. **Stage history is append-only** — every stage transition is recorded; history is never
   mutated. *(tests 5, 6)*

## 8. Principles compliance

| # | Principle | How C-CRM1 honors it |
|---|---|---|
| 1 | AI computes no numbers | **No LLM in this track at all.** Value/probability are user-entered data; weighted value + conversion are SQL aggregates; tests assert API == SQL |
| 2 | Evidence on signals/tasks | N/A — opportunities are user data, not AI signals (no evidence/confidence envelope applies) |
| 3 | Confidence on conclusions | N/A — `probability` is a user-entered deal probability, not an AI confidence score; it is labeled as the user's input |
| 4 | No writes to source ERP | Opportunities are VALERI-native rows in `app.*`; the ERP is never touched |
| 5 | Read-only/staging | Unchanged; this adds VALERI-owned data entry, not ERP mutation |
| 6 | PII masking before LLM | N/A — no LLM call; customer names stay server-side as normal app data |
| 7 | Append-only logs | `opportunity_stage_history` is append-only (one row per transition, never updated/deleted) |
| 8 | Feedback loop | N/A for this track (no AI behaviour to learn from) |
| 9 | Register/visibility | Opportunities are user data, not AI output — no register tag. The UI clearly labels them as manually-entered pipeline (not AI analysis) |
| 10 | Approval/reversible self-config | N/A — CRUD is direct user action gated by RBAC, not AI self-configuration; no `app.decision` needed (decisions are for config/AI changes) |

## 9. Open questions (decide before implementation)

- **D1 — Dashboard: additive, not replace.** Keep the MVP recovery widgets (Kupci u padu,
  Izgubljeni artikli — Sales Recovery is still the core value) AND add the opportunity tiles
  (Otvorene prilike / Stopa konverzije / Najveće prilike). The api-spec's `lost_articles |
  opportunities` becomes "both present". OK, or replace the recovery widgets?
- **D2 — Stage default probabilities** (in `rule_config`): lead 0.10, qualified 0.30,
  proposal 0.50, negotiation 0.70, won 1.0, lost 0.0. An opportunity's explicit `probability`
  overrides its stage default. OK?
- **D3 — RBAC:** view = owner/admin/finance/sales_rep (rep → own customers); create/update =
  owner/admin/sales_rep (rep → own customers only); finance read-only. OK?
- **D4 — Conversion rate** = `won / (won + lost)` over closed opportunities (not won/total).
  OK?
- **D5 — Seed demo opportunities** (a dozen across stages on seeded customers/reps) so the
  screen + dashboard show real data and tests have fixtures. OK?
- **D6 — Kanban interaction:** a stage `<Select>` per card (calls PATCH) rather than
  drag-and-drop for the MVP. OK?
- **D7 — `app.activity` table created now but unused until C-CRM2** (it's in the same Phase-2
  DDL block; one migration per schema milestone). OK, or defer the table to C-CRM2?
