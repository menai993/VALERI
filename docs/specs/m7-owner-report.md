# Spec — M7: Owner report + approval workflow

**Milestone:** M7 · **Builds on:** M6 (LLM narration layer exists) · **Status:** implemented (commit 96da94c; 13/13 tests green, principle-reviewer PASS, 2026-06-02)

## 1. Objective

Give the owner **weekly, self-delivered value**: a scheduled weekly report whose every number
is a SQL aggregate (top declines, lost articles, sleeping customers, task stats, and a
"recently suppressed" placeholder filled in M11), narrated in Bosnian by the LLM through the
M6 masking/number-contract pipeline, with **every block register-tagged** — plus the
**approval workflow** that draws the product's most important behavioural line: internal
actions (creating tasks, generating/storing the report) run automatically; anything
customer-facing exists only as an **approval-gated draft** that structurally cannot be sent
without an explicit human decision.

## 2. Scope

### In scope
1. **Migration 0008**: `appr_status` enum + `app.approval` (per data-model.md, + D2 payload
   column) + `app.owner_report` (D1 — the stored weekly snapshot).
2. **`reports/` package**: SQL aggregation queries (one place, reviewable), report builder
   (aggregates → masked → LLM narrative per section → register tags → stored snapshot),
   summary block extraction.
3. **`approvals/` package**: approval lifecycle (draft → pending_approval →
   approved/rejected → sent), the **gate** (`send_customer_message()` raises without an
   approved row), draft generation for customer-facing win-back/offer messages (LLM, masked,
   attached to the related task).
4. **Scheduler**: weekly job = scan → tasks → **report generation** (after the Sunday scan).
5. **API**: `GET /api/reports/owner/weekly`, `GET /api/reports/owner/summary`,
   `GET /api/approvals?status=`, `POST /api/approvals/{id}/decide` — per docs/api-spec.md.
6. Tests: aggregates == SQL, register tags everywhere, the approval gate, auto-run internal
   actions, full approval lifecycle, API behaviour.

### Out of scope (deferred)
- Real message transport (e-mail/SMS/Viber). M7's "send" is a gated state transition
  (`approved` → `sent`); the transport integration is a Phase-2/pilot decision.
- "Recently suppressed" content (M11 — the section ships as an empty, labeled placeholder).
- `app.decision` rows for approvals (M10 introduces the decision log; M7 records decisions
  on the approval row itself: decided_by/decided_at/status).
- Report UI (M8 AI Report screen), `/dashboard` endpoint (M8).
- Report PDF/export (Phase 2 Izvještaji screen).

## 3. Files

```
apps/api/valeri_api/reports/
  __init__.py
  sql/
    weekly_aggregates.sql   the report's numbers: KPIs (week revenue vs prior week), top-5
                            declines, top-5 lost articles, sleeping customers, task stats —
                            one SQL file, all aggregates
  builder.py                build_weekly_report(session, week_end, client=None) →
                            aggregates (SQL) → per-section masked payload → LLM narrative
                            (M6 narration layer, report schema) → register per section →
                            store app.owner_report row; template fallback per section
  schemas.py                ReportSection {title, register, narrative, data}, OwnerReport,
                            OwnerReportSummary, ReportSectionNarrative (LLM output schema)

apps/api/valeri_api/approvals/
  __init__.py
  models.py                 Approval (schema="app")
  schemas.py                ApprovalRead, ApprovalDecision, DraftMessage
  workflow.py               create_draft(task_id, kind, payload) · submit_for_approval(id) ·
                            decide(id, decision, decided_by) · send_customer_message(id) —
                            THE GATE: raises ApprovalRequired unless status == 'approved' ·
                            generate_customer_drafts(session, client) — win-back/offer drafts
                            for decline/sleeping tasks (LLM, masked)

apps/api/valeri_api/api/
  reports.py                GET /reports/owner/weekly · GET /reports/owner/summary
  approvals.py              GET /approvals · POST /approvals/{id}/decide

apps/api/valeri_api/scanner/scheduler.py   (edit) weekly job also generates the report
apps/api/valeri_api/main.py                (edit) mount reports + approvals routers

apps/api/migrations/versions/
  0008_report_approvals.py  appr_status enum + app.approval (+payload) + app.owner_report

apps/api/tests/
  test_reports.py           aggregates == SQL, registers, narrative contract, summary, API
  test_approvals.py         the gate, lifecycle, auto-run internal actions, drafts, API
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.approval` | **create** (0008) + lifecycle writes | per data-model.md **+ `payload JSONB`** (D2 — holds the draft text/channel being approved) |
| `app.owner_report` | **create** (0008) + weekly insert | **D1 — addition to the data model**: `id, week_start, week_end, generated_at, payload JSONB` (the full report snapshot: sections, aggregates, narratives, registers) |
| `appr_status` enum | **create** (0008) | draft/pending_approval/approved/rejected/sent |
| `app.signal`, `app.task`, `core.*`, `audit.ai_log` | read / narration logging | aggregates come from signals/tasks/invoices; LLM calls logged as in M6 |

