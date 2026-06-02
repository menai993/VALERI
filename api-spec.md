# VALERI — API surface (`docs/api-spec.md`)

FastAPI, JSON over HTTPS, SSE for streaming. All endpoints are RBAC-checked. This is the contract the frontend (`frontend-spec.md`) binds to. Paths are under `/api`.

## Conventions

- **Auth:** session cookie or `Authorization: Bearer <jwt>`. Roles: owner, sales_rep, finance, admin. A sales_rep only sees its own customers/tasks/data; finance is gated from rep-only views; admin manages settings/users.
- **Errors:** `{ "error": { "code": "string", "message": "human text", "details": {} } }` with proper HTTP status.
- **Pagination:** `?limit=&cursor=`; responses `{ "items": [...], "next_cursor": "..." }`.
- **Money/percent:** numbers as numerics; the client formats (KM, tabular). Dates ISO `YYYY-MM-DD`.
- **AI-response envelope** (every AI-derived item carries these, enforcing the principles):
  ```json
  { "register": "analiza|preporuka|akcija",
    "status": "draft|pending_approval|executed|null",
    "confidence": 0.0, "conf_band": "niska|srednja|visoka",
    "evidence": { "metric": "...", "value": 0, "baseline": 0, "delta_pct": 0,
                  "invoices": [], "lines": [], "period": {"from":"","to":""} },
    "payload": { } }
  ```
- **Numbers come from SQL**; the API never returns a figure computed by the LLM.

## Auth (M8)
- `POST /auth/login` → `{token, user}`
- `POST /auth/logout`
- `GET /auth/me` → current user + role

## Ingest (M2)
- `POST /ingest/import` (multipart CSV/Excel or a path) → `{import_id}`
- `GET /ingest/report/{import_id}` → data-quality report (dupes, renamed articles, code-swap candidates, missing segments, orphan lines)

## Dashboard & metrics (M3, dashboard payload assembled M8)
- `GET /dashboard` → the Početna payload in one call: `{ kpis, revenue_trend, ai_insights, customers_at_risk, lost_articles | opportunities, rep_activity?, owner_report_summary, recently_suppressed }`
- `GET /metrics/overview?from&to` → KPI cards: `ukupan_prihod`, `kupci_u_padu`, `izgubljeni_artikli`, `zadaci_danas` (+ MVP recovery tiles), each `{value, delta, delta_unit, spark[]}`
- `GET /metrics/revenue-trend?range=12m` → series for the combo chart `{months[], revenue[], secondary[], substats}`
- `GET /metrics/customer/{id}` → 360-lite metrics (turnover trend, last order, basket, interval, risk)

## Customers (M8) & Articles (M4 detection, M8 UI)
- `GET /customers?query=&segment=&risk=` ; `GET /customers/{id}` (360)
- `GET /customers/at-risk` → rows `{customer, last_activity, value, risk_band, confidence, evidence}`
- `GET /articles?query=&category=` ; `GET /articles/{id}`
- `GET /articles/lost?customer_id=` → lost-article signals (code-swap excluded), with evidence

## Signals & self-config dismissal (M4–M5, M10)
- `GET /signals?rule=&rep=&conf=` ; `GET /signals/{id}`
- `POST /signals/{id}/feedback` `{useful, reason}`
- `POST /signals/{id}/dismiss` `{reason_text}` → returns a **proposed rule change** (does not yet apply): `{learned_rule_draft, scope, description, effect_estimate, interpretation_confidence, requires_confirm}`

## Tasks (M5)
- `GET /tasks?assignee=&status=` ; `GET /tasks/{id}`
- `POST /tasks/{id}/status` `{status}`
- `POST /tasks/{id}/feedback` `{useful, reason}`

## Owner report (M7)
- `GET /reports/owner/weekly` → full report (sections, each register-tagged, numbers from SQL)
- `GET /reports/owner/summary` → the dashboard summary block (mini metrics + narrative bullets)

## Approvals (M7)
- `GET /approvals?status=pending_approval`
- `POST /approvals/{id}/decide` `{decision: "approved|rejected|deferred", note?}` → writes `app.decision`

## Self-configuration & learned rules (M10–M11)
- `POST /rules/apply` `{learned_rule_draft}` → applies (graduated autonomy); writes `app.learned_rule` + reversible `app.decision`; returns `{learned_rule, decision}`
- `GET /learned-rules` → list with origin, effect (suppressed count), status, autonomy
- `GET /learned-rules/{id}` → detail + `suppression_hit` items (what it hid)
- `PATCH /learned-rules/{id}/scope` `{scope}` → edit scope (writes a decision)
- `POST /learned-rules/{id}/undo` → revert (writes a decision)
- `GET /audit/decisions?kind=` → the decision feed ("show the decision on the platform")

## Chat — Ask VALERI (M9)
- `POST /chat/sessions` → `{session_id}`
- `POST /chat/sessions/{id}/messages` `{text}` → **SSE stream** of `{type: "token"|"tool_call"|"register"|"card"|"done", ...}`; tool calls run server-side via the safe catalog; the final message carries the AI-response envelope and any inline cards (e.g. a self-config rule card or a task draft)
- `GET /chat/sessions/{id}` → history

## Investigations (M13)
- `POST /investigations` `{question, signal_id?}` → `{investigation_id}` (async)
- `GET /investigations?status=` ; `GET /investigations/{id}` → report + `investigation_step` trace
- `POST /investigations/{id}/resume` `{decision}` → satisfies a HITL interrupt and resumes
- SSE `GET /investigations/{id}/stream` → progress events while running

## Reps & activity (Phase 2)
- `GET /reps/activity?date=` → per-rep activity + completion (needs `app.activity`)

## Opportunities — CRM (Phase 2, optional)
- `GET /opportunities?stage=` ; `POST /opportunities` ; `PATCH /opportunities/{id}` ; `GET /opportunities/pipeline` (kanban + weighted value)

## Settings (M8 base; M12 LLM)
- `GET/PATCH /settings/rule-config` → thresholds (`app.rule_config`)
- `GET/PATCH /settings/autonomy` → the auto-vs-confirm boundary
- `GET/PATCH /settings/llm` → tier model IDs, escalation threshold, provider (hosted Claude), masking on/off (default on, cannot be disabled in prod)
- `GET/POST/PATCH /settings/users` (admin) → RBAC user management
