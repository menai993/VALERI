# CSA — Self-Configuring Conversational Agent (spec, for review)

**Status:** DRAFT — awaiting owner review. No code until approved, then Plan Mode.
**Builds on:** M3 (semantic registry), M9 (chat/tools), M10–M11 (self-config + reversible decisions), M12 (router), M13 (investigation agent). **Companion:** `docs/architecture.md`, `docs/principles.md`, `docs/client-intelligence.md` §8 (clarification policy).

## 1. Problem (what triggered this)

The chat answers open-ended questions with irrelevant data because the intent router maps **every** question onto a fixed set of 8 metrics/tools, and **force-fits** when nothing matches instead of admitting a gap. Concrete failure: *"koji se artikli najviše prodaju?"* — there is **no article-ranking capability** in the semantic registry, so the router returns turnover numbers (wrong) or the generic fallback. A fixed tool set will not cover the long tail of real questions.

Owner decision (recorded): build the **full self-configuring agent now**, and **allow a guarded web tool** for investigations.

## 2. Goal

The agent should: (a) **know its own capabilities** (introspect the platform), (b) **plan how to get the answer** from those capabilities, (c) **collect the data** in a bounded multi-step loop, (d) **admit and self-configure** when a capability is missing (propose a new one, reversibly, for approval), and (e) optionally **consult the internet** for non-PII context — all **without ever violating the hard rules**.

### The one inviolable limit
**The LLM never writes free SQL and never computes a business number.** "Self-configuring" = the agent reasons over a **declarative capability catalog** (the semantic registry + tool catalog) and, when a capability is missing, **drafts a new metric definition that a human approves** before it is ever executable. Numbers always come from the validated query builder. This keeps Principles 1, 6, 7, 9, 10 intact.

## 3. Design

### 3.1 Capability self-description (introspection)
- A `capabilities` service exposes the **semantic registry** (metric name, description_bs, entity, grain, params, RBAC scope) **+ the safe tool catalog** (name, description, params, `mutates`) as one machine-readable catalog.
- The planner prompt is built **from this catalog at runtime** (not hard-coded lists), so adding a capability automatically teaches the agent. Powers an honest answer to *"šta me možeš pitati?"*.
- New read-only tool `describe_capabilities` (no numbers) so the agent can introspect mid-conversation.

### 3.2 New metrics (the declarative self-config surface — proves "capabilities are data")
Add to `semantic/registry.yaml` (YAML + one SQL block each, no new Python):
- `top_articles` — articles ranked by revenue or quantity over a period; optional `segment`/`category_id`/`customer_id`. (Directly fixes the failing question.)
- `article_catalog` — list of active articles/categories ("koje artikle imamo").
- `category_sales` — sales by category over a period.
- `top_customers` — customers ranked by turnover (symmetry; reuses turnover SQL).
Each ships with a golden test (output == SQL fixture).

### 3.3 Agentic chat (replace the brittle single-shot router)
- Promote chat from `intent → one tool` to a **bounded plan → act(loop) → synthesize** flow, reusing the **M13 investigation agent** machinery (LangGraph, caps, checkpointer, masking, number contract). Simple questions still resolve in one tool call (cheap path); multi-step questions use the loop.
- **Slot/context memory:** carry the active entity + period across turns (fixes "zadnjih 60 dana" losing the "articles" intent). Reuse the clarification policy (`client-intelligence.md` §8) when a slot is ambiguous — ask one short question, don't guess.
- **Honesty gate:** when no capability covers the question, the agent says so (*"To još ne znam izračunati"*) and offers a **capability proposal** (3.4) — it never force-fits a wrong tool.