- **One migration**: `0008_report_approvals`. `docs/data-model.md` updated for D1/D2.

## 5. API touchpoints (per docs/api-spec.md, M7)

| Endpoint | Request | Response |
|---|---|---|
| `GET /api/reports/owner/weekly` | `?week_end=YYYY-MM-DD?` (default: latest stored) | the full stored report: `{week_start, week_end, generated_at, sections: [{title, register, narrative, data}], recently_suppressed: []}` |
| `GET /api/reports/owner/summary` | — | the dashboard block: `{metrics: [{label, value, register}], bullets: [{text, register}]}` extracted from the latest report |
| `GET /api/approvals?status=pending_approval` | — | `{items: [ApprovalRead]}` (id, task_id, kind, status, payload, decided_by, decided_at) |
| `POST /api/approvals/{id}/decide` | `{"decision": "approved"\|"rejected"\|"deferred", "note"?}` | updated ApprovalRead; 404/409 envelopes |

Every report section and approval item carries its register tag; numbers in responses are
SQL values passed through (never LLM-computed).

## 6. Key design decisions (flagged for review)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **`app.owner_report` table** (not in data-model.md) stores each weekly report as an immutable snapshot | The weekly report must be a reproducible artifact ("what did VALERI tell me last Monday?"), not a live query that changes under the owner's feet; also avoids re-paying LLM narration on every GET. data-model.md gets updated. |
| **D2** | **`app.approval.payload JSONB`** column addition | An approval without the thing being approved (the draft message text, target customer, channel) is not auditable or reviewable. data-model.md gets updated. |
| **D3** | **Customer-facing drafts in M7** = win-back / offer message drafts generated (LLM, masked, number-contract-checked) for decline + sleeping tasks during report generation; attached to their task via `approval.task_id`, born as `status='draft'` | This makes the approval gate real (there is something to approve) while the actual transport stays out of scope. |
| **D4** | **The gate is structural**: `send_customer_message(approval_id)` is the ONLY send path and it raises `ApprovalRequired` unless `status == 'approved'`; on send it sets `status='sent'` + timestamps | "No customer-facing item can send without approval" must be enforced by code shape, not convention. |
| **D5** | **Report sections**: ① KPI pregled (week revenue vs prior week, signal/task counts) — register `analiza` ② Najveći padovi (top-5 declines) — `analiza` ③ Izgubljeni artikli (top-5) — `analiza` ④ Uspavani kupci — `analiza` ⑤ Zadaci sedmice (open/done stats + top tasks) — `preporuka` ⑥ Nedavno potisnuto — placeholder, empty until M11 ⑦ Prijedlozi poruka (customer-facing drafts awaiting approval) — `akcija` + status | Covers the plan's required content; registers per the semantics of each block. |
| **D6** | Report narration reuses the **M6 narration layer** (masking, number contract, ai_log, retry, template fallback) with a new output schema (`ReportSectionNarrative {text, register}`) | One LLM discipline, not two. |

## 7. Tests (TDD: aggregate + gate tests written first)

### `tests/test_reports.py`
1. `test_report_aggregates_match_sql` — every number in the stored report payload (week
   revenue, prior-week revenue, each decline's value/baseline, lost-article counts, task
   counts) equals an independent direct-SQL computation, to the cent.
2. `test_report_sections_register_tagged` — all 7 sections present, each with a valid
   register; section 6 is the empty "recently suppressed" placeholder; section 7 items carry
   `akcija` + approval status.
3. `test_report_narrative_numbers_from_sql` — every narrative passes the number contract
   against its section's aggregates (FakeLLMClient); invented numbers → template fallback.
