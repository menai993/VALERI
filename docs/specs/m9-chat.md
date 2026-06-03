# Spec — M9: Safe tool catalog + intent router + chat (Ask VALERI)

**Milestone:** M9 · **Builds on:** M8 (auth/RBAC, dashboard APIs, web shell) · **Status:** approved (D1–D6 OK'd by owner, 2026-06-03)

## 1. Objective

Let the owner **talk to the business in Bosnian**: a chat where every question is answered
with **SQL-computed numbers fetched through a safe, typed, RBAC-checked, audited tool
catalog** — never by an LLM that touches the database. The Tier-1 model only classifies
intent and narrates finished numbers; every reply carries a register tag; every tool call
lands in `app.tool_call_log`. This is the conversation foundation that self-configuration
(M10), the learning loop (M11) and the investigation agent (M13) plug into.

## 2. Scope

### In scope — the tool catalog (`tools/`, each per the `/tool` scaffold)
| Tool | Kind | What it does (data source) |
|---|---|---|
| `query_metric` | read | One metric from the **semantic registry** (`turnover`, `turnover_by_month`, `customer_turnover_60d`, `customer_baseline_60d`, `customer_last_order`, `customer_order_interval`) via `semantic.run_metric()` |
| `compare_periods` | read | Turnover of two periods + delta — one SQL query computes both values **and** the delta |
| `list_signals` | read | Open signals (rule/conf filters), rep-scoped, full envelope |
| `explain_signal` | read | One signal: evidence + confidence + its task + customer |
| `get_customer_360` | read | Reuses `metrics.dashboard.customer_360()` (SQL), rep-scoped |
| `create_task_draft` | **mutation** | INSERT `app.task` (internal action) + `audit.task_log` + **reversible `app.decision`** (D1) |
| `propose_rule_change` | stub | Returns `{available: false, milestone: "M10"}` — keeps the catalog/router contract stable |
| `start_investigation` | stub | Returns `{available: false, milestone: "M13"}` |

Catalog infrastructure: `ToolContext` (session+user+message_id), typed dispatch
(RBAC → validate → run → **log success AND failure**), `app.tool_call_log` writer.

### In scope — conversation (`conversation/`)
1. **Migration 0010**: `app.conversation`, `app.message`, `app.tool_call_log` (per
   data-model.md) **+ `app.decision` + its enums** (D1 — required by the tool-mutation contract).
2. **Entity resolution (deterministic, server-side)**: customer/article names mentioned in
   the message matched against `core.*` by normalised substring — never by the model.
3. **PII-masked intent routing (Tier-1)**: resolved names → pseudonyms before the prompt;
   output = `{intent, tool, params, confidence}` (Pydantic, reject+retry, ai_log).
   Intents: `question | feedback_config | investigation | action | help`.
4. **Tool dispatcher**: maps pseudonym refs back to ids (server-side), calls the catalog.
5. **Answer narration (Tier-1)**: tool result (finished SQL numbers, masked) → Bosnian reply
   + register via the M6 `narrate_structured` discipline (number contract, template fallback).
6. **Session memory**: conversations/messages persisted; the last N messages give the router context.
7. **SSE streaming**: `tool_call` → `register` → `token` → `card?` → `done` events.

### In scope — web (Ask VALERI screen)
8. `features/chat/`: ChatPage (thread + input), ChatMessage (register chip + narrative +
   tool-result card + EvidenceExpander), SSE consumption; GlobalSearch + "Pitaj VALERI"
   quick action route here; chat strings in bs/en catalogs.

### Out of scope (deferred)
- Real `propose_rule_change` (M10 — learned rules) and `start_investigation` (M13 — LangGraph).
- NL→SQL beyond the registry metrics; multi-turn slot filling; clarification questions (CI1).
- True token-by-token LLM streaming (D3 — narration is generated, then streamed; same SSE contract).
- Fuzzy/pg_trgm entity resolution + `customer_alias` (CI1) — M9 uses deterministic
  normalised substring matching.
- Chat-triggered KB capture (CI1), cost attribution columns (X1).

## 3. Files

### Backend
```
migrations/versions/0010_conversation_tools.py   app.conversation, app.message, app.tool_call_log,
                                                 app.decision (+ decision_kind/actor_kind enums)
valeri_api/tools/__init__.py
valeri_api/tools/base.py                ToolContext, ToolError/ToolPermissionError, ToolDefinition
valeri_api/tools/models.py              ToolCallLog (app.tool_call_log, SQLAlchemy)
valeri_api/tools/log.py                 append-only tool_call_log writer (success + failure)
valeri_api/tools/catalog.py             TOOLS registry + dispatch(): RBAC → validate → run → log
valeri_api/tools/query_metric.py        QueryMetricInput/Output + tool fn (semantic layer)
valeri_api/tools/compare_periods.py     ComparePeriodsInput/Output + SQL (both values + delta)
valeri_api/tools/list_signals.py        ListSignalsInput/Output (rep-scoped signal rows)
valeri_api/tools/explain_signal.py      ExplainSignalInput/Output (evidence + task + customer)
valeri_api/tools/get_customer_360.py    Customer360Input/Output (wraps metrics.dashboard)
valeri_api/tools/create_task_draft.py   CreateTaskDraftInput/Output (task + task_log + decision)
valeri_api/tools/stubs.py               propose_rule_change + start_investigation stubs
valeri_api/audit/decision.py            append-only app.decision writer (reused by M10)
valeri_api/audit/models.py (edit)       + Decision model
valeri_api/conversation/__init__.py
valeri_api/conversation/models.py       Conversation, Message (app schema)
valeri_api/conversation/schemas.py      IntentClassification, ChatAnswer, SSE event + API schemas
valeri_api/conversation/resolution.py   resolve_entities(text) → [(name, customer_id)], deterministic
valeri_api/conversation/intent.py       classify_intent(): mask → Tier-1 → validate → ai_log
valeri_api/conversation/answer.py       narrate_answer(): tool result → Bosnian + register (M6 discipline)
                                        + deterministic fallback templates per tool
valeri_api/conversation/service.py      handle_message(): persist → resolve → route → dispatch →
                                        narrate → persist reply → yield SSE events
valeri_api/api/chat.py                  POST /chat/sessions · POST .../messages (SSE) ·
                                        GET /chat/sessions · GET /chat/sessions/{id}
valeri_api/llm/prompts.py (edit)        + INTENT_SYSTEM_PROMPT, CHAT_ANSWER_SYSTEM_PROMPT
valeri_api/main.py (edit)               mount chat router
migrations/env.py (edit)                register conversation/tools/decision models
tests/tools/__init__.py
tests/tools/test_query_metric.py        contract + RBAC + logging (TDD, per /tool)
tests/tools/test_compare_periods.py     contract + RBAC + logging
tests/tools/test_list_signals.py        contract + RBAC + logging
tests/tools/test_explain_signal.py      contract + RBAC + logging
tests/tools/test_get_customer_360.py    contract + RBAC + logging
tests/tools/test_create_task_draft.py   mutation + decision + task_log + RBAC + logging
tests/tools/test_stubs.py               stubs return not-available, still logged
tests/test_chat.py                      the conversation acceptance tests
```

### Frontend
```
src/features/chat/ChatPage.tsx          thread + input + SSE wiring
src/features/chat/ChatMessage.tsx       register chip, narrative, tool card, EvidenceExpander
src/lib/api/sse.ts                      POST-SSE reader (fetch + ReadableStream parser)
src/lib/api/queries.ts (edit)           useChatSessions/useChatHistory/sendChatMessage
src/lib/api/types.ts (edit)             chat types + SSE event types
src/lib/i18n/bs.ts + en.ts (edit)       chat strings
src/routes.tsx (edit)                   /chat route
src/app/TopBar.tsx (edit)               GlobalSearch submit → /chat?q=
src/app/Sidebar.tsx (edit)              "Pitaj VALERI" → /chat
src/test/chat.test.tsx                  ChatMessage envelope + SSE rendering
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.conversation`, `app.message`, `app.tool_call_log` | **create** (0010) + writes | exactly per data-model.md; `tool_call_log.message_id` nullable (M13 agent calls tools outside chat) |
| `app.decision` + `decision_kind`/`actor_kind` enums | **create** (0010) + writes | **D1**: pulled forward from M10 because the `/tool` contract requires mutations to write a reversible decision; M10 builds learned_rule/suppression_hit on top |
| `app.task`, `audit.task_log` | write | `create_task_draft` (internal action, auto-allowed) |
| `core.*`, `core.customer_metrics`, `app.signal` | read | tool data sources (SQL/semantic only) |
| `audit.ai_log` | write | every intent + narration LLM call (M6 writer) |

One migration: `0010_conversation_tools`.

## 5. API touchpoints (per docs/api-spec.md M9)

| Endpoint | Method | Roles | Behaviour |
|---|---|---|---|
| `/chat/sessions` | POST | all authed | `{session_id}`; conversation owned by the user |
| `/chat/sessions` | GET | all authed | own sessions list (additive, D5) |
| `/chat/sessions/{id}` | GET | owner of the session | history: messages with register + tool_calls |
| `/chat/sessions/{id}/messages` | POST `{text}` | owner of the session | **SSE stream**: `tool_call` → `register` → `token` → `card?` → `done`; reply persisted with envelope |

Numbers in replies are tool outputs (SQL) passed through; the chat never returns an
LLM-computed figure (number contract enforced on narration).

## 6. Tests (TDD: tool contract tests written first, per `/tool`)

### `tests/tools/` (one file per tool; each has the 3 mandatory tests)
1. **Contract**: every number the tool returns == the same SQL run directly (to the cent).
2. **RBAC**: a sales_rep cannot reach data outside its scope (company-wide metrics blocked,
   other reps' customers blocked); owner/admin/finance pass; blocked calls raise typed errors.
3. **Logging**: one `tool_call_log` row per call — success AND failure/permission-denied.

Plus per tool: `create_task_draft` → task + task_log('created') + **reversible decision** row,
assignee = customer's rep; stubs → `{available: false}` + still logged.

### `tests/test_chat.py`
4. `test_bosnian_question_returns_sql_numbers_tagged_analiza` — **the milestone acceptance**:
   "Koliki je promet u zadnjih 30 dana?" → (fake Tier-1) intent=question/tool=query_metric →
   reply numbers == direct SQL, register == `analiza`, persisted in app.message.
5. `test_customer_question_resolves_and_masks` — "Koliki je promet kupca <real name>?" →
   entity resolved server-side; **prompts contain pseudonyms only** (no raw name in any
   LLM call or ai_log row); reply rehydrated with the real name.
6. `test_rep_blocked_from_finance_tools` — a rep asks a company-wide revenue question →
   tool dispatch raises permission error → polite Bosnian refusal reply, **no numbers**;
   blocked call logged in tool_call_log with ok=false.
7. `test_every_call_in_tool_call_log` — a multi-tool conversation: every dispatch (incl.
   failures) has a row with tool/args/latency/ok linked to the message.
8. `test_sse_event_sequence` — the stream yields tool_call → register → token → done in
   order; payloads match the persisted message.
9. `test_session_memory_and_history` — sessions persist; GET history returns messages with
   register + tool_calls; users only see their own sessions (404/403 otherwise).
10. `test_intent_fallback_on_invalid_llm_output` — persistently malformed router output →
    help-style fallback reply (no exception, no raw output shown).
11. `test_action_intent_creates_task_draft` — "Kreiraj zadatak za <customer>" → task exists,
    register card `akcija`, decision row written.
12. `test_stub_intents_reply_milestone_note` — feedback_config/investigation intents →
    "stiže u M10/M13" reply, register `analiza`.

### `src/test/chat.test.tsx` (web)
13. ChatMessage renders register chip + narrative + EvidenceExpander for tool results;
    user vs assistant alignment; SSE events append progressively; input disabled while streaming.

## 7. Acceptance criteria (IMPLEMENTATION-PLAN M9)

1. **A Bosnian question routes to query_metric/compare_periods and returns SQL-correct
   numbers tagged Analiza** (test 4).
2. **A rep is RBAC-blocked from finance tools** (tool tests #2 + test 6).
3. **Every call is in tool_call_log** (tool tests #3 + test 7).
4. PII masked in every chat LLM call (test 5); register on every reply (tests 4, 11, 12).
5. Full pytest + vitest + lint + CI green; **tool-catalog-guardian** PASS; **/numbers-check**
   clean; **principle-reviewer** PASS.

## 8. Principles compliance

| Principle | M9 impact |
|---|---|
| 1. No LLM-computed numbers | The model never queries the DB; it picks a tool + params. All numbers come from tools (SQL/semantic layer); narration passes the M6 number contract; `/numbers-check` greps conversation/ + llm/ for arithmetic. |
| 2. Evidence | `list_signals`/`explain_signal` return full signal evidence; chat cards carry it; query results include the period/filters they were computed for. |
| 3. Confidence | Intent classification carries confidence (low → fallback to help/clarification); signal tools pass through detection confidence; narration confidence → ai_log. |
| 4./5. No ERP writes; read-only | Tools read `core.*`/`app.*` only; the single mutation (`create_task_draft`) writes VALERI's own `app.task`. |
| 6. PII masking | Chat messages are masked **before** the intent/narration prompts (entities resolved server-side → pseudonyms); rehydration only for the stored human-facing reply. Tests assert no raw names in prompts/ai_log. |
| 7. Append-only logs | `app.tool_call_log` (every call, success+failure), `audit.ai_log` (every LLM call), `audit.task_log` (task creation), `app.decision` (mutations). No update/delete paths. |
| 8. Feedback loop | Conversation + tool logs are the substrate M10's dismissal/feedback flow builds on; intent `feedback_config` is routed (stub) from day one. |
| 9. Register tags | Every assistant message stores + streams a register; tool cards tagged (query results `analiza`, task drafts `akcija`); stubs reply `analiza`. |
| 10. Approval / internal autonomy | `create_task_draft` is an internal action (auto-allowed) but reversible + recorded as a visible `app.decision`; nothing customer-facing exists in chat (drafts for customers remain behind M7 approvals). |
| Conventions | Typed Pydantic everywhere (incl. all LLM I/O); thresholds untouched; no secrets; one migration; Bosnian-first replies. |

## 9. Open questions (owner decisions before implementation)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | **`app.decision` pulled forward into migration 0010.** The `/tool` contract (and tool-catalog-guardian) requires mutations to write a reversible decision; `create_task_draft` is a mutation. M10 then adds learned_rule/suppression_hit on top of the existing table. Alternative: defer the decision write to M10 and accept a guardian FAIL note in M9. | **pull the table forward** |
| **D2** | **"Finance tools" for rep blocking** = `query_metric`/`compare_periods` **without a customer scope** (company-wide revenue). Reps can still query **their own** customers' metrics; list/explain/360 stay rep-scoped. | as stated |
| **D3** | **SSE granularity**: the narration is generated fully (Tier-1, validated), then streamed as one `token` event. The SSE contract (`token`/`tool_call`/`register`/`card`/`done`) is final, so true incremental streaming can be added later without changing the frontend. | full-then-stream |
| **D4** | **Entity resolution in M9** = deterministic, normalised (lowercase, diacritic-insensitive) substring matching of customer names in the message (~80 customers — exhaustive scan is fine). pg_trgm fuzzy matching + aliases + clarifications belong to CI1. No match → company-wide question. | as stated |
| **D5** | **`GET /chat/sessions`** (list own sessions) added beyond api-spec — the chat screen needs it for the session list. | include |
| **D6** | **`create_task_draft` persists immediately** as an open `app.task` (internal action, auto-allowed by principle 10) with task_log + decision; the chat shows it as an `akcija` card. Alternative: an unpersisted draft card + a separate confirm endpoint. | persist immediately |

---
*After approval: Plan Mode (file-by-file implementation order), then TDD implementation, then tool-catalog-guardian + /numbers-check + principle-reviewer.*
