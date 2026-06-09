# Spec — P1: Close the loop (approvals UI, inbox, task→activity, Danas)

**Track:** Improvement Roadmap P1 (`docs/IMPROVEMENT-ROADMAP.md`) · **Builds on:** M7 approvals API (complete, UI-less), C-CRM2 activity API (`POST /activity`, hook unused), CI1 review queue, M13 investigations API, M8 dashboard/tasks · **Status:** implemented (D1–D6 defaults approved by owner, 2026-06-09)

## 1. Objective

Every confirmation VALERI produces becomes reachable and one tap away, and the people-loop closes where people work. Today the owner **cannot approve a customer draft in-app** (no screen consumes `/approvals`), the notifications bell is decorative, a rep cannot log what happened when closing a task (`useLogActivity` unmounted), and there is no "Danas" view. P1 ships: the **Odobrenja** screen, a **real inbox bell** fed by one SQL aggregate, **task→activity in one flow**, the **Danas** preset + due filters, wired **quick actions** (Novi zadatak / Nova analiza + an Istraži button on the customer 360), and clickable cross-links. UI-first phase: numbers all come from existing SQL; the only new writes are a manual-task endpoint and the existing activity/approval/investigation endpoints.

## 2. Scope

### In scope
- **Odobrenja screen** (`/odobrenja`, owner/admin): pending-first tabs, draft text + customer + evidence, one-tap Odobri/Odbij/Odgodi via existing `POST /approvals/{id}/decide`.
- **`GET /api/inbox/summary`** (new, SQL counts, RBAC-aware) + functional **NotificationsBell** (badge + dropdown linking to /odobrenja, /zabiljeske, /zadaci) + count badge on the Zabilješke nav item.
- **Task → activity in one flow**: marking a task done opens an inline "Šta je urađeno?" mini-form (kind, done) posting to existing `POST /activity`; skippable. Visible toast on feedback/actions (new dependency-free `Toast`).
- **`POST /api/tasks`** (new): manual task (title, body?, assignee_id, due_date?; `signal_id NULL`); writes `audit.task_log` `created`; powers the "Novi zadatak" quick action.
- **Danas**: `"1d"` range preset (backend `RANGE_PRESETS` + DateRangePicker), `GET /tasks?due=today|overdue` filter + due-date sort on Zadaci.
- **Quick actions wired**: "Novi zadatak" → task dialog; "Nova analiza" → investigation dialog (shared component with InvestigationsTab); **Istraži** button on CustomerDetailPage (prefilled question).
- **Cross-links**: customer-360 task/signal rows link to `/zadaci?task={id}` (highlight) and `/ai-report` (Istrage/insights context); remove the stale `soon: true` badge on Prilike.
- `TaskRow` API response gains `customer_id`/`customer_name` (read-only join via signal) so the activity form and links know the customer.

### Out of scope (deferred)
- Job-failure alerts in the inbox (P2 — the summary shape reserves an `alerts` field at 0).
- Approvals for Airtable proposals (P4), e-mail/Viber transport of approved drafts (P7).
- Mobile bottom nav, i18n/format sweep (P7). New approval kinds. Web push/e-mail notifications.

## 3. Files

