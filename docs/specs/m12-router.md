# Spec — M12: Tiered LLM router (role-based + cascade)

**Milestone:** M12 · **Builds on:** M6 (gateway, masking, narrate_structured), M9–M11 (all LLM call sites exist) · **Status:** approved (D1–D6 defaults OK'd by owner, 2026-06-03)

## 1. Objective

Make model choice a **deliberate, logged, config-driven decision** instead of "everything goes to
Tier-1". Every LLM call declares a **task role**; the router maps roles to tiers (Haiku for
narration/intent/NL→rule/simple Q&A; Sonnet for the over-suppression re-check and future
investigations, Opus for the hardest), writes **`audit.llm_route_log`** for every decision, and can
**cascade-escalate** one tier up when the model reports low self-confidence or its output keeps
failing validation. Swapping a tier's underlying Claude model (Sonnet ↔ Opus) is config-only, and
PII masking is untouched by routing — it sits *before* the router in the call chain. This is the
cost lever: ~60–70% of calls stay on Haiku by construction, stable prompt prefixes are cached, and
the router is the single place future models plug into.

## 2. Scope

### In scope

1. **`llm/router/`**: role registry, role→tier mapping (DB-backed, never hard-coded), the
   routing decision, cascade escalation, and the append-only route log writer.
2. **Migration 0013**: `audit.llm_route_log` (exactly per data-model.md) + `llm_router`
   thresholds seeded into `app.rule_config`.
3. **Router integration** into the two LLM entry points (`narrate_structured`, `narrate_task`)
   and a one-line `role=` declaration at each of the 7 existing call sites.
4. **Cascade escalation** (one step max): low self-confidence OR validator-reject after the
   retry budget on the initial tier → re-run once on the next tier up; both decisions logged.
5. **Prompt caching**: `LiteLLMClient` marks the (stable) system prompt as cacheable via the
   Anthropic `cache_control` passthrough — the weekly scan/report bursts reuse the prefix.
6. **Tier model config**: `config.py` + `infra/litellm.config.yaml` + `.env` so each tier's
   underlying Claude model is pure configuration.
7. **`GET/PATCH /api/settings/llm`** (admin): tier→model view, role→tier mapping, escalation
   threshold, cascade on/off; **masking shown as locked-on and not changeable**; every PATCH
   writes a reversible `app.decision`.
8. **Web**: the Settings → "AI model" tab goes live (routing table, escalation, masking lock).

### Out of scope (deferred)

- **Batch API integration → X1** (`docs/llm-cost.md`). Rationale: the `ai_log.batched`/cost
  columns, the cost dashboard, and the acceptance test that Batch actually reduces cost all
  belong to X1; shipping half of it here would be unverifiable. M12 ships caching; X1 ships Batch.
  *(Owner decision D1.)*
- Investigation roles' actual usage (M13 — the roles and tiers are registered now, used then).
- Answer caching, per-feature daily caps, budgets (X1).
- Any change to masking, evidence, or register discipline (routing is orthogonal by design).

## 3. Files

### Backend

```
migrations/versions/0013_llm_router.py       audit.llm_route_log + llm_router rule_config seeds
                                             (role_tiers map, escalation_confidence_threshold 0.6,
                                              cascade_enabled true, cascade_max_escalations 1)
valeri_api/llm/router/__init__.py            re-exports
valeri_api/llm/router/roles.py               ROLE_* constants; DEFAULT_ROLE_TIERS; TIER_ORDER
                                             (tier1 < tier2 < tier2_strong)
valeri_api/llm/router/router.py              load_router_config(session) · initial_route(session,
                                             role, request_id) · escalate(session, route, reason,
                                             confidence) · client_for(route, override) — every
                                             decision → log_route()
valeri_api/audit/route_log.py                log_route(session, ...) append-only writer
valeri_api/audit/models.py (edit)            + LlmRouteLog model (audit.llm_route_log)
valeri_api/llm/client.py (edit)              LiteLLMClient(model=tier alias) + prompt-cache
                                             system-message structure; get_llm_client(tier="tier1")
valeri_api/llm/structured.py (edit)          + role param; router picks the client when none is
                                             injected; cascade on low-confidence / validator-reject
valeri_api/llm/narration.py (edit)           + role param (task narration goes through the router)
valeri_api/config.py (edit)                  + llm_tier2_model, llm_tier2_strong_model,
                                             llm_prompt_cache_enabled
valeri_api/api/settings.py (edit)            GET/PATCH /settings/llm (admin, decision per change,
                                             masking locked-on)
valeri_api/signals/pipeline.py (edit)        role="narration"           (1 line)
valeri_api/reports/builder.py (edit)         role="report_narration"    (1 line)
valeri_api/approvals/workflow.py (edit)      role="customer_draft"      (1 line)
valeri_api/conversation/intent.py (edit)     role="intent"              (1 line)
valeri_api/conversation/answer.py (edit)     role="simple_qa"           (1 line)
valeri_api/selfconfig/proposer.py (edit)     role="nl_rule"             (2 lines)
valeri_api/selfconfig/auditor.py (edit)      role="over_suppression_audit"  (1 line)
infra/litellm.config.yaml (edit)             tier model ids referenced from env vars
                                             (LLM_TIER*_MODEL) so a swap touches only .env
tests/test_router.py (new)                   TDD — the router test list (§6)
tests/test_settings_api.py (edit)            + /settings/llm endpoint tests
```

