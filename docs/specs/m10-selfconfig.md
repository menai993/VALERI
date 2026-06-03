# Spec — M10: Self-configuration loop ("ignore that" → reversible rule)

**Milestone:** M10 · **Builds on:** M9 (chat + tool catalog + `app.decision`), M4 (scanner suppression hook) · **Status:** approved (D1–D6 OK'd by owner, 2026-06-03)

## 1. Objective

Close the **learning loop**: when a user dismisses an AI insight with a reason ("to je sezonski
kupac"), Tier-1 structures it into a **typed, narrowest-fit rule change** with a Bosnian
description, a SQL-computed predicted effect (blast radius) and an interpretation confidence;
**graduated autonomy** applies low-stakes suppressions immediately (reversibly) and demands a
one-tap confirm for high-value/broad scopes; every application writes an **active
`app.learned_rule` + an append-only reversible `app.decision`**; the scanner consults learned
rules and logs **`app.suppression_hit`** per suppression; **Undo** restores everything. This is
what makes VALERI self-configuring instead of static.

## 2. Scope

### In scope
1. **Migration 0011**: `app.suppression_hit` (per data-model.md) + `selfconfig` autonomy
   thresholds seeded into `app.rule_config` (D4).
2. **`selfconfig/` package**:
   - `proposer.py` — dismissal/feedback reason (masked) → Tier-1 → `RuleChangeProposal`
     (scope kind: `once|entity|category|threshold|conditional`, narrowest fit; Bosnian
     description; interpretation confidence); entity refs are pseudonyms, **resolved to ids
     server-side**.
   - `effect.py` — **SQL** blast radius: how many signals (last 90 days) the scope would have
     suppressed, by rule.
   - `autonomy.py` — auto-apply vs confirm, driven by `app.rule_config` (effect size,
     confidence, scope kind); customer-facing = never-auto (structural: suppressions are never
     customer-facing; documented).
   - `applier.py` — `apply_rule()` (learned_rule active + reversible decision + rule_config
     update for threshold kinds), `undo_rule()` (revert + new `undo` decision),
     `edit_scope()` (scope change + decision).
3. **Scanner hook completion** (`rules/engine.py`): suppressed drafts are now **written** to
   `app.signal` with `status='suppressed'` (evidence preserved for the M11 auditor) + one
   `app.suppression_hit` per suppression (D2); dedup extended so a suppressed key isn't
   re-inserted (repeat scans add hits to the existing suppressed signal).
4. **Dismissal flow**: `POST /signals/{id}/dismiss {reason_text}` → signal `dismissed` + its
   open task dismissed (D6) → proposal; **low-stakes proposals auto-apply in the same request**
   (D1), high-stakes return `requires_confirm` + blast radius → `POST /rules/apply` confirms.
5. **Chat wiring**: the `propose_rule_change` M9 stub becomes the **real tool** (same proposer
   flow); the `feedback_config` intent returns a real rule-proposal card.
6. **API**: dismiss/apply/learned-rules/undo/edit-scope/decisions per api-spec.md.
7. **Web**: the RuleCard becomes functional (proposal scope chips, Bosnian description, blast
   radius, confidence; Primijeni enabled; auto-applied confirmation state); dashboard dismiss
   wired end-to-end.

### Out of scope (deferred)
- The "Šta je VALERI naučio" AI-Report tab, decision feed UI, over-suppression auditor,
  expiry handling → **M11**.
- Engine evaluation of `conditional` scopes ("when": season=…) — proposals of this kind are
  stored (always confirm) but not yet consumed by the scanner (documented limitation, M11+).
- Learned rules for anything other than detection suppression / threshold change (e.g.
  task-routing rules).
- Cost attribution columns (X1), preferred-language enforcement (X2).

## 3. Files

### Backend
```
migrations/versions/0011_selfconfig.py     app.suppression_hit + selfconfig rule_config seeds
valeri_api/selfconfig/__init__.py
valeri_api/selfconfig/schemas.py           ProposedScope, RuleChangeProposal (LLM output),
                                           RuleChangeDraft (proposal + effect + autonomy),
                                           LearnedRuleRead, DecisionRead, API schemas
valeri_api/selfconfig/proposer.py          propose_from_dismissal()/propose_from_text():
                                           mask → Tier-1 → validate → resolve entity refs →
                                           effect estimate → autonomy → RuleChangeDraft
valeri_api/selfconfig/effect.py            estimate_effect(session, scope) → SQL counts
valeri_api/selfconfig/autonomy.py          decide_autonomy(scope, effect, confidence, config)
valeri_api/selfconfig/applier.py           apply_rule() / undo_rule() / edit_scope() —
                                           each writes learned_rule + reversible decision
valeri_api/rules/engine.py (edit)          suppressed drafts → status='suppressed' signal +
                                           suppression_hit; dedup includes suppressed keys
valeri_api/rules/models.py (edit)          + SuppressionHit model
valeri_api/tools/propose_rule_change.py    the REAL tool (replaces the stub): runs the proposer,
                                           auto-applies when autonomy allows (mutation → decision)
valeri_api/tools/stubs.py (edit)           only start_investigation remains
valeri_api/tools/catalog.py (edit)         register the real propose_rule_change
valeri_api/conversation/service.py (edit)  feedback_config → real tool → rule-proposal card
valeri_api/conversation/answer.py (edit)   narration/template for rule proposals
valeri_api/api/signals.py (edit)           + POST /signals/{id}/dismiss
valeri_api/api/rules.py                    POST /rules/apply · GET /learned-rules ·
                                           GET /learned-rules/{id} · PATCH .../scope ·
                                           POST .../undo · GET /audit/decisions
valeri_api/llm/prompts.py (edit)           + RULE_PROPOSAL_SYSTEM_PROMPT (Bosnian, JSON-only)
valeri_api/main.py + migrations/env.py (edits)
tests/test_selfconfig.py                   the acceptance tests (below)
tests/tools/test_propose_rule_change.py    contract/RBAC/logging for the real tool
tests/tools/test_stubs.py (edit)           start_investigation only
tests/test_chat.py (edit)                  feedback_config now yields a real proposal card
tests/test_scanner.py (edit)               suppression assertions updated for persisted
                                           suppressed signals + hits
```

### Frontend
```
src/components/widgets/RuleCard.tsx (rewrite)  proposal display: scope chips, Bosnian
                                               description, blast radius, confidence;
                                               Primijeni (enabled) / auto-applied state / Undo link
src/features/dashboard/DashboardPage.tsx (edit) dismiss → POST /signals/{id}/dismiss → RuleCard
src/lib/api/types.ts + queries.ts (edits)      dismiss/apply/learned-rules/undo hooks
src/lib/i18n/bs.ts + en.ts (edits)             selfconfig strings
src/test/rule-card.test.tsx                    functional RuleCard tests (replaces preview tests
                                               in ai-insight.test.tsx)
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.suppression_hit` | **create** (0011) + writes | exactly per data-model.md; `signal_id` references the **persisted suppressed signal** (D2) |
| `app.learned_rule` | write (applier) / read (engine, API) | table exists since M4; scope JSONB per data-model.md shape; `autonomy` = `auto_applied`/`confirmed` |
| `app.decision` | write (every apply/undo/edit) | exists since M9; kinds: `suppression`, `threshold_change`, `undo`; actor `valeri` (auto) or `user` (confirmed) |
| `app.signal` | write | dismissal → `status='dismissed'`; scanner now writes `status='suppressed'` rows |
| `app.task`, `audit.task_log` | write | dismissing a signal dismisses its open task (D6) |
| `app.rule_config` | **seed** (0011) + read + write | `selfconfig.*` autonomy thresholds (D4); threshold-kind rules update the target rule's config (reversibly) |
| `audit.ai_log` | write | every proposer LLM call (masked) |

One migration: `0011_selfconfig`.

## 5. API touchpoints (per docs/api-spec.md M10)

| Endpoint | Method | Roles | Behaviour |
|---|---|---|---|
| `/signals/{id}/dismiss` | POST `{reason_text}` | owner/admin; rep (own signals) | signal+task dismissed → proposal; **auto-applies** when autonomy allows (D1) → `{proposal, applied, learned_rule?, decision?, requires_confirm, effect_estimate}` |
| `/rules/apply` | POST `{draft}` | owner/admin | applies a pending (requires_confirm) draft → `{learned_rule, decision}`; 409 if already applied |
| `/learned-rules` | GET | owner/admin/finance | list: origin (signal/message), effect (hit count from SQL), status, autonomy |
| `/learned-rules/{id}` | GET | owner/admin/finance | detail + its `suppression_hit` rows |
| `/learned-rules/{id}/scope` | PATCH `{scope}` | owner/admin | edit scope → new decision |
| `/learned-rules/{id}/undo` | POST | owner/admin | revert → `status='reverted'` + `undo` decision |
| `/audit/decisions?kind=` | GET | owner/admin/finance | the append-only decision feed |

## 6. Tests (TDD: the four acceptance tests written first)

### `tests/test_selfconfig.py`
1. `test_dismissal_creates_exactly_one_reversible_decision_and_active_rule` — **acceptance**:
   dismiss a decline signal with reason "sezonski kupac" (fake Tier-1 proposes entity-scope) →
   EXACTLY ONE `app.decision` (reversible, kind=`suppression`) + ONE active `app.learned_rule`
   (autonomy=`auto_applied`); the signal is `dismissed`, its task is `dismissed`.
2. `test_scanner_suppresses_future_signal_and_logs_hit` — **acceptance**: with the learned rule
   active, clear signals and re-run the scan → the matching detection becomes a
   `status='suppressed'` signal (no task) + one `suppression_hit` linking rule→signal; other
   customers' signals fire normally.
3. `test_vague_broad_request_requires_confirm` — **acceptance**: a category-wide proposal
   (or low interpretation confidence) → `requires_confirm=true`, NOTHING applied (zero new
   learned_rules/decisions); then `POST /rules/apply` applies it (autonomy=`confirmed`).
4. `test_undo_restores` — **acceptance**: undo an active rule → `status='reverted'` + a NEW
   `undo` decision referencing the original; re-scan → the signal fires again (no suppression,
   no new hits).
5. `test_autonomy_boundary_lives_in_rule_config` — raising/lowering `selfconfig.*` thresholds
   flips the same proposal between auto-apply and confirm (no code change).
6. `test_effect_estimate_matches_sql` — the blast radius equals an independent SQL count.
7. `test_proposer_masks_pii` — proposer prompts + ai_log carry pseudonyms only; the applied
   rule's scope carries the REAL entity_id (server-side resolution).
8. `test_threshold_kind_updates_rule_config_reversibly` — a threshold proposal (confirm) →
   rule_config value changed + old value in the decision payload; undo restores the old value.
9. `test_edit_scope_writes_decision` — PATCH scope → scope updated + decision written.
10. `test_api_learned_rules_and_decisions` — list/detail (+hits), undo, decisions feed,
    RBAC (rep 403 on apply/undo), 404/409 envelopes.

### `tests/tools/test_propose_rule_change.py`
11. Contract (effect numbers == SQL) / RBAC (rep: own signals only) / logging (every call) /
    mutation (auto-applied proposal writes decision) — per the /tool scaffold.

### Edits
12. `tests/test_chat.py` — feedback_config intent now returns a rule-proposal card (not "M10").
13. `tests/test_scanner.py` — hand-inserted learned rule: suppressed signal is persisted with
    `status='suppressed'` + hit (was: silently skipped).

### Web (`src/test/rule-card.test.tsx`)
14. RuleCard renders proposal (scope chips, description, blast radius, confidence); Primijeni
    enabled and calls apply; auto-applied state shows confirmation + Undo; register `akcija`.

## 7. Acceptance criteria (IMPLEMENTATION-PLAN M10)

1. **A dismissal creates exactly one reversible decision + an active learned_rule** (test 1).
2. **The scanner suppresses the right future signal and logs suppression_hit** (test 2).
3. **Vague+broad triggers confirm** (test 3).
4. **Undo restores** (test 4).
5. Autonomy boundary in `rule_config`, never code (test 5); effect numbers from SQL (test 6);
   PII masked (test 7).
6. Full pytest + vitest + CI green; **selfconfig-reviewer**, **/decision-audit**,
   **principle-reviewer** all PASS.

## 8. Principles compliance

| Principle | M10 impact |
|---|---|
| 1. No LLM-computed numbers | The LLM proposes scope/description/confidence only; the predicted effect (blast radius) and hit counts are SQL; thresholds changed by threshold-kind rules are user-confirmed values, not model-computed. |
| 2. Evidence | Proposals carry the source signal + its evidence; suppressed signals keep full evidence (persisted with status='suppressed'); hits link rule→signal. |
| 3. Confidence | `interpretation_confidence` on every proposal (drives autonomy); low confidence → confirm required. |
| 4./5. No ERP writes; read-only | All writes stay in `app.*`. |
| 6. PII masking | Dismissal reasons + signal context are masked before the proposer prompt; entity refs are pseudonyms resolved server-side; tests assert no raw names in prompts/ai_log. |
| 7. Append-only logs | Every apply/undo/edit writes `app.decision` (INSERT-only); suppressions write `suppression_hit`; proposer calls write `ai_log`; dismissals write `task_log`. No UPDATE/DELETE on any audit table. |
| 8. Feedback loop | This IS the feedback loop: dismissals change future behaviour, visibly and reversibly. |
| 9. Register tags | Proposals/cards are `preporuka` (a suggested rule) until applied, then `akcija` + applied/pending status; inline confirmations always state what happened. |
| 10. Auto-apply boundary | Exactly per the principle: internal, reversible, decision-logged suppressions may auto-apply; high-value scope requires confirm; customer-facing never-auto (structurally N/A for suppressions; the boundary lives in `rule_config`). |
| Conventions | Autonomy thresholds in DB; typed Pydantic everywhere; one migration; Bosnian descriptions. |

## 9. Open questions (owner decisions before implementation)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | **Dismiss auto-applies low-stakes proposals in the same request** (returning the applied rule + inline confirmation); high-stakes return `requires_confirm` → `/rules/apply` is the confirm tap. Alternative: always two-step. | **auto-apply in dismiss** |
| **D2** | **Suppressed signals are persisted** (`status='suppressed'`, full evidence) and `suppression_hit` references them — the M11 auditor needs this; M4's "silently skip" behaviour changes. | **persist them** |
| **D3** | **Scope kinds in M10**: `once`/`entity`/`category` suppress rules work end-to-end; `threshold` kind applies as a reversible `rule_config` change; `conditional` is proposable + storable (always confirm) but not yet evaluated by the scanner (M11+). | as stated |
| **D4** | **Autonomy defaults** (in `rule_config`, rule=`selfconfig`): `auto_apply_max_effect`=10 (signals/90d), `auto_apply_min_confidence`=0.7, `confirm_kinds`=["category","threshold","conditional"] (only `once`/`entity` can auto-apply). | as stated |
| **D5** | **RBAC**: dismiss = owner/admin + rep (own signals); apply/undo/edit-scope = owner/admin; learned-rules + decisions views = owner/admin/finance. | as stated |
| **D6** | **Dismissing a signal also dismisses its open task** (one gesture, no orphan tasks). | yes |

---
*After approval: Plan Mode, then TDD implementation, then selfconfig-reviewer + /decision-audit + principle-reviewer.*
