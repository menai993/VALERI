# VALERI — UI design spec v2 (command-dashboard direction)

**Supersedes v1.** Redesigned to the dense owner-dashboard you preferred (the mock labeled "Metarium" = VALERI). This is the single source of truth for the frontend; P8 builds to it. It keeps VALERI's non-negotiable discipline (register tags, confidence, evidence, self-configuration, approval) layered onto the richer dashboard look.

---

## 1. Direction

A clean, dense, **professional owner command dashboard**: information-rich but calm, white cards on a soft gray field, one blue accent, semantic risk/trend colors, and gentle elevation. Owner-first — the owner wanted to *see the numbers*, so we lead with KPIs, a trend chart, AI insights, and decision tables on one screen. Still calm, never loud: restrained type, generous gutters, soft shadows instead of hard borders, one accent per state.

This direction changes two things from v1: density goes **up** (multi-widget grid, KPI row, charts, tables), and **soft elevation is now allowed** (subtle card shadows, as in the mock).

---

## 2. Scope honesty — which widgets are MVP vs later

The mock is more CRM/pipeline-oriented than the written scope. Build the layout now, but wire each widget to the right phase. Do **not** ship widgets that imply data we don't have.

| Widget | Phase | How to wire it (read-only MVP) |
|---|---|---|
| Ukupan prihod, revenue trend, YTD, avg monthly | **MVP** | SQL metrics over invoices |
| Zadaci za danas | **MVP** | signal→task pipeline |
| Top kupci u riziku | **MVP** | declining-customer detection → risk badge (Visok/Srednji/Nizak) |
| AI insights: declining customers, lost articles, cross-sell | **MVP** | the real Sales-Recovery signals, each with register + confidence + evidence |
| AI Owner Report sažetak + narrative | **MVP** | the weekly owner report |
| Aktivnosti komercijalista | **Phase 2** | needs activity logging; show as "uskoro" until then |
| Offers not sent 10+ days | **Phase 2** | offers/follow-up module |
| Otvorene prilike, Stopa konverzije, Najveće prilike (pipeline) | **Phase 2 (CRM)** | needs an opportunity/deal model; render as a clearly-labeled placeholder or hide |
| Forecast / prihod-vs-plan, opportunity sources, avg opportunity value | **Phase 2 (CRM)** | needs targets + deal model |
| Nova prilika / Novi kupac (data entry) | **Phase 2** | conflicts with read-only MVP; in MVP, "Brze akcije" = Nova analiza, Novi zadatak, Pitaj VALERI only |

**MVP recovery-equivalents** for the pipeline tiles (so the screen is full and honest in Phase 1): replace "Otvorene prilike / Stopa konverzije / Pipeline" with **Kupci u padu**, **Izgubljeni artikli**, **Vrijednost za povrat** (recoverable revenue), and a **win-back / reaktivacija** rate.

---

## 3. Design tokens

### Typography
- **UI font:** `Plus Jakarta Sans` (Google Fonts) — clean, modern, slightly geometric; matches the mock. Fallback `'Plus Jakarta Sans', ui-sans-serif, system-ui, sans-serif`.
- **Numbers:** `font-variant-numeric: tabular-nums` everywhere money/percentages appear (KPI values, tables).
- **Weights:** 400 / 500 / 600; 700 only for big KPI values.
- **Scale (px/lh):** page title 26/1.2 · section title 17/1.3 · card title 15/1.35 · KPI value 30/1.1 (700) · body 14/1.55 · small 13/1.45 · micro 11.5/1.4. Sentence case.

### Color tokens (light → dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f4f6f9` | `#0e1217` | page field |
| `--surface` | `#ffffff` | `#161b22` | cards |
| `--surface-2` | `#f6f8fb` | `#1b2129` | inner panels, sub-stat strips |
| `--border` | `#eaeef3` | `#242c35` | hairlines |
| `--text` | `#1f2733` | `#e8ecf1` | primary |
| `--text-2` | `#5e6b7a` | `#9aa6b2` | secondary |
| `--text-3` | `#97a1ad` | `#6b7681` | meta/labels |
| `--primary` | `#2f6bed` | `#5b8def` | accent: active nav, links, primary buttons, chart line |
| `--primary-soft` | `#eaf1fe` | `#172643` | icon chips, primary tints |
| `--up` | `#16a34a` | `#54c882` | positive deltas ↑ |
| `--down` / `--risk-high` | `#e5484d` | `#f0716f` | negative deltas ↓, Visok |
| `--risk-mid` | `#ef8f1c` | `#eaa64b` | Srednji |
| `--risk-low` | `#16a34a` | `#54c882` | Nizak |

Risk/trend **badge** backgrounds use a tint of the same hue: Visok `#fdecec/#c8302f`, Srednji `#fdf1e0/#b4620a`, Nizak `#e8f6ec/#1d8a45` (light).

Register / semantic chips (bg / text), light:

| Register | bg / text |
|---|---|
| Analiza (info) | `#eaf1fe` / `#1a4f8a` |
| Preporuka (warning) | `#fdf1e0` / `#9a5a0c` |
| Akcija (success) | `#e8f6ec` / `#1d7a3e` |

Chart palette: revenue bars `#bcd4fb`, revenue line `--primary`, opportunities/secondary dashed `#e5484d`, gridlines `--border`, axis labels `--text-3`.

### Shape, elevation, spacing, motion
- **Radius:** cards `--r-lg: 16px`; inner panels/inputs `--r-md: 10px`; chips/badges `--r-sm: 7px` (pill for status).
- **Elevation (soft, allowed now):** `--shadow-sm: 0 1px 2px rgba(16,24,40,.05)`, `--shadow: 0 1px 3px rgba(16,24,40,.07), 0 1px 2px rgba(16,24,40,.04)`. Cards use `--shadow`; borders stay hairline.
- **Spacing:** page padding 24px; grid gap 16px; card padding `18px 20px`; internal gaps 8/12px.
- **Motion:** one staggered fade-up on load; hover 150ms; chart draws once on mount. Nothing decorative.

---

## 4. VALERI discipline, layered onto the dashboard

The mock omits these; VALERI requires them. How they appear in this denser UI:

- **Register chip on every AI surface.** Each "AI uvidi za Vas" item, each AI Owner Report bullet, and any recommendation carries a small Analiza / Preporuka / Akcija chip in its top-left.
- **Confidence on every conclusion.** Risk rows and AI insights show `pouzdanost: visoka/srednja/niska` (micro text, `--text-3`).
- **Evidence one tap away.** AI insights and risk rows expose a "Dokaz" / "Prikaži brojke" link revealing the SQL rows; a micro footer notes "brojke iz baze · SQL".
- **Self-configuration is visible & reversible.** Every AI insight has a quiet "Zanemari" affordance → opens the rule card (scope chips + predicted effect + Primijeni/Promijeni opseg). Learned rules live in **AI Report → Šta je VALERI naučio**, with Undo. The auditor surfaces drifted suppressions as a `Na provjeri` card.
- **Approval gates.** Anything customer-facing (a drafted offer/message) is `Akcija · Čeka odobrenje` until approved.

---

## 5. Components (anatomy)

**Top bar** — height ~64px, `--surface`, bottom hairline. Left: brand wordmark. Then a **company switcher** (building icon + name + chevron). Center: **global search** ("Pretražite kupce, prilike, artikle…", `⌘K`) — this is also the **Ask VALERI** entry (typing a question opens chat). Right: **notifications** bell with count badge; **profile** (avatar + name + role + chevron).

**Sidebar** — width ~212px, `--surface`, right hairline. Sections (icon 18px + label 14px), active = `--primary-soft` bg + `--primary` text + medium weight. Items: Početna, Kupci, Prilike, Artikli, Zadaci, AI Report, Izvještaji (expandable ▸), Postavke. Bottom block **"Brze akcije"** separated by a hairline: Nova analiza, Novi zadatak, Pitaj VALERI (+ Nova prilika / Novi kupac in Phase 2). On mobile → bottom tab bar (5 items) + "više".

**Date-range picker** — top-right of the page header; calendar icon + range label + chevron; opens a range popover.

**KPI / stat card** — `--surface`, `--r-lg`, `--shadow`, padding `18px 20px`. Top row: label (14px `--text-2`) + a soft round icon chip (`--primary-soft`). Big value (30px/700, tabular) + inline delta (`↑18%` `--up` / `↓3pp` `--down`) + "vs. prethodni period" (micro). Footer: a **sparkline** (line or bars) or a **progress bar** (for Zadaci: "23 od 31", "74% završeno").

**Combo chart card** — title + range dropdown + legend (Prihod (KM) `--primary`, secondary dashed `--down`). Dual-axis chart: revenue bars (`#bcd4fb`) + line (`--primary`), secondary dashed line. Below, a **sub-stat strip**: 3–4 cells (YTD prihod, prosj. mjesečni, … , each value + green delta) on `--surface-2`, divided by hairlines.

**AI insight item** — list row in the "AI uvidi za Vas" card: soft icon chip + **register chip** + title (15px/500) + sub line (value/context, `--text-2`) + a `--primary` action link ("Pregledajte … →"). Hover reveals "Zanemari" (→ self-config) and "Dokaz". Confidence as micro text.

**Data table** — header row (12px `--text-3`, hairline under), body rows with hairline dividers, generous row height (~48px). Cells: primary text (15px/500) + secondary meta. Right-aligned numeric columns (tabular). A **status/risk badge** column. Footer link "Pogledajte sve … →". Used for Top kupci u riziku and Najveće prilike.

**Risk badge** — pill, `--r-sm`, tinted bg + hue text: Visok / Srednji / Nizak.

**Probability cell** — percentage (tabular) optionally with a 3px mini bar in `--primary`.

