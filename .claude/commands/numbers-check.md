---
description: Run the golden metric/tool tests and scan llm/ + conversation/ for arithmetic on business data (principle 1 enforcement).
---

Run the **numbers check** — the enforcement pass for principle 1 ("AI does not compute
financial numbers").

## Steps

1. **Golden tests** — run the metric and tool contract test suites:
   ```bash
   cd apps/api && uv run pytest tests/metrics/ tests/tools/ -v
   ```
   Every metric/tool number must equal its SQL fixture exactly. Report any failure verbatim.

2. **Static scan** — search `apps/api/valeri_api/llm/` and `apps/api/valeri_api/conversation/`
   (and any prompt templates) for places where business numbers could be computed outside
   SQL:
   - arithmetic operators applied to values that originate from LLM output;
   - numbers parsed out of model text (`int(`, `float(`, regex digit extraction on
     completions);
   - prompt instructions asking the model to calculate, sum, average, project, or score;
   - LLM output fields persisted/rendered as business figures without coming from a tool/SQL
     result.

3. **Report**:

```
# Numbers check — <date>

## Golden tests: PASS (N tests) | FAIL
<failures verbatim>

## Static scan: CLEAN | FINDINGS
| File:line | Code | Why it's a risk |

## Verdict: PASS | FAIL
```

A FAIL here is a bug by definition (CLAUDE.md hard rule 1), not a style issue. Do not soften
findings.
