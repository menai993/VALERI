---
description: Scaffold a detection rule - spec in docs/rules/, thresholds in app.rule_config, labeled fixtures, tests first.
argument-hint: <name>
---

Scaffold the detection rule **$ARGUMENTS** for the VALERI rule engine
(`apps/api/valeri_api/rules/`), tests first (TDD — this is trust-critical code).

## Order of work

1. **Rule spec** — write `docs/rules/$ARGUMENTS.md`:
   - what the rule detects (business meaning, in plain language);
   - the exact SQL/metric logic (which tables/metrics from `docs/data-model.md` it reads);
   - every threshold/parameter with its default value and meaning;
   - the **evidence** payload shape it emits (invoices/lines/dates/values/period);
   - how **confidence** (0–1 + band) is derived;
   - guard conditions (what must NOT fire: e.g. seasonal customers, code-swapped articles);
   - the register tag of the resulting signal.
2. **Thresholds in `app.rule_config`** — every parameter from the spec is seeded as
   `(rule='$ARGUMENTS', param, value)` rows in a migration/seed. **Never hard-code a
   threshold in the rule body** (CLAUDE.md conventions).
3. **Fixtures** — `tests/fixtures/rules/$ARGUMENTS/` with at least three labeled cases:
   - `true_positive` — the rule MUST fire, with the expected evidence and confidence band;
   - `must_not_fire` — a case that superficially looks positive but must be guarded
     (seasonality, code-swap, etc.);
   - `low_confidence_borderline` — fires but with low confidence → softer task or none.
4. **Tests first** — `tests/rules/test_$ARGUMENTS.py` asserting, for each fixture:
   fire/no-fire, evidence rows exactly match the fixture's expected rows, confidence band
   correct, thresholds read from `rule_config` (test by changing a threshold and asserting
   behaviour changes), and that active `app.learned_rule` suppressions are consulted.
5. **Implementation** — `rules/$ARGUMENTS.py` emitting `app.signal` rows with evidence +
   confidence + register, until all tests pass.

## After implementing

Run the **principle-reviewer** subagent on the diff and include its report.
