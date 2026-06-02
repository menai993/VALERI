# VALERI — Frontend build spec (`docs/frontend-spec.md`)

How to build the UI. Pair with `ui-design.md` (visual tokens, component anatomy) and `api-spec.md` (data). Target look: the dense owner command dashboard.

## 1. Stack & setup
React 18 + TypeScript + Vite + Tailwind CSS + **shadcn/ui** + **TanStack Query** (server state) + **Zustand** (theme/i18n/UI state) + **Recharts** (charts) + **React Router**. No `localStorage`. Pin latest stable; commit lockfile.

## 2. Tailwind theme (from `ui-design.md` §3)
Define CSS variables on `:root` and `.dark` for every token (`--bg, --surface, --surface-2, --border, --text, --text-2, --text-3, --primary, --primary-soft, --up, --down/--risk-high, --risk-mid, --risk-low`, register bg/text, chart palette, radii, shadows). Map them in `tailwind.config.ts` `theme.extend.colors/borderRadius/boxShadow` so components use semantic classes (`bg-surface`, `text-2`, `rounded-lg`, `shadow-card`), never raw hex. Font family `Plus Jakarta Sans`; enable tabular numerals via a `.tnum` utility. Light/dark via a `.dark` class on `<html>`, initial from `prefers-color-scheme`, toggled in Zustand.

## 3. Project structure
```
apps/web/src/
  app/                 App shell (TopBar, Sidebar, QuickActions, theme provider, router outlet)
  components/ui/        primitives (shadcn-based): Button, Card, Chip, Badge, IconChip, Input, Dropdown, Dialog, Skeleton, Progress, Tabs
  components/widgets/   VALERI widgets (below)
  features/             one folder per screen: dashboard/, customers/, articles/, tasks/, ai-report/, chat/, learned-rules/, investigations/, settings/, opportunities/(phase2)
  lib/api/              typed fetch client + TanStack Query hooks (one per api-spec group) + SSE helpers
  lib/i18n/             bs (default) + en strings; formatMoney(KM), formatDate, formatDelta
  lib/format/           number/percent/date helpers (tabular)
  store/                Zustand: theme, language, ui (sidebar, modals)
  routes.tsx
```

## 4. Component inventory (props → API binding)

Primitives (`components/ui`): standard shadcn components themed to the tokens.

VALERI widgets (`components/widgets`):
- **RegisterChip** `{register}` — Analiza/Preporuka/Akcija pill (info/warning/success tokens). On every AI surface.
- **ConfidenceLabel** `{band}` — "pouzdanost: visoka/srednja/niska".
- **RiskBadge** `{band}` — Visok/Srednji/Nizak pill (high/mid/low tokens).
- **EvidenceExpander** `{evidence}` — "Prikaži brojke/Dokaz" link → reveals SQL rows/numbers (tabular) + "brojke iz baze · SQL" footer.
- **StatCard** `{label, value, delta, deltaUnit, spark?, progress?}` — KPI card; ← `GET /metrics/overview` / `/dashboard.kpis`.
- **Sparkline** `{data, type:'line'|'bar'}` — Recharts mini chart.
- **ComboChart** `{months, revenue, secondary, legend}` — dual-axis bars+line+dashed line; ← `GET /metrics/revenue-trend`.
- **SubStatStrip** `{stats[]}` — under the chart (YTD etc.).
- **AIInsightItem** `{icon, register, title, sub, actionHref, confidence, evidence, onDismiss}` — list row in "AI uvidi"; dismiss → opens RuleCard; ← `/dashboard.ai_insights`.
- **DataTable** `{columns, rows, footerHref}` — generic table with badge/numeric/link cells; used by Customers-at-risk, Lost-articles, Opportunities.
- **RepActivityRow** `{rep, count, summary, completion}` — Phase 2; ← `GET /reps/activity`.
- **OwnerReportSummary** `{metrics[], bullets[]}` — mini metric cards + narrative bullets (each tagged); ← `GET /reports/owner/summary`.
- **RuleCard** `{draft, scope, description, effect, interpretationConfidence, requiresConfirm, onApply, onEditScope, onCancel}` — the self-config card with editable scope chips; ← `POST /signals/{id}/dismiss` then `POST /rules/apply`.
- **ApprovalCard** `{item, onApprove, onReject, onDefer}` — ← `/approvals`.
- **DateRangePicker** `{range, onChange}`.
- **CompanySwitcher**, **GlobalSearch** (also the Ask-VALERI entry: submitting a question routes to chat), **NotificationsBell**, **ProfileMenu**.
- **Sidebar** + **QuickActions** (MVP: Nova analiza, Novi zadatak, Pitaj VALERI).
- **ChatThread** `{messages}`, **ChatMessage** (renders register chip, narrative, result list, EvidenceExpander, inline RuleCard/task-draft), **ChatInput** (SSE send).
- **InvestigationReport** `{report, trace}` + **InvestigationList**.
- **LearnedRuleCard** `{rule, onUndo, onEditScope}` (origin, effect, status, Na provjeri flag).

