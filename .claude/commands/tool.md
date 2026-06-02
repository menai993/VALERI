---
description: Scaffold a safe tool (typed, RBAC-checked, logged, SQL-only) with a contract test, then run tool-catalog-guardian.
argument-hint: <name>
---

Scaffold the safe tool **$ARGUMENTS** in `apps/api/valeri_api/tools/`, following the tool
catalog rules (CLAUDE.md "How the model touches data", `docs/architecture.md` §2, and
principle 1).

## What to generate

1. **`tools/$ARGUMENTS.py`** containing:
   - `class {Name}Input(BaseModel)` — typed, validated Pydantic v2 input (no free-form dicts).
   - `class {Name}Output(BaseModel)` — typed Pydantic v2 output.
   - `def $ARGUMENTS(input: {Name}Input, ctx: ToolContext) -> {Name}Output` where the body:
     a. **RBAC check** first — verify `ctx.user` role/ownership; raise a typed
        permission error otherwise.
     b. Gets every figure from **deterministic SQL / the semantic layer** — never from an
        LLM, never computed by parsing model output.
     c. Writes **`app.tool_call_log`** (tool, args, result_ref, latency_ms, ok) on success
        AND failure.
     d. If the tool mutates state (drafts, proposals): write an append-only, **reversible**
        `app.decision` and never touch any source/ERP system.
2. **Registration** in the tool catalog registry so the conversation layer can dispatch it.
3. **`tests/tools/test_$ARGUMENTS.py`** — written BEFORE the implementation (TDD):
   - a **contract test** asserting every number the tool returns equals the result of the
     same SQL run directly against the test DB (to the cent);
   - an **RBAC test** asserting a sales_rep cannot reach data outside its scope;
   - a **logging test** asserting a `tool_call_log` row is written per call (success and
     failure).

## After implementing

Run the **tool-catalog-guardian** subagent on the diff and include its report. If it reports
FAIL, fix and re-run before presenting the result.
