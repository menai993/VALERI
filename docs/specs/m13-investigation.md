# Spec — M13: Investigation agent (LangGraph, async, HITL)

**Milestone:** M13 · **Builds on:** M9 (safe tool catalog + chat stub), M12 (Tier-2 routing roles already registered), M7 (approval workflow) · **Status:** awaiting owner review

## 1. Objective

Give VALERI the ability to **investigate hard questions with a stronger model** — "Zašto hotel
segment pada tri mjeseca zaredom?" — without ever loosening the trust rules. A LangGraph state
machine (plan → act → critic → synthesize) runs **asynchronously in the worker** on Tier-2
(Sonnet, synthesis on Opus), uses **only the safe tool catalog** for data (numbers = SQL, RBAC,
logged), is **hard-capped** in steps/tokens/time, **checkpoints to Postgres** so a restart resumes
instead of restarting, and **interrupts before any action** (task/draft) until a human approves.
The result is a stored, register-tagged report: Bosnian narrative + findings + confidence +
recommended next step + the full step trace.

## 2. Scope

### In scope

1. **`investigation/` package**: the LangGraph graph (4 nodes + an HITL action node), Postgres
   checkpointing, budget caps, the async runner, the append-only step trace.
2. **Migration 0014**: `app.investigation` + `app.investigation_step` + `inv_status` enum
   (exactly per data-model.md) + `investigation` budget seeds in `rule_config`.
3. **New dependencies**: `langgraph` + `langgraph-checkpoint-postgres` (pinned latest stable;
   mandated by CLAUDE.md/architecture.md). LangGraph's checkpoint tables are created by its own
   `setup()` (per data-model.md), not by Alembic.
4. **HITL**: the agent never executes a mutating tool directly — proposed actions interrupt the
   graph (`interrupt_before`), the investigation becomes `needs_input`, and only an explicit
   `POST /resume {decision}` executes or discards them.
5. **The real `start_investigation` tool** (replaces the last M9 stub) + chat wiring: the
   "Istraži" intent creates a queued investigation and links to it.
6. **API**: `POST /investigations`, `GET /investigations?status=`, `GET /investigations/{id}`,
   `POST /investigations/{id}/resume`, `GET /investigations/{id}/stream` (SSE).
7. **Web**: the **Istrage** tab goes live — InvestigationList + "Nova istraga" form +
   InvestigationReport (narrative, findings, confidence, next step, trace); chat investigation
   card links to the investigation.
8. **Worker**: an interval job polls for `queued` investigations and runs them.

### Out of scope (deferred)

- `get_client_knowledge` / `search_documents` agent tools (CI2/DI2).
- Auto-triggered investigations from signals (`trigger='auto'` is stored but only `user` triggers
  are created in M13).
- Investigation cost dashboards (X1); Bosnian narration quality pass (M14 pilot).
- Multi-turn follow-up questions on a finished investigation (new investigation instead).

## 3. Files

### Backend