### Frontend

```
src/lib/api/types.ts + queries.ts (edits)    LlmSettings/LlmRoleTier types; useLlmSettings,
                                             usePatchLlmSettings
src/features/settings/SettingsPage.tsx (edit) live "AI model" tab: tier table, role→tier rows
                                             (admin-editable), escalation slider, masking lock
src/lib/i18n/bs.ts + en.ts (edits)           LLM settings strings
src/test/settings-llm.test.tsx (new)         renders routing config; masking locked; PATCH wired
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `audit.llm_route_log` | **create** (0013) + append-only writes | Exactly per data-model.md: request_id, task_role, chosen_tier, model, reason, confidence, at |
| `app.rule_config` | **seed** (0013) + read + write | rule=`llm_router`: `role_tiers` (JSONB map), `escalation_confidence_threshold` (0.6), `cascade_enabled` (true), `cascade_max_escalations` (1) |
| `app.decision` | write | every `/settings/llm` PATCH (reversible, old+new values) |
| `audit.ai_log` | read-only relationship | unchanged — ai_log keeps recording calls; route_log records *why that model* |

Migration **0013** is the one schema-changing migration of this milestone (one new table + seeds).

**Role → tier defaults** (D2; stored in `rule_config`, shown/edited in settings):

| Role | Tier | Used by | Share of call volume |
|---|---|---|---|
| `narration` | tier1 | task bodies (scan) | high |
| `intent` | tier1 | chat intent router | high |
| `simple_qa` | tier1 | chat answers | high |
| `nl_rule` | tier1 | rule proposals (dismiss/chat) | medium |
| `report_narration` | tier1 | weekly report sections | medium |
| `customer_draft` | tier1 | approval-gated message drafts | low |
| `over_suppression_audit` | **tier2** | M11 auditor (weekly) | low |
| `investigation` | **tier2** | M13 (registered now) | — |
| `investigation_synthesis` | **tier2_strong** | M13 hardest (registered now) | — |

→ every high/medium-volume role is Haiku; only the weekly audit (and future investigations) use
Sonnet/Opus. The ~60–70%-on-Haiku target holds **by construction** and is asserted in tests.

## 5. API touchpoints

- `GET /api/settings/llm` (admin) → `{provider, tiers: {tier1: {alias, model}, tier2: …,
  tier2_strong: …}, role_tiers: {…}, escalation_confidence_threshold, cascade_enabled,
  masking: "locked_on"}`. Tier→Claude-model mapping is read from config (infra-owned), shown
  read-only; role→tier and escalation values are editable.
- `PATCH /api/settings/llm` (admin) → `{role_tiers?, escalation_confidence_threshold?,
  cascade_enabled?}`; each change writes a reversible `app.decision`
  (kind=`threshold_change`); attempting to touch masking → 422 (`masking_locked`).
- No other endpoint changes. (Route-log reading/inspection is X1's cost dashboard.)

## 6. Tests (`tests/test_router.py`, TDD — the router is trust-critical infrastructure)

1. `test_each_role_maps_to_configured_tier` — every role in DEFAULT_ROLE_TIERS routes to its
   tier; the production client for that route carries the right LiteLLM alias
   (tier1/tier2/tier2_strong). *(acceptance 1)*
2. `test_role_tiers_live_in_rule_config` — flipping `over_suppression_audit` to tier1 in
   `rule_config` changes the route; nothing is hard-coded.
3. `test_haiku_share_by_construction` — all interactive + scan-volume roles (narration, intent,
   simple_qa, nl_rule, report_narration, customer_draft) map to tier1 in the defaults.
4. `test_cascade_escalates_on_low_confidence` — a scripted client returns a valid output with
   confidence below the threshold → the router escalates once → second route-log entry
   (reason=`low_confidence`), final result comes from the escalated call. *(acceptance 2)*
5. `test_cascade_escalates_on_validator_reject` — output fails schema/number validation through
   the retry budget on tier1 → escalation (reason=`validator_reject`) → tier2 result accepted.
6. `test_cascade_caps_at_one_escalation` — a tier2-routed role that keeps failing does NOT
   escalate past `cascade_max_escalations`; the failure surfaces as NarrationFailed (template
   fallbacks still protect callers).
7. `test_cascade_disabled_in_config` — `cascade_enabled=false` → no escalation, behaviour
   identical to M11.
8. `test_every_route_logged` — every `narrate_structured`/`narrate_task` call writes ≥1
   `llm_route_log` row (request_id, task_role, chosen_tier, model, reason); injected test
   clients log with reason=`injected_client`. *(acceptance 3)*
9. `test_route_log_is_append_only` — the writer only INSERTs; no update/delete path exists.
10. `test_tier_swap_is_config_only` — pointing `over_suppression_audit` at tier2_strong (the
    Sonnet→Opus swap) via config changes the routed model alias; **no code change**; and the
    M11 auditor masking test still passes through the routed path (PII intact). *(acceptance 4)*
11. `test_masking_unaffected_by_routing` — the same masked payload reaches the client regardless
    of tier; no raw customer name in any routed prompt (re-run the M6 PII assertions through
    the router).
12. `test_prompt_cache_message_structure` — `LiteLLMClient` marks the system prompt with
    `cache_control` (unit test on message construction; no network).
13. `test_existing_callers_backward_compatible` — M6–M11 test suites stay green: `client=`
    injection still works, default roles applied.

`tests/test_settings_api.py` additions:

14. `test_settings_llm_get_and_patch` — GET shows tiers/roles/escalation/masking-locked; PATCH
    (admin) changes a role tier + threshold, writes one reversible decision per change;
    sales_rep/finance → 403.
15. `test_settings_llm_masking_locked` — any attempt to disable masking via PATCH → 422.

Web (`src/test/settings-llm.test.tsx`):

16. The AI-model tab renders tiers, role mapping and escalation from the API; masking row shows
    locked-on; saving a role change calls PATCH.

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN M12)

1. **Each role maps to the right tier** — narration/intent/NL→rule/simple-Q&A → Haiku;
   over-suppression re-check (+ registered investigation roles) → Sonnet/Opus. *(tests 1–3)*
2. **Cascade escalates on low confidence** — and on validator-reject, capped, logged. *(tests 4–7)*
3. **Every route logged** — `audit.llm_route_log` row per decision. *(tests 8–9)*
4. **Swapping Sonnet↔Opus is config-only and masking holds.** *(tests 10–11)*

## 8. Principles compliance

| # | Principle | How M12 honors it |
|---|---|---|
| 1 | AI computes no numbers | Routing changes *which model* narrates — the number contract in `narrate_structured` applies identically on every tier; cascade re-validates on the higher tier |
| 2 | Evidence on signals/tasks | N/A — no signal/task creation changes |
| 3 | Confidence on conclusions | Self-reported confidence now also *drives* escalation; it keeps being logged in ai_log + route_log |
| 4 | No writes to source ERP | Router writes only `audit.llm_route_log` + reads `rule_config` |
| 5 | Read-only/staging | Unchanged |
| 6 | PII masking before LLM | Masking happens **before** `narrate_structured` builds prompts; the router only picks the client afterwards — structurally impossible for routing to bypass masking; explicit cross-tier masking tests |
| 7 | Append-only logs | `llm_route_log` is INSERT-only (like ai_log); settings PATCHes write decisions |
| 8 | Feedback loop | Low-confidence outputs trigger escalation — the system reacts to its own quality signal |
| 9 | Register/visibility | Unchanged — register tagging happens in the output schemas, not the router |
| 10 | Approval/reversible self-config | `/settings/llm` changes are admin-gated, reversible, decision-logged; masking cannot be disabled (locked) |

## 9. Open questions (decide before implementation)

- **D1 — Batch API deferred to X1.** M12 ships role routing + cascade + caching; the Batch API
  (with its cost instrumentation and "measurably cheaper" acceptance) ships in X1 where
  `ai_log.batched`/`cost_usd` live. OK?
- **D2 — Role→tier defaults** as in the §4 table (only the weekly auditor on Sonnet until M13).
  OK?
- **D3 — Cascade policy:** trigger = self-confidence < 0.6 OR validator-reject after the retry
  budget; max one escalation per call; thresholds in `rule_config`. OK?
- **D4 — Route log covers injected clients too** (tests/fakes log reason=`injected_client`), so
  "every route logged" is literally true and testable without the gateway. OK?
- **D5 — Tier→model mapping stays infra config** (litellm.config.yaml + .env, shown read-only in
  the API); the app-side settings PATCH changes *role→tier* and escalation only. The Sonnet↔Opus
  swap = pointing a role at `tier2_strong` (app config) **or** editing the yaml (infra config) —
  both are config-only. OK?
- **D6 — Web scope:** full admin editing of role→tier + escalation in the Settings tab (not just
  read-only display). OK?