**Rep activity row** — avatar + name; a small count chip (e.g. "4"); activity summary text ("2 sastanka, 1 ponuda, 1 poziv"); a right-aligned **completion progress** (label "% " + thin bar). Phase 2.

**AI Owner Report summary** — a 4-up of mini metric cards (soft icon chip on top, label, value 24px/700, delta) + a **narrative list**: bullet rows each with an icon and an insight sentence, tagged Analiza/Preporuka. Header link "Pogledajte cijeli izvještaj →".

**Buttons** — default: `--surface`, hairline, `--r-md`, hover `--surface-2`. Primary: `--primary` bg, white text. Positive ("Odobri", "Primijeni"): success tokens. Quick-action items: ghost rows with a leading round + icon.

**States** — every card has explicit loading (skeleton), empty ("Nema podataka za ovaj period"), and error states; AI cards show a subtle "VALERI analizira…" while computing.

---

## 6. Layout & grid

12-column fluid grid, 16px gutters, page max ~1180px inside the sidebar.

- Row 1: page title + subtitle (left), date-range picker (right).
- Row 2: **KPI row** — 4 cards (`repeat(auto-fit, minmax(230px,1fr))`).
- Row 3: **8/4 split** — combo chart (8) + AI uvidi (4).
- Row 4: **6/6 split** — Top kupci u riziku + Najveće prilike (Phase 2: swap "Najveće prilike" for "Izgubljeni artikli" in MVP).
- Row 5: **6/6 split** — Aktivnosti komercijalista (Phase 2) + AI Owner Report sažetak.

Responsive: ≥1100px as above; 720–1100px the 8/4 and 6/6 splits stack to single column in priority order (KPIs → AI uvidi → risk → owner report); ≤720px sidebar→bottom bar, all cards full-width, KPIs 2-up then 1-up.

---

## 7. Screens

1. **Početna (dashboard)** — the layout in §6. The flagship; AI surfaces carry register/confidence/evidence; insights are dismissible into the self-config loop.
2. **Kupci** — list/search of customers; a customer detail (360-lite): turnover trend, last order, basket, risk, the signals/tasks for that customer, contacts.
3. **Prilike (Phase 2 / CRM)** — opportunity pipeline (kanban by stage + table); until Phase 2, the nav item shows a "uskoro" state.
4. **Artikli** — articles/categories; **lost-article detection** surfaced here (the MVP centerpiece the mock omits): per-customer lost articles with code-swap handling and evidence.
5. **Zadaci** — prioritized task stack (mobile-first): title, reason+evidence, proposed action, due date, done/feedback; filters by rep/type/confidence.
6. **AI Report** — the weekly **owner report** (full), plus **Šta je VALERI naučio** (learned rules + Undo + auditor flags) and **Istrage** (investigation list + report with trace).
7. **Izvještaji** — saved/exportable reports (revenue, recovery, rep activity).
8. **Pitaj VALERI (chat)** — opened from the search bar or a nav entry; streamed thread with register chips, evidence expanders, inline self-config rule cards, "Istraži" handoff.
9. **Postavke** — rule thresholds (`app.rule_config`), auto-vs-confirm boundary, model/provider toggle, language, users/RBAC.

Nav mapping to the mock: Početna · Kupci · Prilike · Artikli · Zadaci · AI Report · Izvještaji ▸ · Postavke, with Ask VALERI reachable via the search bar.

---

## 8. Accessibility, i18n, numbers

- WCAG AA contrast in both modes; visible focus rings; full keyboard nav; badges/chips always carry text, never color alone.
- Bosnian default with full diacritics (č, ć, ž, š, đ); i18n layer with EN toggle. Dates `d. mmm yyyy.` / `dd.mm.yyyy.`; money "142.300 KM" with thousands separators and tabular figures; deltas as `↑18%` / `↓3pp`.
- Initial theme from `prefers-color-scheme`; manual toggle persists in app state (no localStorage).

---

## 9. How P8 consumes this

- Stack (from the plan): React + TypeScript + Vite + Tailwind + shadcn/ui + TanStack Query + Zustand; **Recharts** (or Chart.js) for the combo/sparkline charts.
- Map §3 tokens into the Tailwind theme (`theme.extend.colors` + CSS vars on `:root`/`.dark`); components reference semantic tokens, never raw hex; elevation via the shadow tokens.
- Build order: (1) tokens + primitives (chip, badge, button, card, icon-chip); (2) data widgets (KPI card, combo chart, sub-stat strip, data table, AI insight item, rep row, owner-report summary); (3) shell (top bar + company switcher + global search/Ask entry + sidebar + quick actions); (4) assemble Početna; (5) remaining screens.
- Treat the uploaded dashboard image as the visual target for Početna; honor the §2 scope mapping so Phase-2 widgets render as labeled placeholders rather than fake data.
- Keep `frontend-design` rules in force: distinctive-but-calm, semantic tokens, light/dark parity, no localStorage.
