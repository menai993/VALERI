# Spec — M11: "Šta je VALERI naučio" + over-suppression auditor

**Milestone:** M11 · **Builds on:** M10 (learned rules, suppression persistence, decisions API), M7 (weekly report), M4 (scanner) · **Status:** implemented (15 auditor + 10 selfconfig/report/dashboard tests; full backend 212 + web 49 green, 2026-06-03)

## 1. Objective

Make the learning loop **transparent and safe**. The owner sees every learned rule — where it
came from, what it actually hid (viewable evidence), its status — and can Undo or edit its scope
at any time. A scheduled **over-suppression auditor** re-examines suppressed streams with
SQL-computed drift checks and raises a visible **"Na provjeri"** decision when a suppressed
pattern has materially worsened since the rule was created, so a learned rule can never silently
hide a real problem forever. Expiry (`expires_at`) becomes a first-class lifecycle state, and the
weekly report's "Nedavno potisnuto" placeholder is filled with real numbers. This is the safety
half of self-configuration: M10 lets VALERI learn; M11 proves the owner stays in control.

## 2. Scope

### In scope

1. **Frontend tab** `AI Report → Šta je VALERI naučio`: `LearnedRuleCard` list (origin, effect
   with viewable suppressed signals, status, autonomy, Na provjeri flag, Undo, Edit-scope) + the
   decision feed (filterable by kind).
2. **Over-suppression auditor** (`selfconfig/auditor.py`): scheduled job; SQL-computed drift
   (value drift + volume drift); one `reactivation` decision per drifted rule ("Na provjeri"),
   Bosnian summary via Tier-1 (template fallback); dedup so a flag is raised once until resolved.
3. **"Zadrži pravilo"** (keep): the owner's way to resolve a Na provjeri flag without undoing —
   writes an `approval`-kind decision; the auditor will not re-flag unless drift worsens again
   after the keep.
4. **Expiry handling**: scan marks `active` rules with `expires_at <= now()` as `expired` +
   writes a `reactivation` decision (actor `valeri`); expired **threshold** rules restore the
   original `rule_config` value (same restore as Undo).
5. **Weekly report**: replace `_suppressed_placeholder_section()` with a real "Nedavno potisnuto"
   section (SQL counts + items); fill the dashboard's `recently_suppressed` field (placeholder
   since M8).
6. **M10 carried fixes** (both affect what this tab displays):
   a. `effect.py` category matching aligned with `engine.py` (`category_name` OR `segment`);
   b. `edit_scope` on threshold-kind rules → 409 guard (scope edits are for suppress rules only).

### Out of scope (deferred)

- Tier-2 routing for the auditor (M12 — M11 uses the existing Tier-1 narration path).
- Auditing of `conditional` scopes (stored-only per M10 D3; no scanner semantics yet).
- Investigations tab content (M13). Phase-2 widgets. Any new chat intents.
- Editing a rule's expiry date from the UI (Undo / re-create covers the need).

## 3. Files

### Backend