4. `test_report_is_stored_snapshot` — generating twice for the same week is idempotent
   (second run returns the existing snapshot, doesn't duplicate); reports for different
   weeks coexist.
5. `test_report_no_pii_in_prompts` — report narration prompts contain pseudonyms only
   (captured via FakeLLMClient).
6. `test_summary_block` — summary metrics/bullets are extracted from the latest report and
   carry registers.
7. `test_api_weekly_and_summary` — GET endpoints return the stored report / summary;
   404 envelope when no report exists.

### `tests/test_approvals.py`
8. `test_internal_actions_auto_run` — a full scheduled cycle (scan → tasks → report) runs
   with **zero** approval rows required; tasks and the report exist, nothing blocked.
9. `test_customer_facing_cannot_send_without_approval` — `send_customer_message()` on a
   `draft` / `pending_approval` / `rejected` approval raises `ApprovalRequired`; nothing is
   marked sent; after `decide(approved)` the send succeeds and sets `sent`.
10. `test_approval_lifecycle` — draft → pending_approval → approved (decided_by/decided_at
    recorded) → sent; the rejected path terminates; invalid transitions raise.
11. `test_drafts_generated_for_decline_and_sleeping_tasks` — report generation creates
    `kind='message'` draft approvals attached to decline/sleeping tasks; drafts are
    LLM-written (masked, number contract) with template fallback.
12. `test_draft_message_no_pii_in_prompt` — draft-message prompts are masked (the message
    body itself may use the real name only AFTER rehydration — it's for a human to review).
13. `test_api_approvals_list_and_decide` — GET filter by status; POST decide approves/
    rejects; deciding an already-decided approval → 409 envelope; unknown id → 404.

## 8. Acceptance criteria (per IMPLEMENTATION-PLAN M7)

1. **Report aggregates match SQL** (test 1).
2. **No customer-facing item can send without an approval row** (tests 9, 10) — enforced
   structurally.
3. **Internal actions auto-run** (test 8).
4. Every report block register-tagged (test 2); narrative numbers pass the contract (test 3).
5. The weekly scheduler produces the report after the scan; endpoints serve it (tests 4, 7).
6. Full pytest green locally + CI; ruff/black clean; principle-reviewer PASS.

## 9. Principles compliance

| Principle | M7 impact |
|---|---|
| 1. No LLM-computed numbers | Report aggregates are SQL (one reviewable .sql file); narratives pass the M6 number contract; test 1 cross-checks every stored number against SQL. |
| 2. Evidence on every conclusion | Each report section carries its `data` (the SQL rows it narrates); drafts attach to tasks → signals → evidence. |
| 3. Confidence on every conclusion | Section narratives carry the LLM confidence in ai_log (M6); detection confidences remain on signals shown in the report data. |
| 4./5. No ERP writes; read-only | Report/approvals write only `app.*`; no external sends exist (transport out of scope). |
| 6. PII masking before LLM | All report + draft narration goes through the M6 masking layer (tests 5, 12). |
| 7. Append-only logs | Every LLM call → `audit.ai_log` (M6 writer). Approval decisions are recorded on the approval row (decided_by/decided_at); the full `app.decision` log arrives in M10. |
| 8. Feedback loop | Unchanged (task feedback persists); report quality becomes assessable per section in M10+. |
| 9. **Register tags** | Every report section and approval item is register-tagged; actions additionally carry approval status (draft/pending/approved/sent) — the user always knows what has and hasn't happened. |
| 10. **Human approval for customer-facing communication** | This milestone implements it: the only send path is structurally gated on an approved approval row; internal actions never require approval. |
| Conventions | Typed Pydantic everywhere; one migration; secrets unchanged; thresholds: top-N section sizes are report layout constants (not detection thresholds), documented in builder.py. |

## 10. Open questions — resolved at review (2026-06-02)

1. **D1 (`app.owner_report` table)** — ✅ approved (+ data-model.md update).
2. **D2 (`app.approval.payload` column)** — ✅ approved (+ data-model.md update).
3. **D3 (drafts for decline + sleeping tasks)** — ✅ approved.
4. **D5 (report section list)** — ✅ approved (the 7 sections).
5. **Week boundary** — ✅ approved: Monday–Sunday, Sunday-night weekly job (Europe/Sarajevo).