### 3.4 Capability self-configuration (the core new idea, kept safe)
- When the agent detects an **unmet, answerable-from-data** gap, it **drafts a metric proposal**: a name, Bosnian description, the entities/params, and a **candidate SQL** built only over known `core.*`/`app.*` tables (schema given to the model; model proposes, does not execute).
- The proposal is a **reversible, logged `app.decision`** (+ a new `app.capability_proposal` row) — **inactive until a human approves**. On approval it is validated by the query builder and added to the registry (the agent's vocabulary grows). This mirrors the M10 learned-rule loop: *auto-draft, human-confirm, reversible, visible*.
- **Guardrails:** proposed SQL is read-only, parameterised, validated (no DDL/DML, allowlisted tables, `EXPLAIN`-checked) before activation; numbers still flow through the query builder; activation is owner-gated (never auto). This is how the agent "learns to get new data" without ever running arbitrary SQL.

### 3.5 Guarded web tool (`search_web`) — investigation agent only
- Read-only `search_web`/`fetch_url` in the safe catalog, usable **only by the investigation agent**, for **general/market context** (e.g. "industry hygiene-supply trends").
- **Guardrails (load-bearing):** an outbound scrubber + the existing masking ensure **no customer/business identifiers, PII, or SQL-computed figures leave the building**; an allowlist + per-day cap (`rule_config`); every query + result logged to `audit.ai_log` (`feature='web_search'`) and `tool_call_log`; results are **evidence/text with citations, never numbers** (Principle 1 unchanged); HITL stays for any external draft. ZDR posture preserved (only masked, non-business queries egress).

## 4. Data-model touchpoints (additive; one migration)
- `app.capability_proposal` (id, name, description, kind=`metric|tool`, definition JSONB (params + candidate SQL), status `proposed|active|rejected`, `decision_id`, created_by, timestamps).
- Reuse `app.decision` (reversible) for every capability activation/rejection and `audit.ai_log`/`audit.tool_call_log` for web calls.
- `rule_config`: `web_search.daily_cap`, `web_search.allowlist`, agent loop/token caps for chat.
- Registry: keep YAML as the seed; **active proposals materialise into a DB-backed registry overlay** so admin/agent-added metrics persist (decision point D2).

## 5. API (additive; per `api-spec.md` conventions)
- `GET /chat/capabilities` → the capability catalog (introspection).
- `POST /chat/.../messages` → unchanged contract; gains plan/act SSE events + an inline `capability_proposal` card when a gap is found.
- `GET /capabilities/proposals`, `POST /capabilities/proposals/{id}/approve|reject` (admin) → writes a reversible decision; approve activates the metric.
- `GET /documents/search` style `search_web` is internal to the agent (not a public endpoint); admin sees its usage via the existing LLM-cost/admin views.

## 6. Frontend (additive; per `frontend-spec.md`)
- Chat: render plan/act steps (like the investigation trace), the honest "can't yet" state, and an inline **CapabilityProposalCard** (Primijeni/Odbij → approval).
- A **"Mogućnosti" (Capabilities)** admin view: list active metrics/tools + pending capability proposals with their candidate SQL (approve/reject, reversible).
- Investigation report: cited web passages link out (with a "vanjski izvor" badge).

## 7. Principles & guardrails (explicit compliance)
1. **Numbers from SQL only** — agent plans/picks/narrates; the validated query builder computes. Proposed metrics are human-approved SQL, never model-executed ad hoc.
2. **Evidence + confidence** on every answer/finding; web results carry source citations.
6. **PII masking** before any LLM **and** any web call; outbound scrubber on `search_web`.
7. **Append-only logs** — every capability proposal/activation is a reversible `decision`; every web call hits `ai_log`/`tool_call_log`.
9/10. **Register tags**; capability activation and any external/customer-facing action are **human-approved, reversible, visible** (never auto).
- RBAC on every tool/metric (a rep can't reach finance-wide metrics or approve capabilities). Bounded agent loop (caps, checkpointer) per M13.

## 8. Tests (TDD on trust-critical paths)
- Golden: `top_articles`/`category_sales`/`article_catalog`/`top_customers` outputs == SQL fixtures (to the unit).
- Chat: *"koji se artikli najviše prodaju?"* → routes to `top_articles`, returns SQL-correct ranking tagged Analiza (the regression that started this).
- Honesty: an unsupported question → no force-fit; agent emits a `capability_proposal` (a reversible decision; inactive until approved); approving it activates the metric and the next ask is answered.
- Introspection: `describe_capabilities` lists exactly the registered metrics/tools (no hallucinated ones).
- Web tool: outbound payload assert — **no PII/business identifier/number** egresses; results are text+citation; daily cap enforced; every call logged.
- Agent: loop/token caps enforced; numbers in any answer all trace to a tool/SQL result (number-contract test extended to the chat agent).
- Decision audit: every capability activation/rejection writes a reversible `app.decision`; Undo restores.

## 9. Build order (phased, each gated by its tests + reviewers)
1. **Capabilities + the failing-question fix:** add the new metrics (golden tests first), the capability catalog/introspection, build the planner prompt from the catalog, and the honesty gate (no force-fit). *Ships the immediate value.*
2. **Agentic chat:** route non-trivial questions through the bounded plan→act→synthesize loop (reuse M13) with slot/context memory + clarifications.
3. **Capability self-configuration:** `capability_proposal` + reversible decision + admin approval + registry overlay + the CapabilityProposalCard.
4. **Guarded web tool:** `search_web` for the investigation agent with the outbound scrubber, allowlist/caps, logging, citations, and the cost-dashboard hook.

## 10. Decision defaults (change before/at review)
- **D1 — Capability proposals are never auto-activated** (owner approves; reversible). *Default: human-gated, matching self-config discipline.*
- **D2 — Registry storage:** keep YAML as seed + a DB overlay for approved proposals (so the agent's learned capabilities persist and are admin-editable). *Default: yes, DB overlay.*
- **D3 — Web tool scope:** investigation agent only (not live chat), allowlisted domains, daily cap, fully masked/scrubbed outbound. *Default: as stated.*
- **D4 — Chat agent cost:** keep the cheap single-tool path for simple questions; only escalate to the plan→act loop when the planner needs >1 capability (cost lever per `docs/llm-cost.md`). *Default: yes.*

---
**Next step:** your review of this spec (esp. D1–D4 and the "no free SQL / human-approved metric" boundary). On approval I'll enter Plan Mode (files, functions, order) before writing any code.