```
pyproject.toml (edit)                          + langgraph, langgraph-checkpoint-postgres
migrations/versions/0014_investigation.py      app.investigation + app.investigation_step +
                                               inv_status enum + rule_config 'investigation' seeds
                                               (max_steps 8, max_seconds 300, max_tokens 50000)
valeri_api/investigation/__init__.py
valeri_api/investigation/models.py             SQLAlchemy: Investigation, InvestigationStep
valeri_api/investigation/schemas.py            InvestigationState (graph state) · LLM output schemas:
                                               PlanOutput, ToolChoice, CriticVerdict, SynthesisOutput ·
                                               API schemas: InvestigationCreate/Read/Detail/Resume
valeri_api/investigation/prompts.py            Bosnian system prompts: PLAN / ACT / CRITIC / SYNTHESIZE
                                               (numbers verbatim, pseudonyms, JSON-only)
valeri_api/investigation/steps.py              record_step(): append-only investigation_step writer
valeri_api/investigation/budget.py             load_budget(rule_config) + over_budget(state) checks
valeri_api/investigation/nodes.py              plan_node · act_node (tool loop via dispatch()) ·
                                               critic_node · execute_action_node (HITL-gated) ·
                                               synthesize_node (writes the report)
valeri_api/investigation/graph.py              build_graph(checkpointer, client): StateGraph wiring,
                                               conditional edges, interrupt_before=["execute_action"]
valeri_api/investigation/checkpoint.py         get_checkpointer(): PostgresSaver on DATABASE_URL +
                                               lazy setup() of LangGraph's tables
valeri_api/investigation/runner.py             create_investigation() · run_investigation(id) (queued→
                                               running→needs_input/done/failed) · resume_investigation(id,
                                               decision) · poll_queued() (the worker entry)
valeri_api/tools/start_investigation.py        the REAL tool: creates a queued app.investigation
valeri_api/tools/stubs.py                      DELETED (no stubs remain)
valeri_api/tools/catalog.py (edit)             register the real start_investigation
valeri_api/conversation/answer.py (edit)       narration/template for the real investigation output
valeri_api/conversation/service.py (edit)      ok investigation → card_type "investigation"
valeri_api/api/investigations.py               the 5 endpoints per api-spec.md (RBAC, SSE)
valeri_api/main.py (edit)                      mount investigations_router
valeri_api/scanner/scheduler.py (edit)         + interval job `investigation_poll` (every 10s)
tests/test_investigation.py                    the acceptance tests (TDD, §6)
tests/tools/test_start_investigation.py        tool contract/RBAC/logging tests
tests/tools/test_stubs.py                      DELETED (replaced by the above + unknown-tool test moves)
```

### Frontend

```
src/components/widgets/InvestigationReport.tsx  narrative + findings (each with confidence + evidence) +
                                                next step + collapsible step trace
src/features/ai-report/InvestigationsTab.tsx    list (status chips) + "Nova istraga" form + report view +
                                                HITL approve/reject panel for needs_input
src/features/ai-report/AIReportPage.tsx (edit)  mount the real Istrage tab
src/features/chat/ChatMessage.tsx (edit)        investigation card → link to /ai-report (Istrage)
src/lib/api/types.ts + queries.ts (edits)       Investigation types · useInvestigations/useInvestigation/
                                                useCreateInvestigation/useResumeInvestigation + SSE helper
src/lib/i18n/bs.ts + en.ts (edits)              investigation strings (replace the M13 placeholder)
src/test/investigations.test.tsx                UI tests (§6)
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.investigation` | **create** (0014) + write | id, trigger, question, status (`inv_status`), model_tier, started_at, finished_at, report JSONB, thread_id — exactly per data-model.md |
| `app.investigation_step` | **create** (0014) + append-only writes | step_no, node, tool, input (masked), output, at — the full trace |
| `inv_status` enum | **create** (0014) | queued / running / needs_input / done / failed |
| `app.rule_config` | **seed** (0014) + read | rule=`investigation`: `max_steps` 8, `max_seconds` 300, `max_tokens` 50000 — caps never hard-coded |
| LangGraph checkpoint tables | created by `PostgresSaver.setup()` | same DB, `checkpoints*` tables; not Alembic-managed (per data-model.md note) |
| `app.task` / `app.approval` | write **only via HITL-approved actions** | the execute_action node calls the existing safe tools (create_task_draft → task + decision; drafts stay approval-gated by M7) |
| `audit.ai_log`, `audit.llm_route_log`, `app.tool_call_log` | written by existing infrastructure | every agent LLM call and tool call is already disciplined |

**Graph design (the binding shape):**

```
START → plan → act ⇄ critic → synthesize → END
                 ↘ (proposed actions) → [INTERRUPT] → execute_action → synthesize
```

- **plan** (Tier-2 / `investigation` role): masked question → sub-questions + first tool calls.
- **act** (Tier-2): picks ONE safe-catalog tool + params per iteration → `dispatch()` runs it
  (RBAC/validation/logging) → masked result into state. Mutating tools are NEVER dispatched here —
  the model can only *propose* them (collected in `state.proposed_actions`).
