# VALERI — Acceptance Report

The execution of the acceptance suite from `docs/IMPLEMENTATION-PLAN.md`, item by
item, with test evidence. Produced at M14 (the final hardening milestone), before
the Ultra Higijena pilot.

- **Date:** 2026-06-03
- **Branch:** `claude/amazing-bell-skOEL`
- **Milestones covered:** M0–M14 (the full MVP + conversation + self-config +
  routing + investigation + hardening plan)
- **Suites:** backend `pytest` (PostgreSQL 16) · web `vitest`
- **Result:** backend **250 passed, 1 skipped (251 collected)** · web **56 passed**
- **Lint/build:** `ruff` + `black` clean · `eslint` clean · `vite build` clean
- **Migrations:** 0001 → 0015, up/down cycle verified

---

## How to reproduce

```sh
# backend
cd apps/api
export DATABASE_URL="postgresql+psycopg://valeri:valeri@localhost:5432/valeri_test"
uv run pytest -q

# web
cd apps/web
npx vitest run
```

---

## Acceptance items (from the plan)

### MVP (after M8)

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Numbers match the source export to the cent | **PASS** | `tests/test_ingest.py` — double-import is idempotent; totals preserved to the cent |
| 2 | A sampled customer's model is correct, no invented links | **PASS** | `tests/test_capability_a.py` — enumerates legal entity, objects, 12-month invoices, assigned rep with no invented relationships |
| 3 | Lost-article detection correct; code-swaps not flagged | **PASS** | `tests/test_scanner.py` — planted lost articles fire; code-swapped retired codes never flagged |
| 4 | Decline-vs-seasonal accuracy with rule explanations | **PASS** | `tests/test_scanner.py` — planted declines fire, seasonal cafés do not; every signal carries evidence + confidence + register |
| 5 | The weekly scan surfaces signals with no user query | **PASS** | `tests/test_scanner.py` (scheduled scan) + `tests/test_reports.py` (weekly owner report aggregates) |
| 6 | One task per signal with the correct assignee | **PASS** | `tests/test_tasks.py` — exactly one task per signal; assignee = customer's rep; owner_cc for top-10; task_log lifecycle complete |
| 7 | 100% of customer-facing comms pass human approval | **PASS** | `tests/test_approvals.py` + `tests/test_reports.py` — drafts are `pending_approval`; nothing customer-facing sends without an approval row; internal actions auto-run |
| 8 | Over 4–6 weeks the share of rejected/"useless" tasks falls | **PILOT MEASUREMENT** | Method below — requires real usage over time; the mechanism (task_feedback) ships and is tested in `tests/test_tasks.py` |

### Full (after M14), additionally

| # | Item | Result | Evidence |
|---|---|---|---|
| 9 | A Bosnian question returns SQL-correct numbers, register-tagged, every tool call logged | **PASS** | `tests/test_chat.py` — intent routes to metric tools, numbers from SQL, reply tagged Analiza, every call in `tool_call_log`; RBAC blocks finance tools from a rep |
| 10 | A dismissal → one reversible decision + active learned rule, right future signal suppressed, Undo restores | **PASS** | `tests/test_selfconfig.py` — exactly one reversible decision + active rule; scanner suppresses the right future signal + logs `suppression_hit`; vague+broad requires confirm; Undo restores |
| 11 | The auditor re-surfaces a drifted suppressed stream | **PASS** | `tests/test_auditor.py` — value/volume drift detected via SQL; one `Na provjeri` (reactivation) decision; expired rules stop suppressing |
| 12 | The investigation agent respects caps, blocks external drafts behind HITL, invents no numbers, resumes from checkpoint | **PASS** | `tests/test_investigation.py` — loop cap enforced from rule_config; HITL blocks the draft until approval; number contract over the whole report; resume from the Postgres checkpoint without re-running steps |
| 13 | Swapping the Tier-2 model is config-only with masking intact | **PASS** | `tests/test_router.py` + `tests/test_settings_api.py` — role→tier from rule_config; Sonnet↔Opus is a config change; masking holds on every tier and cannot be disabled (422) |
| — | The gate above all: the team uses it voluntarily | **PILOT MEASUREMENT** | Method below |

---

## M14 hardening additions

| Capability | Result | Evidence |
|---|---|---|
| Backups restore provably | **PASS** | `tests/test_hardening.py::test_backup_restore_roundtrip` — dump → restore into a scratch DB → identical row counts; `restore.sh` requires explicit `--yes` |
| Structured JSON logging | **PASS** | `tests/test_hardening.py::test_json_logging_format` + `test_json_logging_records_exceptions` — one parseable JSON line per record; no payloads/PII |
| Perf within budget | **PASS** | `tests/test_hardening.py::test_perf_budgets` — scan (no recompute) < 10s, recompute < 10s, dashboard < 3s on seed data |
| Growth-table query plans use indexes | **PASS** | `tests/test_hardening.py::test_invoice_date_range_uses_index` — all-customer date-range aggregation uses `ix_invoice_date` (migration 0015), not a seq scan |

---

## Pilot measurements (items 8 and the voluntary-usage gate)

These are **not** unit-testable — they are measured during the pilot. The
mechanisms ship and are tested; the trends are observed over weeks.

**Item 8 — useless-task share falls (4–6 weeks).**
- *Metric:* weekly ratio `count(task_feedback where useful=false) / count(task_feedback)`.
- *Baseline:* the ratio in pilot week 1.
- *Target:* a downward trend over weeks 1→6 as the self-config loop (M10) learns from
  dismissals and the auditor (M11) catches over-suppression.
- *Data source:* `app.task_feedback` + the decision feed; no extra instrumentation needed.

**The gate — voluntary usage.**
- *Metric:* weekly active reps (logins + task interactions) and how often the owner
  opens the ERP for the operational picture vs. VALERI.
- *Target:* reps open VALERI's task list to start the day; the owner stops opening the
  ERP for the operational view.
- *Data source:* `audit.task_log` (task views/actions), auth sessions; owner interview.

---

## Notes

- One backend test is skipped: the live-gateway smoke test (`test_llm.py`), which is
  intentionally skipped unless a real `ANTHROPIC_API_KEY` is configured — every other
  LLM path is covered by fakes.
- The full system runs against PostgreSQL 16 with LangGraph's checkpoint tables in the
  same database; migrations 0001–0015 build the schema from empty.
- Principles compliance is enforced continuously by the reviewer subagents
  (`principle-reviewer`, `tool-catalog-guardian`, `selfconfig-reviewer`,
  `investigation-agent-builder`) and the `/numbers-check` + `/decision-audit` commands,
  run at every milestone.
