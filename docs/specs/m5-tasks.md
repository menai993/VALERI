# Spec — M5: Signal → Task pipeline + feedback + task log

**Milestone:** M5 · **Builds on:** M4 (signals exist) · **Status:** approved (D1–D4 OK'd by owner, 2026-06-02)

## 1. Objective

Prove that every detection becomes **work somebody owns**: each confirmed (`new`) signal is
turned into **exactly one** `app.task` assigned to the customer's sales rep (owner CC'd for
top-10 customers), carrying a Bosnian title/body/proposed action rendered from the signal's
SQL evidence, a due date from config, and the register tag. Reps give feedback
(`app.task_feedback`), and **every lifecycle event** lands in the append-only
`audit.task_log` — the first audit table goes live.

## 2. Scope

### In scope
1. **Migration 0006**: `task_status` enum, `app.task`, `app.task_feedback`,
   `audit.task_log` (exactly per docs/data-model.md) + per-rule `task_due_days` seeded into
   `app.rule_config`.
2. **`signals/` package**: the signal→task pipeline (assignee/owner_cc/due-date derivation in
   SQL; one task per signal; signal status → `tasked`), deterministic **Bosnian templates**
   for title/body/proposed_action (see D1), Pydantic schemas.
3. **`audit/` writers**: `audit/models.py` (TaskLog) + `audit/task_log.py`
   (`log_task_event()` — append-only, never updates/deletes).
4. **Scanner integration**: `run_scan(..., create_tasks=True)` — the scheduled scans produce
   tasks, not just signals.
5. **API**: `GET /api/tasks`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/status`,
   `POST /api/tasks/{id}/feedback` per docs/api-spec.md (cursor pagination, error envelope).
6. Tests: one-task-per-signal, correct assignee, owner_cc, evidence/register carried,
   due dates from config, full task_log lifecycle, feedback persistence, API behaviour.

### Out of scope (deferred)
- **LLM-written task bodies** (M6). M5 bodies are deterministic Bosnian templates that
  format SQL evidence values — no LLM call exists yet. M6 upgrades narration via the gateway.
- `audit.ai_log` (M6), `app.approval` / owner report (M7), `app.decision` (M10).
- Auth/RBAC on endpoints (M8) — same posture as ingest endpoints.
- Task UI (M8 Zadaci screen).
- Signal dismissal endpoint + self-config (`/signals/{id}/dismiss` is M10).

## 3. Files

```
apps/api/valeri_api/signals/
  __init__.py
  models.py             Task, TaskFeedback (SQLAlchemy, schema="app")
  schemas.py            TaskRead, TaskListResponse, TaskStatusUpdate, FeedbackCreate, FeedbackRead
  templates.py          per-rule Bosnian title/body/proposed_action templates
                        (pure string formatting of evidence values — no arithmetic, no LLM)
  pipeline.py           create_tasks_from_signals(session, as_of) -> TaskCreationResult:
                        assignee + owner_cc + due_date in SQL; signal → exactly one task;
                        signal.status → 'tasked'; task_log 'created' + 'assigned'

apps/api/valeri_api/audit/
  models.py             TaskLog (SQLAlchemy, schema="audit")
  task_log.py           log_task_event(session, task_id, event, payload) — append-only writer

apps/api/valeri_api/api/
  tasks.py              the 4 endpoints

apps/api/valeri_api/scanner/scan.py     (edit) run_scan(..., create_tasks=True)
apps/api/valeri_api/scanner/scheduler.py (edit) scheduled jobs create tasks
apps/api/valeri_api/main.py             (edit) mount tasks router

apps/api/migrations/versions/
  0006_tasks.py         task_status enum + app.task + app.task_feedback + audit.task_log
                        + task_due_days config seeds