```
apps/api/valeri_api/
  api/inbox.py                       # NEW GET /inbox/summary — SQL counts, RBAC-aware
  api/tasks.py                       # EDIT: POST /tasks (manual), ?due= filter, due sort,
                                     #   customer_id/customer_name in TaskRow (join via signal)
  signals/schemas.py                 # EDIT: TaskRow + TaskCreate schemas
  signals/pipeline.py (or service)   # EDIT: create_manual_task() writing audit.task_log
  metrics/dashboard.py               # EDIT: RANGE_PRESETS += {"1d": 1}
  main.py                            # EDIT: mount inbox router

apps/api/tests/
  test_inbox.py                      # NEW: summary counts == SQL per role
  test_tasks.py                      # EDIT: manual task + task_log + RBAC; due filter; customer fields
  test_dashboard.py                  # EDIT: 1d preset accepted

apps/web/src/
  features/approvals/ApprovalsPage.tsx     # NEW: the Odobrenja screen
  components/widgets/ApprovalCard.tsx      # NEW: per frontend-spec §4 (item, onApprove/Reject/Defer)
  components/widgets/NewTaskDialog.tsx     # NEW: manual-task form → POST /tasks
  components/widgets/InvestigationDialog.tsx # NEW: shared create-investigation form (reused by
                                           #   Sidebar quick action, CustomerDetail Istraži, InvestigationsTab)
  components/widgets/ActivityPrompt.tsx    # NEW: "Šta je urađeno?" inline form on task completion
  components/ui/toast.tsx                  # NEW: minimal toast (context + portal, no new dep)
  app/TopBar.tsx                           # EDIT: functional bell (badge + dropdown) from useInboxSummary
  app/Sidebar.tsx                          # EDIT: /odobrenja item (owner/admin) + Zabilješke badge,
                                           #   quick actions onClick, remove Prilike soon:true
  features/tasks/TasksPage.tsx             # EDIT: due filter/sort, ActivityPrompt on done, ?task= highlight, toast
  features/customers/CustomerDetailPage.tsx# EDIT: clickable task/signal rows + Istraži button
  features/ai-report/InvestigationsTab.tsx # EDIT: use shared InvestigationDialog form
  components/widgets/DateRangePicker.tsx   # EDIT: "1d" preset (Danas)
  lib/api/types.ts / queries.ts            # EDIT: InboxSummary, TaskCreate, useInboxSummary,
                                           #   useCreateTask, due filter param
  lib/i18n/bs.ts / en.ts                   # EDIT: approvals/inbox/activity-prompt/danas strings
  routes.tsx                               # EDIT: /odobrenja route
apps/web/src/test/
  approvals.test.tsx                       # NEW   inbox-bell.test.tsx  # NEW
  task-activity.test.tsx                   # NEW   (TasksPage edits covered here)
```

## 4. Data-model touchpoints

- **No migration.** Reads: `app.approval`, `app.task` (due_date), `app.clarification` (pending), `app.client_fact`/`commercial_event`/`client_relationship` (proposed), `app.signal` (task→customer join), `core.customer`, `app.activity`.
- Writes (existing tables only): `app.task` (manual insert, `signal_id NULL` — allowed by schema), `audit.task_log` (`created`, `status`, `feedback` events — existing writers), `app.activity` (existing endpoint), `app.approval` (existing decide flow).

## 5. API touchpoints

- **NEW `GET /api/inbox/summary`** → `{pending_approvals, pending_clarifications, proposed_kb_items, tasks_due_today, alerts: 0, total}` — pure SQL `COUNT`s; RBAC: `pending_approvals` only for owner/admin (else 0); `tasks_due_today` scoped to the rep's own tasks for `sales_rep`.
- **NEW `POST /api/tasks`** `{title, body?, assignee_id, due_date?, customer_id?}` → TaskRow (201). RBAC: owner/admin any assignee; sales_rep only self; finance 403. Writes `task_log('created')`. Manual tasks render without the AI envelope (no confidence/evidence — they are user data).
- **EDIT `GET /api/tasks`**: `?due=today|overdue` filter, `?sort=due_date`, and TaskRow gains `customer_id`/`customer_name`.
- **EDIT `GET /api/dashboard|/api/metrics/*`**: accept `range=1d` (presets map only).
- Unchanged but newly consumed by UI: `GET/POST /approvals*`, `POST /activity`, `POST /investigations`.

## 6. Tests

