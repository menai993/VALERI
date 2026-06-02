---
description: Verify every rule/config-changing path writes a reversible app.decision (principle 10 / conventions enforcement).
---

Run the **decision audit** — verify that every path which changes VALERI's behaviour writes
an append-only, reversible `app.decision`.

## Steps

1. **Enumerate config-changing paths.** Search `apps/api/valeri_api/` for every write to:
   - `app.rule_config` (threshold changes),
   - `app.learned_rule` (create / scope edit / revert / expire),
   - `app.approval` (approve / reject decisions),
   - any settings persistence (`/settings/*` handlers),
   - any scanner/selfconfig path that changes future detection behaviour.

2. **For each path found, verify in the same transaction/unit of work:**
   - an `app.decision` row is written (kind, actor, summary, payload);
   - `reversible=true` and the payload is sufficient to restore the previous state
     (or the decision is explicitly irreversible AND requires human confirmation);
   - undo paths write a new decision referencing the original (`reverted_decision_id`) —
     never delete or update existing decisions (append-only);
   - the decision is visible via `GET /audit/decisions`.

3. **Check the tests** — every config-changing path has a test asserting its decision write
   and a test asserting Undo restores the previous behaviour.

4. **Report**:

```
# Decision audit — <date>

| Path (file:line) | Writes decision | Reversible | Undo covered | Test exists | Verdict |
|---|---|---|---|---|---|

## Verdict: PASS | FAIL (N paths missing decisions)

## Details
<for each FAIL: what changes behaviour silently and what must be added>
```

A config change without a decision is invisible self-modification — the exact thing VALERI
promises never to do. Report every gap.