apps/api/tests/
  test_tasks.py         pipeline + lifecycle + API tests (list in §7)
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.task` | **create** (0006) + write (pipeline) | exactly per data-model.md, `ix_task_assignee_status` |
| `app.task_feedback` | **create** (0006) + write (API) | |
| `audit.task_log` | **create** (0006) + append (writer) | **append-only**: the writer has no update/delete path |
| `app.signal` | read + status update | `new` → `tasked` when its task is created |
| `app.rule_config` | read + **seed** | new param `task_due_days` per rule (D3) |
| `core.customer_rep`, `core.customer_metrics`, `core.customer`, `core.sales_rep` | read | assignee + top-10 + names for templates |

- **One migration**: `0006_tasks` (enum `task_status` + 3 tables + config seeds).

## 5. API touchpoints (per docs/api-spec.md, Tasks M5)

| Endpoint | Request | Response |
|---|---|---|
| `GET /api/tasks?assignee=&status=&rule=&limit=&cursor=` | — | `{items: [TaskRead], next_cursor}` |
| `GET /api/tasks/{id}` | — | `TaskRead` (+ writes `viewed` to task_log); 404 envelope |
| `POST /api/tasks/{id}/status` | `{"status": "in_progress"\|"done"\|"dismissed"}` | updated `TaskRead`; writes task_log |
| `POST /api/tasks/{id}/feedback` | `{"useful": bool, "reason": str?}` | `FeedbackRead`; writes task_log |

`TaskRead` carries the AI-response envelope fields: register, confidence + conf_band and
evidence (joined from the signal), plus title/body/proposed_action/due_date/status/assignee.

## 6. Task derivation (exact semantics)

| Field | Derivation (SQL unless stated) |
|---|---|
| `signal_id` | the source signal; **exactly one task per signal** (enforced by flipping signal status to `tasked` in the same transaction) |
| `assignee_id` | the customer's current rep: latest `core.customer_rep.from_date` per customer |
| `owner_cc` | `true` if the customer is **top-10 by `turnover_6m_avg_60d`** (rank in SQL; D2) |
| `title` | Bosnian template per rule (templates.py), e.g. decline → `"Pad prometa: {customer_name}"` |
| `body` | Bosnian template formatting the **signal's evidence values verbatim** (no recomputation), e.g. decline → `"Promet u zadnjih 60 dana: {value} KM (uobičajeno {baseline} KM, promjena {delta_pct}%). Pad nije sezonski."` + footer `"Brojke iz baze · SQL"` |
| `proposed_action` | Bosnian template per rule, e.g. decline → `"Kontaktirati kupca, provjeriti razlog pada i ponuditi akcijsku ponudu."` |
| `due_date` | `signal.created_at::date + task_due_days(rule)` from `app.rule_config` (D3) |
| `status` | `open` |
| `register` | `preporuka` (a task is by nature a recommendation to act; the underlying signal keeps its own register) — D4 |

Task lifecycle events written to `audit.task_log`: `created` (payload: signal_id, rule) ·
`assigned` (assignee_id, owner_cc) · `viewed` (on GET detail) · `actioned` (status →
in_progress) · `outcome` (status → done/dismissed) · `feedback` (useful, reason).

## 7. Tests (TDD: pipeline tests written before the pipeline)

`tests/test_tasks.py` (uses the seeded + scanned DB fixture from M4 tests):

1. `test_one_task_per_signal` — after scan + pipeline: every previously-`new` signal is
   `tasked` and has exactly one task; **running the pipeline again creates zero tasks**.
2. `test_assignee_is_customers_rep` — every task's `assignee_id` equals the customer's
   current rep (independent SQL cross-check).
3. `test_owner_cc_for_top10_customers` — tasks of top-10-by-baseline customers have
   `owner_cc = true`, all others `false` (independent SQL ranking cross-check).
4. `test_task_carries_evidence_and_register` — every task: register `preporuka`, its signal's
   evidence reachable, Bosnian title/body non-empty, body ends with "Brojke iz baze · SQL".
5. `test_body_numbers_equal_signal_evidence` — contract: every number appearing in a decline
   task's body is the exact string of an evidence value (no recomputed/derived numbers).
6. `test_due_dates_from_config` — due_date = signal date + configured `task_due_days`;
   changing the config value changes the next pipeline run's due dates.
7. `test_no_task_for_dismissed_or_suppressed_signals` — signals not in status `new` are skipped.
8. `test_task_log_lifecycle` — created + assigned on creation; actioned on in_progress;
   outcome on done; feedback event; events accumulate append-only in chronological order.
9. `test_feedback_persists` — feedback rows persist with useful/reason/timestamp; multiple
   feedback entries per task allowed.
10. `test_api_list_filters_and_pagination` — GET /tasks by assignee/status; limit+cursor.
11. `test_api_detail_writes_viewed` — GET /tasks/{id} returns the envelope fields and logs
    `viewed`; unknown id → 404 envelope.
12. `test_api_status_transition` — POST valid status → updated + logged; invalid → 422.
13. `test_api_feedback` — POST feedback → persisted + logged.
14. `test_scan_creates_tasks` — `run_scan(create_tasks=True)` produces signals **and** their
    tasks in one transaction.

## 8. Acceptance criteria (per IMPLEMENTATION-PLAN M5)

1. **One task per signal with the correct assignee** (tests 1–3).
2. **Feedback persists** (tests 9, 13).
3. **task_log records the full lifecycle** (test 8) and is written by an append-only writer.
4. Tasks carry evidence/register/due-date per the data model (tests 4–6).
5. Endpoints behave per api-spec (tests 10–13).
6. Full pytest suite green locally + CI; ruff/black clean.
7. principle-reviewer reports PASS on the M5 diff.

## 9. Principles compliance

| Principle | M5 impact |
|---|---|
| 1. No LLM-computed numbers | No LLM exists yet (M6). Templates only **format** SQL-computed evidence values; test 5 asserts no recomputation. |
| 2. Evidence on every task | Tasks link to their signal; evidence travels with the task (API joins it); test 4. |
| 3. Confidence on every conclusion | The task exposes its signal's confidence + band in the API envelope. |
| 4./5. No ERP writes; read-only posture | Pipeline writes only `app.*`/`audit.*`. |
| 6. PII masking before LLM | No LLM call. Task titles/bodies use real customer names — they are for **human reps** (rehydrated view); masking applies at the LLM boundary in M6. |
| 7. **Append-only logs** | `audit.task_log` goes live with a writer that can only INSERT; every lifecycle event recorded (test 8). |
| 8. Feedback loop | `app.task_feedback` capture ships now — the raw material for M10's self-configuration. |
| 9. Register tags | Every task carries `register='preporuka'`; the signal keeps its own register; both visible in the API. |
| 10. Approval gates | N/A — tasks are internal work items; no customer-facing sending exists yet (M7). |
| Conventions | due-date offsets in `rule_config` (never literals); typed Pydantic I/O; one migration; cursor pagination per api-spec. |

## 10. Open questions — resolved at review (2026-06-02)

1. **D1 — Template bodies in M5** — ✅ confirmed (LLM narration replaces them in M6).
2. **D2 — Top-10 ranking** — ✅ confirmed: `turnover_6m_avg_60d`.
3. **D3 — Due-date offsets** — ✅ confirmed: 3/5/7/7/14 days.
4. **D4 — Task register** — ✅ confirmed: every task = `preporuka`.