**Backend (TDD first):**
- `test_inbox.py::test_summary_counts_match_sql` — each count equals an independent SQL count (seeded approvals/clarifications/proposed/tasks).
- `test_inbox.py::test_summary_rbac` — rep: approvals=0, tasks_due_today only their own; finance: approvals=0; owner: all.
- `test_tasks.py::test_manual_task_created_with_task_log` — POST /tasks → row with `signal_id NULL` + one `task_log` `created` event.
- `test_tasks.py::test_manual_task_rbac` — rep forced to self-assign; finance 403.
- `test_tasks.py::test_due_filter_and_sort` — `due=today`/`overdue` rows == SQL; sort by due_date.
- `test_tasks.py::test_task_row_carries_customer` — customer_id/name joined via signal; NULL-safe for manual tasks.
- `test_dashboard.py::test_range_1d_accepted` — `?range=1d` → `range_days==1`.

**Frontend (vitest):**
- `approvals.test.tsx` — pending list renders kind/customer/message + evidence; Odobri fires decide; decided item leaves pending tab.
- `inbox-bell.test.tsx` — badge = total from fixture; dropdown shows category counts + links; zero → no badge.
- `task-activity.test.tsx` — marking done opens ActivityPrompt; submit posts kind to /activity and toasts; Preskoči skips; due filter renders.
- existing `dashboard.test.tsx` — "Danas" preset present.

## 7. Acceptance criteria

1. Owner approves a pending customer draft **entirely in-app**; the decision is recorded (decided_by/at) and the item leaves the pending queue.
2. The bell shows a real count (== SQL) that clears as items are handled; Zabilješke nav carries its own badge.
3. Completing a task can log an activity (kind) in the same dialog; the activity row exists in `app.activity`; skipping is one tap.
4. "Danas" exists on Početna (range=1d) and Zadaci (due-today/overdue); numbers match SQL.
5. "Novi zadatak" and "Nova analiza" perform real actions (manual task / investigation); Istraži exists on the customer 360; no dead buttons remain; Prilike no longer says "Uskoro".
6. Customer-360 task/signal rows navigate to the task (highlighted) / AI report.
7. RBAC holds everywhere (rep: own tasks only, no approvals; finance: read-only).

## 8. Principles compliance

| # | Principle | How P1 honors it |
|---|-----------|------------------|
| 1 | No LLM-computed numbers | No LLM in this phase; all counts/filters are SQL. |
| 2 | Evidence on every AI signal/task | Unchanged for AI tasks (ApprovalCard shows the draft's evidence); manual tasks are user data, clearly not AI output (no envelope). |
| 3 | Confidence on AI conclusions | Unchanged; surfaces keep ConfidenceLabel where AI-derived. |
| 4 | No ERP writes | None — only VALERI's own DB. |
| 5 | Read-only staging | Untouched. |
| 6 | PII masking | N/A — no LLM calls added. |
| 7 | Append-only logs | Manual task writes `task_log('created')`; approval decisions already log via the M7 flow (`app.decision` on decide). |
| 8 | Feedback loop | Strengthened: feedback gets visible confirmation; activity capture closes the why-was-this-closed gap. |
| 9 | Analysis/recommendation/action | Approvals screen surfaces `akcija + status` explicitly — nothing happens silently; manual tasks carry register without implying AI origin. |
| 10 | Human approval for external comms | This phase finally gives that approval a usable UI; sending still does not happen (transport is P7). |

## 9. Open questions (defaults — confirm or override)

- **D1 manual-task creators:** owner/admin (any assignee) + sales_rep (self only); finance excluded. *(default)*
- **D2 activity prompt timing:** shown on `done` only, with "Preskoči"; not on `in_progress`. *(default)*
- **D3 bell refresh:** refetch on window focus + 60s polling. *(default)*
- **D4 manual-task register:** keep column default `'preporuka'`, UI renders manual tasks without AI envelope. *(default)*
- **D5 task highlight:** `/zadaci?task={id}` scroll-and-highlight, no separate detail page. *(default)*
- **D6 inbox `alerts` field:** present, always 0 until P2. *(default)*