```
migrations/versions/0012_auditor_config.py   seed selfconfig audit thresholds into app.rule_config
                                             (audit_drift_factor, audit_volume_factor, audit_min_hits)
valeri_api/selfconfig/auditor.py             NEW — audit_suppressions(session, client) -> AuditResult:
                                             expire_rules() · compute_drift() (SQL) · raise/skip
                                             Na provjeri decisions · Tier-1 Bosnian summary
valeri_api/selfconfig/applier.py (edit)      keep_rule(session, rule_id, user) -> approval decision;
                                             expire restore reuses _restore_threshold(); edit_scope
                                             threshold guard (409)
valeri_api/selfconfig/effect.py (edit)       category scope matches category_name OR segment (6a)
valeri_api/selfconfig/schemas.py (edit)      + AuditResult, DriftReport, SuppressionHitDetail
                                             (+evidence/customer), LearnedRuleRead.na_provjeri,
                                             LearnedRuleRead.origin (source customer/message)
valeri_api/scanner/scan.py (edit)            run_scan() calls expire_rules() before loading suppressions
valeri_api/scanner/scheduler.py (edit)       + audit job (weekly, after the Sunday cycle) and
                                             audit_suppressions() inside run_weekly_cycle()
valeri_api/reports/builder.py (edit)         _suppressed_section(session, week) — real data + Na provjeri note
valeri_api/metrics/dashboard.py (edit)       recently_suppressed = last N suppression hits (SQL)
valeri_api/metrics/schemas.py (edit)         recently_suppressed row shape
valeri_api/api/rules.py (edit)               list/detail: + na_provjeri flag, origin fields, hit evidence;
                                             + POST /learned-rules/{id}/keep
valeri_api/llm/prompts.py (edit)             + AUDIT_SUMMARY_SYSTEM_PROMPT (Bosnian, numbers verbatim)
tests/test_auditor.py                        NEW — the auditor acceptance tests (TDD, §6)
tests/test_selfconfig.py (edit)              + keep/threshold-guard/API-extension tests
tests/test_reports.py (edit)                 + recently-suppressed section tests
tests/test_scanner.py (edit)                 + expiry status-transition assertions
tests/test_dashboard.py (edit)               + recently_suppressed payload test
```

### Frontend

