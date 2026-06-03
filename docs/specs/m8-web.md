# Spec — M8: Web app (owner command dashboard) + auth/RBAC

**Milestone:** M8 · **Builds on:** M7 (all dashboard data exists: metrics, signals, tasks, owner report) · **Status:** approved (D1–D8 OK'd by owner, 2026-06-03)

> Re-verified against the doc set updated 2026-06-03 (new CLAUDE.md conventions, architecture §8
> language policy, VALERI-IMPLEMENTATION-PLAN.md): the M8 milestone scope is unchanged. The
> Bosnian-first UI + EN toggle in this spec satisfies the §8 UI requirement; the per-user
> `preferred_language` column is covered by D8 below (the full LLM-side enforcement is milestone X2).

## 1. Objective

Give the owner the **Početna command dashboard** — the screen that replaces opening the ERP:
KPI row, revenue combo chart, "AI uvidi", at-risk + lost-articles tables, and the owner-report
summary, all rendered from SQL-computed numbers with **register + confidence + evidence on every
AI surface** — plus the screens around it (Zadaci, Artikli, Kupci, AI Report, Postavke), in
Bosnian with an EN toggle and light/dark parity. Behind it: **auth + RBAC**
(owner/sales_rep/finance/admin, `app.app_user`) so a rep sees only their own customers/tasks and
finance/rep views are properly gated. This is the **last MVP milestone** before the acceptance
suite.

## 2. Scope

### In scope — backend
1. **Migration 0009**: `app.app_user` (per data-model.md) + seed app users (owner, admin,
   finance, one login per seeded sales rep) with bcrypt-hashed dev passwords.
2. **`auth/` package**: bcrypt password hashing, JWT in an **httpOnly cookie** (D1), FastAPI
   dependencies `current_user()` / `require_roles(...)`, RBAC helpers (rep → customer scope).
3. **New API routers** (per api-spec.md): `auth`, `dashboard`, `metrics`, `customers`,
   `articles`, `signals`, `settings` (rule-config + users).
4. **Dashboard/metrics SQL** in `metrics/sql/dashboard.sql` + `metrics/dashboard.py` — KPI
   tiles, revenue trend, at-risk rows, lost-article rows, AI-insight rows. The only place the
   new numbers are produced.
5. **RBAC applied to existing routers** (tasks, reports, approvals, ingest) per the D2 matrix;
   existing tests get an authenticated-as-owner client fixture.

### In scope — frontend (per frontend-spec.md §7 build order)
6. Dependencies: `react-router`, `@tanstack/react-query`, `zustand`, `recharts`,
   `@fontsource/plus-jakarta-sans` (self-hosted font — on-prem, D6), `vitest` +
   `@testing-library/react` + `jsdom` (dev).
7. **Primitives** (`components/ui`): add badge, input, label, dialog, dropdown-menu, skeleton,
   progress, tabs, select, separator (shadcn, themed by existing M0 tokens).
8. **Widgets** (`components/widgets`): RegisterChip, ConfidenceLabel, RiskBadge,
   EvidenceExpander ("Prikaži brojke" → SQL rows + "brojke iz baze · SQL" footer), StatCard,
   Sparkline, ComboChart, SubStatStrip, AIInsightItem (with "Zanemari" → RuleCard),
   DataTable, OwnerReportSummary, RuleCard (preview mode, D3), DateRangePicker,
   CardState (skeleton/empty/error).
9. **Shell + routing**: TopBar (brand, GlobalSearch placeholder→chat in M9, NotificationsBell,
   ProfileMenu with logout + theme/language toggles), Sidebar (Početna, Kupci, Prilike
   [uskoro], Artikli, Zadaci, AI Report, Postavke) + QuickActions, AuthGuard, login page.
10. **Screens**: Početna (the §6 grid), Zadaci, Artikli (lost-articles centerpiece), Kupci
    (list + 360-lite detail), AI Report (Sedmični izvještaj tab live; Šta je VALERI naučio /
    Istrage tabs as labeled M10/M13 placeholders), Postavke (thresholds read-only sliders +
    users admin + LLM info), Prilike ("uskoro" state).
11. **i18n** (bs default + en), **light/dark**, formatters (KM money, dates, deltas, tabular).
12. **Frontend tests** (vitest): trust-critical widgets + dashboard assembly + formatters (D5).
13. **CI**: web job gains `npm test`.

### Out of scope (deferred)
- `POST /signals/{id}/dismiss` returning a learned-rule draft, `/rules/apply`, learned-rules
  screens → **M10** (the RuleCard in M8 is a preview; its "Primijeni" is disabled, D3).
- Chat / Ask VALERI (GlobalSearch routes there in M9), investigations UI (M13).
- Rep-activity widget, opportunities/pipeline (Phase 2) — labeled placeholders only.
- Real e-mail/password reset, user self-service; password rotation policy (M14 runbook).
- `/metrics/customer/{id}` beyond what the Kupci 360-lite needs.
- PDF/export of reports (Phase 2 Izvještaji).

## 3. Files

### Backend (apps/api)
```
migrations/versions/0009_app_user.py        app.app_user + seeded users (one migration, M8)
valeri_api/auth/__init__.py
valeri_api/auth/passwords.py                bcrypt hash/verify
valeri_api/auth/tokens.py                   JWT encode/decode (AUTH_SECRET, 12h expiry)
valeri_api/auth/models.py                   AppUser (schema="app")
valeri_api/auth/schemas.py                  LoginRequest, UserRead, UserCreate, UserUpdate
valeri_api/auth/deps.py                     current_user(), require_roles(), rep_customer_ids()
valeri_api/auth/seed_users.py               dev users for the seed/migration
valeri_api/metrics/dashboard.py             assemble_dashboard(), kpis(), revenue_trend(),
                                            at_risk_rows(), lost_article_rows(), insight_rows()
valeri_api/metrics/sql/dashboard.sql        named queries: kpis, revenue_trend, at_risk,
                                            lost_articles, insights, customer_360
valeri_api/api/auth.py                      POST /auth/login · POST /auth/logout · GET /auth/me
valeri_api/api/dashboard.py                 GET /dashboard
valeri_api/api/metrics.py                   GET /metrics/overview · /metrics/revenue-trend ·
                                            /metrics/customer/{id}
valeri_api/api/customers.py                 GET /customers · /customers/{id} · /customers/at-risk
valeri_api/api/articles.py                  GET /articles · /articles/{id} · /articles/lost
valeri_api/api/signals.py                   GET /signals · /signals/{id} · POST /signals/{id}/feedback
valeri_api/api/settings.py                  GET/PATCH /settings/rule-config · GET/POST/PATCH /settings/users
valeri_api/api/tasks.py        (edit)       + RBAC (owner/admin all, rep own, finance 403)
valeri_api/api/reports.py      (edit)       + RBAC (owner/admin/finance; rep 403)
valeri_api/api/approvals.py    (edit)       + RBAC (owner/admin only)
valeri_api/api/ingest.py       (edit)       + RBAC (admin only)
valeri_api/main.py             (edit)       mount new routers
valeri_api/config.py           (edit)       + auth_secret, auth_token_hours, dev_password flag
migrations/env.py              (edit)       register auth models
infra/.env.example, docker-compose.yml (edit)  + AUTH_SECRET
tests/test_auth.py                          login/logout/me, hashing, cookie behaviour
tests/test_rbac.py                          the D2 matrix end-to-end
tests/test_dashboard.py                     every dashboard number == independent SQL
tests/test_metrics_api.py                   overview/revenue-trend/customer == SQL
tests/test_customers_articles_api.py        lists/details/at-risk/lost + rep scoping
tests/conftest.py              (edit)       auth client fixtures (as_owner, as_rep, as_finance, as_admin)
tests/test_tasks.py, test_reports.py, test_approvals.py, test_ingest.py (edit)  use as_owner client
```

### Frontend (apps/web)
```
package.json (edit)                         + router/query/zustand/recharts/fontsource/vitest
vite.config.ts (edit)                       + vitest config
src/main.tsx (edit)                         providers: QueryClient → Router → Theme → I18n
src/routes.tsx                              route table + AuthGuard wiring
src/App.tsx (replace)                       router outlet
src/app/AppShell.tsx                        sidebar + topbar + <Outlet/> grid
src/app/TopBar.tsx                          brand, search placeholder, bell, profile menu
src/app/Sidebar.tsx                         nav + Brze akcije (Nova analiza, Novi zadatak, Pitaj VALERI [M9])
src/app/ThemeProvider.tsx                   .dark class, prefers-color-scheme initial, Zustand
src/app/AuthGuard.tsx                       /auth/me query → redirect /login
src/components/ui/…                         shadcn primitives (listed in §2.7)
src/components/widgets/RegisterChip.tsx     Analiza/Preporuka/Akcija pill
src/components/widgets/ConfidenceLabel.tsx  "pouzdanost: visoka/srednja/niska"
src/components/widgets/RiskBadge.tsx        Visok/Srednji/Nizak pill
src/components/widgets/EvidenceExpander.tsx "Prikaži brojke" → evidence table + SQL footer
src/components/widgets/StatCard.tsx         KPI card (label, value, delta, spark/progress)
src/components/widgets/Sparkline.tsx        Recharts mini line/bar
src/components/widgets/ComboChart.tsx       bars + line + dashed secondary, dual axis
src/components/widgets/SubStatStrip.tsx     YTD / avg-monthly cells
src/components/widgets/AIInsightItem.tsx    register + title + sub + confidence + Dokaz + Zanemari
src/components/widgets/DataTable.tsx        generic table w/ badge + numeric + link cells
src/components/widgets/OwnerReportSummary.tsx  mini metrics + tagged bullets
src/components/widgets/RuleCard.tsx         dismiss → preview card (Primijeni disabled until M10)
src/components/widgets/DateRangePicker.tsx  range presets (30d/90d/12m)
src/components/widgets/CardState.tsx        Skeleton / Empty ("Nema podataka…") / Error states
src/features/login/LoginPage.tsx            e-mail+password → POST /auth/login
src/features/dashboard/DashboardPage.tsx    the §6 grid; useDashboard()
src/features/tasks/TasksPage.tsx            task stack + status/feedback + filters
src/features/articles/ArticlesPage.tsx      articles list + lost-articles view (per customer)
src/features/customers/CustomersPage.tsx    list/search
src/features/customers/CustomerDetailPage.tsx  360-lite (metrics, trend, signals, tasks)
src/features/ai-report/AIReportPage.tsx     tabs: Sedmični izvještaj · Naučeno (M10) · Istrage (M13)
src/features/settings/SettingsPage.tsx      thresholds (read) + users (admin) + LLM info
src/features/opportunities/OpportunitiesPage.tsx  "uskoro" placeholder
src/lib/api/client.ts                       fetch wrapper (credentials:'include', error envelope)
src/lib/api/types.ts                        TS types mirroring API schemas
src/lib/api/queries.ts                      TanStack Query hooks per api group
src/lib/i18n/index.tsx                      I18nProvider + useT()
src/lib/i18n/bs.ts, en.ts                   string catalogs
src/lib/format/index.ts                     formatMoney("142.300 KM"), formatDate, formatDelta
src/store/theme.ts, ui.ts                   Zustand (no server data, no localStorage)
src/test/setup.ts + *.test.tsx              vitest + RTL tests (§6)
.github/workflows/ci.yml (edit)             web job: + npm test
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.app_user` | **create** (migration 0009) + seed users | exactly per data-model.md auth section; `sales_rep_id` links a rep login to its `core.sales_rep` row |
| `user_role` enum | **create** (0009) | owner/sales_rep/finance/admin |
| `core.*`, `app.signal`, `app.task`, `app.rule_config`, `app.owner_report`, `app.approval` | read | dashboard/metrics/screens; signal feedback writes `app.signal.status` + `audit.task_log`-style record? → **no**: M8 signal feedback reuses `app.task_feedback` via the signal's task (no new table) |
| `core.customer_rep` | read | RBAC: a rep's visible customers = current assignments |

One migration: `0009_app_user`. No other schema change.

## 5. API touchpoints (all per docs/api-spec.md; all RBAC-checked)

| Endpoint | Method | Roles | Response (shape) |
|---|---|---|---|
| `/auth/login` | POST | public | sets httpOnly cookie; `{user: {id,name,email,role}}` |
| `/auth/logout` | POST | any | clears cookie |
| `/auth/me` | GET | any authed | `{id,name,email,role,sales_rep_id}` |
| `/dashboard` | GET | owner/admin/finance | `{kpis[4], revenue_trend, ai_insights[], customers_at_risk[], lost_articles[], rep_activity:null, owner_report_summary, recently_suppressed:[]}` — every AI item carries the envelope (register/confidence/conf_band/evidence) |
| `/metrics/overview?range=` | GET | owner/admin/finance | 4 KPI cards `{key,label,value,delta,delta_unit,spark[],progress?}` |
| `/metrics/revenue-trend?range=12m` | GET | owner/admin/finance | `{months[],revenue[],secondary[],substats[]}` (secondary = same months last year) |
| `/metrics/customer/{id}` | GET | owner/admin/finance + owning rep | 360-lite `{turnover_trend[],last_order,avg_interval,basket[],risk}` |
| `/customers?query=&segment=&risk=` | GET | all (rep: own only) | paginated rows |
| `/customers/{id}` | GET | owner/admin/finance + owning rep | customer + contacts + metrics |
| `/customers/at-risk` | GET | all (rep: own only) | rows `{customer,last_order,value,baseline,risk_band,confidence,evidence}` from decline signals |
| `/articles?query=` , `/articles/{id}` | GET | all | article rows |
| `/articles/lost?customer_id=` | GET | all (rep: own customers) | lost-article signals + evidence (code-swap already excluded by M4 rule) |
| `/signals?rule=&conf=` , `/signals/{id}` | GET | all (rep: own) | signal + envelope |
| `/signals/{id}/feedback` | POST | all (rep: own) | `{useful, reason}` → recorded on the signal's task (`app.task_feedback` + `audit.task_log`) |
| `/settings/rule-config` | GET / PATCH | owner+admin read; admin write | thresholds list / updated values (PATCH writes `updated_by`) |
| `/settings/users` | GET / POST / PATCH | admin only | user management |
| existing `/tasks*` | (edit) | owner/admin all; rep own; finance 403 | unchanged shapes |
| existing `/reports/owner/*` | (edit) | owner/admin/finance; rep 403 | unchanged shapes |
| existing `/approvals*` | (edit) | owner/admin | unchanged shapes |
| existing `/ingest*` | (edit) | admin | unchanged shapes |

Numbers in every response are SQL values passed through; the API returns no LLM-computed figure.

## 6. Tests

### Backend (pytest; TDD on RBAC + dashboard numbers)
1. `test_auth.py::test_login_logout_me` — correct/wrong password, cookie set + httpOnly + cleared, /auth/me roundtrip, expired token → 401.
2. `test_auth.py::test_passwords_hashed` — no plaintext password anywhere in `app.app_user`.
3. `test_rbac.py::test_rep_cannot_load_finance_data` — rep → 403 on /dashboard, /metrics/*, /reports/owner/*, /approvals (the milestone acceptance).
4. `test_rbac.py::test_rep_sees_only_own` — /tasks, /customers, /customers/at-risk, /signals return only rows for the rep's customers (compared against SQL over `core.customer_rep`).
5. `test_rbac.py::test_finance_and_admin_gating` — finance → 403 on /tasks + /approvals + /settings/users; admin-only endpoints reject others; unauthenticated → 401 everywhere except /health + /auth/login.
6. `test_dashboard.py::test_dashboard_numbers_match_sql` — every KPI value/delta, trend point, at-risk row value/baseline, lost-article row, insight confidence equals an independent SQL computation (to the cent).
7. `test_dashboard.py::test_dashboard_envelope` — every ai_insight / at-risk / lost-article item carries register + confidence + conf_band + evidence.
8. `test_metrics_api.py` — overview KPIs == SQL; revenue-trend series == SQL by month; customer 360 == SQL.
9. `test_customers_articles_api.py` — list/detail/at-risk/lost shapes, pagination, 404 envelopes, rep scoping.
10. `test_settings_api.py` — rule-config GET/PATCH (PATCH writes updated_by; thresholds change detection behaviour), users CRUD admin-only.

### Frontend (vitest + React Testing Library)
11. `widgets.test.tsx` — RegisterChip renders text for each register; ConfidenceLabel renders "pouzdanost: …"; RiskBadge text; EvidenceExpander hides → reveals numbers + "brojke iz baze · SQL" footer on click.
12. `ai-insight.test.tsx` — AIInsightItem shows register chip + confidence + Dokaz; clicking "Zanemari" opens RuleCard (preview, Primijeni disabled with M10 note).
13. `stat-card.test.tsx` — StatCard renders value/delta/spark; delta colors up/down by sign.
14. `dashboard.test.tsx` — DashboardPage with mocked API: skeletons while loading → all 5 zones render; API error → error state; empty data → "Nema podataka" states.
15. `format.test.ts` — formatMoney("142.300 KM"), formatDelta("↑18%" / "↓3pp"), formatDate("dd.mm.yyyy.").
16. `i18n.test.tsx` — bs default; EN toggle swaps strings; no hard-coded Bosnian in components (strings come from the catalog).

## 7. Acceptance criteria (frontend-spec.md §8 + IMPLEMENTATION-PLAN M8)

1. **RBAC gating works** — a sales_rep login cannot load finance data (403 + UI "nemate pristup"), sees only its own tasks/customers (tests 3–5).
2. **The dashboard renders seeded data** with skeleton/empty/error states (tests 6, 14).
3. **Every AI surface shows register + confidence + evidence** (tests 7, 11, 12).
4. **Light/dark both correct**; initial from `prefers-color-scheme`; toggle persists in app state (no localStorage).
5. **Bosnian throughout with EN toggle** (test 16); diacritics correct; money/dates in local format.
6. Rep-activity + opportunities render as labeled Phase-2 placeholders ("uskoro"), never fake data.
7. AI-insight dismiss opens the RuleCard preview (apply lands in M10) (test 12).
8. Full pytest + vitest + eslint + builds green locally and in CI; principle-reviewer PASS.

## 8. Principles compliance

| Principle | M8 impact |
|---|---|
| 1. No LLM-computed numbers | The web app renders only API numbers; the new dashboard/metrics endpoints read SQL (metrics/sql/dashboard.sql); no LLM call is added anywhere in M8. Test 6 cross-checks every rendered number against SQL. |
| 2. Evidence everywhere | Every AI surface has EvidenceExpander showing the signal's evidence rows; /dashboard items carry evidence JSON. |
| 3. Confidence everywhere | ConfidenceLabel on every AI surface; conf_band passed through from signals. |
| 4./5. No ERP writes; read-only | M8 adds zero writes to `core.*`; only app.app_user (own table) + task_feedback + rule_config updates (governed, logged with updated_by). |
| 6. PII masking | No new LLM calls → no new masking surface. PII (customer names/contacts) stays inside the on-prem app/UI, which is allowed (humans see real names). |
| 7. Append-only logs | Signal feedback writes task_log events; settings changes record updated_by/updated_at; no audit rows are ever updated/deleted. |
| 8. Feedback loop | The UI now exposes feedback (task + signal) to reps/owner — the loop's input surface. |
| 9. Register tags | RegisterChip on every AI surface (insights, report bullets, tasks, approvals); statuses shown on approvals/actions. |
| 10. Approval gating | Approvals screen shows pending items (M7 API); nothing in the UI can send without the gate; self-config apply is disabled until M10. |
| Conventions | Typed everywhere (TS strict + Pydantic); thresholds shown from `app.rule_config`, never hard-coded in UI; **no localStorage/sessionStorage** (auth = httpOnly cookie, theme/lang = Zustand in-memory); secrets in env (AUTH_SECRET). |

## 9. Open questions (owner decisions before implementation)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | **Auth storage**: httpOnly session cookie (JWT inside) vs Bearer token in JS memory. Cookie survives refresh, is XSS-proof, and respects the no-localStorage rule; same-origin behind Caddy so CSRF exposure is minimal (SameSite=Lax + JSON-only API). | **httpOnly cookie** |
| **D2** | **RBAC matrix**: owner+admin = everything (admin additionally /settings/users + /ingest); finance = dashboard/metrics/reports/customers/articles, **no** tasks/approvals; sales_rep = own tasks/customers/signals/articles only, **no** dashboard/metrics/reports/approvals/settings. | as stated |
| **D3** | **RuleCard in M8**: preview-only (dismiss opens the card, shows reason input + scope chips, "Primijeni" disabled with "Samokonfiguracija stiže u M10") — no new dismiss endpoint, so M10 owns that contract cleanly. Alternative: a temporary dismiss endpoint now. | **preview-only** |
| **D4** | **Seed users / dev passwords**: `vlasnik@`, `admin@`, `finansije@` + one login per seeded rep, all with documented dev password `valeri-dev-2026`, forced change at pilot (M14 runbook). | as stated |
| **D5** | **Frontend test depth**: vitest + RTL for trust-critical widgets + dashboard assembly + formatters + i18n (16 tests total), not full E2E (Playwright deferred to M14 hardening). | as stated |
| **D6** | **Tailwind v4 note**: M0 pinned Tailwind v4 (CSS-first `@theme`, no `tailwind.config.ts`). frontend-spec §2 wording predates this; tokens stay in `src/index.css` exactly as M0 declared them. Same semantics, different file. | accept (no config file) |
| **D7** | **Dashboard date range**: DateRangePicker offers presets (30d / 90d / 12m) passed as `?range=` to /dashboard and /metrics/overview; default 30d. Custom from–to ranges deferred. | as stated |
| **D8** | **`app_user.preferred_language`** (architecture §8): since M8 creates the `app.app_user` table anyway, include the column now (`TEXT NOT NULL DEFAULT 'bs'`) so X2 doesn't need a second migration on the same table. M8 only stores it; LLM-side enforcement ("respond in {preferred_language}") is X2. | include the column now |

---
*After approval: Plan Mode (file-by-file implementation order), then implementation with TDD on RBAC + dashboard numbers, then principle-reviewer.*