## 5. Screen specs

**Početna (dashboard)** — `features/dashboard`. Layout = `ui-design.md` §6 grid: header (title + DateRangePicker) → KPI row (4 StatCards) → 8/4 (ComboChart + SubStatStrip | AI uvidi list of AIInsightItem) → 6/6 (Customers-at-risk DataTable | Lost-articles DataTable — MVP; Opportunities in Phase 2) → 6/6 (RepActivity (Phase 2 placeholder) | OwnerReportSummary). One `useDashboard()` query hydrates it; each card shows skeleton/empty/error. AI surfaces carry RegisterChip + ConfidenceLabel + EvidenceExpander; AIInsightItem dismiss opens RuleCard.

**Kupci** — list/search (DataTable) + customer detail (360-lite): metrics, turnover trend (Sparkline/ComboChart), basket, risk, the customer's signals/tasks.

**Artikli** — articles/categories list + **lost-article view** per customer (the MVP centerpiece): rows with code-swap handling and EvidenceExpander; ← `GET /articles/lost`.

**Zadaci** — mobile-first task stack: title, reason + EvidenceExpander, proposed action, due date, status control + feedback; filters (rep/type/confidence); ← `/tasks`.

**AI Report** — tabs: **Sedmični izvještaj** (full owner report), **Šta je VALERI naučio** (LearnedRuleCard list + decision feed + auditor "Na provjeri"), **Istrage** (InvestigationList + InvestigationReport with trace).

**Pitaj VALERI (chat)** — opened from GlobalSearch or nav; ChatThread + ChatInput; SSE streaming; inline cards.

**Postavke** — threshold sliders (rule-config), auto-vs-confirm boundary, LLM settings (tiers/escalation; masking shown as locked-on), language, users (admin).

**Prilike (Phase 2)** — opportunity pipeline (kanban + DataTable + weighted value); until then, a labeled "uskoro" state.

## 6. State & data
- TanStack Query per api group; query keys `['dashboard']`, `['signals',filters]`, `['tasks',filters]`, `['learnedRules']`, etc.; mutations invalidate the right keys (e.g. applying a rule invalidates `['signals']` + `['learnedRules']` + `['decisions']`).
- **SSE:** a helper opens `POST /chat/.../messages` and `GET /investigations/{id}/stream`, dispatching `token/tool_call/register/card/done` into the thread / progress UI.
- Zustand holds theme, language, and ephemeral UI (sidebar open, open dialogs). No server data in Zustand.
- i18n: all strings via `lib/i18n` (bs default, en toggle); never hard-code Bosnian in components.

## 7. Build order (for P8 / the web milestone)
1. Tailwind tokens + primitives (Chip/RegisterChip, Badge/RiskBadge, Button, Card, IconChip, Skeleton, Progress).
2. Data widgets (StatCard, Sparkline, ComboChart, SubStatStrip, DataTable, AIInsightItem, EvidenceExpander, ConfidenceLabel, OwnerReportSummary, RuleCard).
3. Shell (TopBar + CompanySwitcher + GlobalSearch/Ask entry + NotificationsBell + ProfileMenu + Sidebar + QuickActions) and routing + auth guard.
4. Assemble **Početna** to match the reference; wire `useDashboard()`.
5. Remaining screens in order: Zadaci, Artikli (lost articles), Kupci, AI Report (report → learned-rules → investigations), Chat, Postavke.
6. Light/dark parity pass + accessibility pass (focus rings, keyboard nav, AA contrast, chips carry text).

## 8. Acceptance (web)
RBAC gating works (a rep can't load finance data); the dashboard renders seeded data with skeleton/empty/error states; every AI surface shows register + confidence + evidence; a signal dismissal opens the RuleCard and applying it reflects in "Šta je VALERI naučio"; light/dark both correct; Bosnian strings throughout with EN toggle.