```
src/components/widgets/LearnedRuleCard.tsx   NEW — per frontend-spec §4: origin, effect (expandable
                                             "what it hid"), status/autonomy badges, Na provjeri flag,
                                             Undo / Edit-scope / Zadrži actions
src/features/ai-report/LearnedTab.tsx        NEW — LearnedRuleCard list + decision feed
src/features/ai-report/AIReportPage.tsx (edit)  mount LearnedTab (replaces the M10 placeholder)
src/lib/api/types.ts (edit)                  LearnedRule.na_provjeri/origin, SuppressionHitDetail,
                                             dashboard recently_suppressed row
src/lib/api/queries.ts (edit)                useLearnedRules, useLearnedRuleDetail, useDecisions,
                                             useEditScopeMutation, useKeepRuleMutation
src/lib/i18n/bs.ts + en.ts (edits)           learned-tab strings (replace learned_m10 placeholder)
src/test/learned-rules.test.tsx              NEW — tab renders origin/effect/status/Na provjeri;
                                             Undo + Keep call the API; what-it-hid expands
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `app.rule_config` | **seed** (0012) + read | `selfconfig.audit_drift_factor` (default 0.7), `selfconfig.audit_volume_factor` (default 3), `selfconfig.audit_min_hits` (default 2) — thresholds never in code |
| `app.learned_rule` | read + write | status transition `active → expired` (expiry); no schema change |
| `app.suppression_hit` | read | the auditor's raw material; joined to suppressed signals for drift + "what it hid" |
| `app.signal` | read | suppressed signals' stored evidence = the drift baseline & current value |
| `app.decision` | write (append-only) | `reactivation` (Na provjeri + expiry), `approval` (keep); all with Bosnian summary + payload |
| `app.owner_report` | write | the filled "nedavno_potisnuto" section |
| `audit.ai_log` | write | every auditor LLM call (masked) |

**No new tables. Migration 0012 is seed-only** (rule_config rows), keeping "one migration per
schema-changing milestone" intact — this milestone changes no schema.

**Decision-kind mapping (no enum change):** drift flag → `reactivation` (payload
`{"review": true, ...}`); expiry → `reactivation` (payload `{"expired": true, ...}`);
keep → `approval` (payload references the reactivation decision it resolves).

## 5. API touchpoints

No new endpoint groups — M10's endpoints are extended (api-spec.md lists them under M10–M11):

- `GET /learned-rules` — each item gains `na_provjeri: bool` (SQL EXISTS over unresolved
  reactivation decisions) and `origin: {source_signal_id, source_customer_name, source_message_id,
  created_by_name}` (rehydrated names — this is human-facing).
- `GET /learned-rules/{id}` — `hits[]` gain `rule`, `customer_name`, `evidence`, `confidence` from
  the suppressed signal ("what it hid, viewable").
- `POST /learned-rules/{id}/keep` — **new**: resolves a Na provjeri flag, writes an `approval`
  decision; owner/admin only; 409 if the rule has no open flag.
- `PATCH /learned-rules/{id}/scope` — 409 for threshold-kind rules (guard 6b).
- `GET /reports/owner/weekly` / `GET /dashboard` — sections/fields now carry real suppression data.

## 6. Tests (TDD — auditor and expiry are trust-critical, written first)

### `tests/test_auditor.py` (new)

1. `test_value_drift_detection_matches_sql` — plant a drifted stream (suppressed signals whose
   `value/baseline` ratio worsened beyond `audit_drift_factor` vs. at-suppression); auditor flags
   exactly that rule; the drift numbers in the decision payload equal direct SQL.
2. `test_volume_drift_detection` — a rule whose actual hits ≥ `audit_volume_factor` × predicted
   effect is flagged even without value drift.
3. `test_stable_stream_not_flagged` — suppressed signals with an unchanged pattern → no decision.
4. `test_na_provjeri_decision_shape_and_dedup` — exactly ONE `reactivation` decision per drifted
   rule (actor `valeri`, Bosnian summary, payload: rule id + drift evidence); re-running the
   auditor does not duplicate the flag.
5. `test_keep_resolves_flag_and_auditor_respects_it` — `keep_rule()` writes an `approval` decision;
   the auditor does not re-flag unless drift worsens after the keep timestamp.
6. `test_undo_resolves_flag` — undoing a flagged rule means the auditor no longer considers it.
7. `test_expired_rules_transition_and_stop_suppressing` — an `active` rule past `expires_at`:
   next scan marks it `expired` + writes a reactivation decision + the signal fires again;
   an expired **threshold** rule restores the original `rule_config` value.
8. `test_auditor_thresholds_live_in_rule_config` — tightening `audit_drift_factor` in DB changes
   what gets flagged; nothing is hard-coded.
9. `test_auditor_masks_pii` — auditor prompts contain pseudonyms only; ai_log rows are clean.
10. `test_auditor_narration_falls_back_to_template` — LLM failure → the decision is still written
    with a deterministic Bosnian template summary.
11. `test_scheduler_has_audit_job` — the scheduler exposes the audit job; `run_weekly_cycle`
    includes the audit step.

### `tests/test_selfconfig.py` (additions)

12. `test_keep_rule_requires_open_flag` — keep on a rule without a flag → `InvalidRuleState`/409.
13. `test_edit_scope_threshold_guard` — scope edit on a threshold rule → 409, no decision written.
14. `test_api_learned_rules_carry_origin_and_na_provjeri` — list/detail responses include origin
    (rehydrated names), na_provjeri flag, and hit evidence.
15. `test_effect_estimate_category_matches_engine` — effect counts for a category scope equal what
    the engine would actually suppress (fix 6a).

### `tests/test_reports.py` / `tests/test_dashboard.py` (additions)

16. `test_recently_suppressed_section_filled` — a week with suppression hits → section items +
    counts equal SQL; the Na provjeri note appears when a flag is open.
17. `test_recently_suppressed_section_empty_is_honest` — no hits → explicit empty narrative,
    `placeholder` flag gone.
18. `test_dashboard_recently_suppressed_payload` — dashboard rows equal SQL (rule description,
    customer, hit count).

### `src/test/learned-rules.test.tsx` (new, web)

19. Tab renders LearnedRuleCards with origin, effect count, status badge, Na provjeri flag.
20. "Šta je sakriveno" expander shows the suppressed signals' evidence (from the detail endpoint).
21. Undo and Zadrži buttons call their endpoints and invalidate the list.
22. Decision feed renders kinds/actors/summaries; filter by kind works.

## 7. Acceptance criteria (from IMPLEMENTATION-PLAN M11)

1. **The screen renders origin/effect** — every learned rule shows where it came from and what it
   hid, with evidence one tap away. *(tests 14, 19, 20)*
2. **Undo works** — from the tab, undoing reverts the rule, writes the decision, and signals fire
   again. *(tests 6, 21 + M10's test_undo_restores still green)*
3. **The auditor re-surfaces a deliberately drifted suppressed stream** — as a visible Na provjeri
   decision with SQL-computed drift evidence. *(tests 1, 2, 4)*
4. **Expired rules stop suppressing** — and are visibly marked expired; thresholds restore.
   *(test 7 + M4's expiry test still green)*

## 8. Principles compliance

| # | Principle | How M11 honors it |
|---|---|---|
| 1 | AI computes no numbers | Drift detection is pure SQL/Python over stored evidence; the LLM only narrates the already-computed drift; number contract enforced on summaries |
| 2 | Evidence on every signal/task | The Na provjeri decision payload carries the exact suppressed signal ids + drift values; "what it hid" shows stored evidence |
| 3 | Confidence on every conclusion | Suppressed signals keep their confidence; drift flags carry the computed drift factor (deterministic, not a model guess) |
| 4 | No writes to source ERP | Auditor writes only `app.decision` / `app.learned_rule.status` |
| 5 | Read-only/staging access | Unchanged; reads core/app only |
| 6 | PII masking before LLM | Auditor prompts use pseudonyms (build_masked_payload path); rehydrated names only in human-facing API/report output |
| 7 | Append-only logs | Flags, keeps, expirations are all new `app.decision` rows; nothing is updated or deleted; ai_log per LLM call |
| 8 | Feedback loop is core | This IS the loop's safety valve: learn (M10) → watch (auditor) → re-surface or expire |
| 9 | Register/visibility | Na provjeri appears in the decision feed + on the card + in the weekly report; section register `analiza`; keep/undo are explicit user actions |
| 10 | Approval for external; self-config reversible+visible | The auditor never undoes a rule itself — it only flags; resolution (undo/keep) is the owner's explicit, logged, reversible action |

## 9. Open questions (decide before implementation)

- **D1 — Drift definition.** Value drift = latest suppressed evidence ratio ≤ `audit_drift_factor`
  × at-suppression ratio (default 0.7 — i.e. the suppressed metric worsened by 30%+); volume
  drift = actual hits ≥ `audit_volume_factor` × predicted effect (default 3×). Both SQL, both
  tunable in rule_config. OK?
- **D2 — Na provjeri lifecycle.** Flag = `reactivation` decision; rule stays `active` (keeps
  suppressing) until the owner acts; resolution = **Undo** (stop suppressing) or **Zadrži**
  (approval decision, keep suppressing). The auditor never changes behaviour on its own. OK, or
  should a flagged rule stop suppressing immediately until the owner decides?
- **D3 — Expiry runs in every scan** (daily + weekly), so an expired rule never suppresses even
  one extra day. Decision actor `valeri`, kind `reactivation`, payload `{"expired": true}`. OK?
- **D4 — Auditor schedule.** Weekly, as part of the Sunday cycle (scan → tasks → report → audit)
  plus its own scheduler job id (`over_suppression_audit`). Daily would cost more LLM calls for
  little gain. OK?
- **D5 — Auditor narration tier.** Existing Tier-1 narration path with template fallback (M12
  moves it to Tier-2 routing). OK?
- **D6 — Dashboard `recently_suppressed`.** Last 10 suppression hits (rule description, customer,
  date), shown as a quiet list under the AI-insights card. OK, or leave the dashboard untouched
  and only fill the weekly report?