- **critic** (Tier-2): are the findings sufficient/grounded? → `synthesize` | `act` (more, if under
  budget) | force-synthesize when any budget cap is hit.
- **execute_action** (no LLM): runs HITL-approved proposed actions through `dispatch()`; the graph
  **interrupts before this node** — it only ever runs after `POST /resume {decision:"approve"}`.
- **synthesize** (Tier-2-strong / `investigation_synthesis` role): Bosnian narrative + findings +
  confidence + next step; number contract enforced against ALL tool outputs; rehydrated and stored
  in `investigation.report`; register `analiza` (the recommended next step is `preporuka`).

## 5. API touchpoints (per docs/api-spec.md M13)

- `POST /investigations` `{question, signal_id?}` → 202 `{investigation_id}` (status `queued`;
  the worker picks it up). RBAC: owner/admin.
- `GET /investigations?status=` → list (id, question, status, started/finished, model_tier).
  RBAC: owner/admin/finance.
- `GET /investigations/{id}` → `{investigation, report, steps[]}` (the full trace).
- `POST /investigations/{id}/resume` `{decision: "approve"|"reject", note?}` → satisfies the HITL
  interrupt; approve executes the proposed action(s), reject discards them; either way the graph
  continues to synthesize. RBAC: owner/admin.
- `GET /investigations/{id}/stream` (SSE) → `{type: "status"|"step"|"done", ...}` progress events
  (poll-based readout of investigation_step + status; closes on done/failed/needs_input).

## 6. Tests (`tests/test_investigation.py`, TDD — the agent is trust-critical)

All LLM calls scripted via injected fakes; the graph + checkpointer run against the real test
Postgres.

1. `test_loop_cap_enforced` — a critic that always wants more → act stops at `max_steps`
   (rule_config), the run still produces a report (confidence reflects incompleteness), and the
   step trace shows exactly max_steps act steps. *(acceptance 1)*
2. `test_budget_caps_live_in_rule_config` — lowering `max_steps` in DB changes where the loop
   stops; nothing hard-coded.
3. `test_hitl_blocks_external_draft` — the agent proposes `create_task_draft` → the graph
   interrupts, investigation = `needs_input`, **no task exists in app.task** → resume(approve) →
   the task exists + the decision/task_log trail; resume(reject) → still no task, the report notes
   the discarded proposal. *(acceptance 2)*
4. `test_numbers_only_from_sql` — every number in the stored report narrative/findings appears in
   the tool outputs (number-contract assertion over the whole trace); a scripted synthesize output
   with an invented number is rejected → retried/templated, never stored. *(acceptance 3)*
5. `test_resume_after_simulated_restart` — run until `needs_input`, then build a brand-new
   graph/runner instance (new process simulation) with the same `thread_id` → resume → completes;
   previously executed steps are NOT re-executed (step count and tool_call_log count unchanged for
   the pre-interrupt part). *(acceptance 4)*
6. `test_full_step_trace` — every node execution appends one `investigation_step` row (plan, each
   act, each critic, synthesize), ordered by step_no, inputs masked.
7. `test_agent_prompts_are_masked` — no raw customer name in any captured agent prompt; pseudonyms
   present; the stored report narrative is rehydrated (human-facing).
8. `test_agent_tools_respect_rbac` — the agent runs with the requesting user's ToolContext; tools
   outside that user's scope fail closed and the failure lands in the trace, not in a crash.
9. `test_worker_picks_up_queued` — `poll_queued()` runs a queued investigation to completion;
   the scheduler has an `investigation_poll` job.
10. `test_status_lifecycle` — queued → running → done/failed/needs_input transitions are recorded
    with timestamps; a node exception → `failed` with the error in the trace (never silent).

`tests/tools/test_start_investigation.py`:

11. The tool creates a `queued` investigation linked to the asking user + optional signal; logged
    in tool_call_log; RBAC (owner/admin create; rep/finance → forbidden); the M9 "unknown tool"
    test moves here from the deleted test_stubs.py.

API (in `tests/test_investigation.py`):

12. `test_api_create_list_detail_resume_rbac` — the 4 JSON endpoints + RBAC + 404/409 envelopes;
    detail carries report + trace; resume only valid on `needs_input` (else 409).
13. `test_api_sse_stream` — the SSE endpoint emits step/status events and closes on done.

Web (`src/test/investigations.test.tsx`):

14. The Istrage tab renders the list with status chips; the report shows narrative + findings with
    confidence + next step + trace; the needs_input state shows the approve/reject panel; creating
    an investigation calls POST.

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN M13)

1. **Loop cap enforced** — the act loop cannot exceed the configured budget. *(tests 1, 2)*
2. **HITL gate blocks an external draft until approval** — nothing customer-facing or task-creating
   happens while the graph is interrupted. *(test 3)*
3. **No model-computed numbers** — report figures equal SQL/tool output. *(test 4 + /numbers-check)*
4. **A run resumes from its checkpoint after a simulated restart.** *(test 5)*

## 8. Principles compliance

| # | Principle | How M13 honors it |
|---|---|---|
| 1 | AI computes no numbers | The agent's only data source is the safe tool catalog (SQL); synthesize narrative passes the number contract against the union of tool outputs |
| 2 | Evidence on every conclusion | Each finding carries the tool calls (with their SQL evidence) that produced it; the full trace is stored and viewable |
| 3 | Confidence on every conclusion | The report carries an overall confidence + per-finding confidence; budget-capped runs say so |
| 4 | No writes to source ERP | The agent writes only app.investigation/investigation_step; actions go through existing safe tools |
| 5 | Read-only/staging | Unchanged |
| 6 | PII masking before LLM | The question and every tool output are masked before any agent prompt (same machinery as chat); the stored report is rehydrated for humans |
| 7 | Append-only logs | investigation_step is append-only; ai_log/route_log/tool_call_log keep recording every call; status transitions are timestamped, never overwritten history |
| 8 | Feedback loop | The critic node is a built-in self-check; reports carry next steps that feed tasks (via HITL) |
| 9 | Register/visibility | The report is `analiza`, its recommended next step `preporuka`, executed actions `akcija` with visible status; the UI shows all states incl. needs_input |
| 10 | Approval for external actions | The whole point of interrupt_before: tasks/drafts NEVER happen without `POST /resume {approve}`; customer-facing drafts additionally stay in the M7 approval queue |

## 9. Open questions (decide before implementation)

- **D1 — Dependencies.** Add `langgraph` + `langgraph-checkpoint-postgres` (latest stable, pinned
  in the lockfile). Mandated by CLAUDE.md; the checkpointer uses the existing Postgres. OK?
- **D2 — Async mechanism.** The worker polls for `queued` investigations every 10s (APScheduler
  interval job). The API returns 202 immediately; tests run the runner synchronously. OK?
- **D3 — Budget defaults** (rule_config): `max_steps=8` act iterations, `max_seconds=300`,
  `max_tokens=50000`. When a cap is hit the agent synthesizes from what it has (confidence
  reflects incompleteness) rather than failing. OK?
- **D4 — RBAC.** Create + resume: owner/admin. View: owner/admin/finance. (Reps ask via chat; the
  chat tool tells a rep the investigation was created for the owner to review — or we allow reps
  to create investigations scoped to their own customers. Default: owner/admin only.) OK?
- **D5 — HITL semantics.** The act node can only *propose* mutations; all proposals are gated by
  ONE interrupt before execute_action; resume approves/rejects them as a batch. (Per-action
  granularity deferred.) OK?
- **D6 — Chat wiring.** The chat "istraži" intent calls the real start_investigation tool →
  creates a queued investigation → the reply carries a card linking to the Istrage tab. OK?
- **D7 — Critic cadence.** The critic runs after every act iteration (Tier-2 call each time).
  Investigations are rare and hard-capped, so cost is bounded; this maximizes quality. OK?
