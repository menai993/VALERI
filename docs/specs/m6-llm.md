# Spec — M6: LLM gateway + PII masking + narration + register tagging

**Milestone:** M6 · **Builds on:** M5 (tasks exist with template bodies) · **Status:** awaiting review

## 1. Objective

Bring the language layer online — **with the masking discipline that makes it permissible**:
an OpenAI-compatible client to the LiteLLM gateway (narration on Tier-1, Claude Haiku 4.5),
a **PII masking step that runs before every prompt** (pseudonymised customer identity, no
contact data ever), Bosnian prompt templates that consume **already-computed SQL numbers**,
Pydantic output schemas with reject+retry, a **number-contract validator** (every number in
the narration must be an evidence value, verbatim), name rehydration for the human-facing
result only, and one append-only `audit.ai_log` row per LLM call. Task bodies and registers
now come from the LLM; templates remain as the graceful fallback.

## 2. Scope

### In scope
1. **Migration 0007**: `audit.ai_log` exactly per docs/data-model.md.
2. **`llm/` package**: client (protocol + LiteLLM implementation via the `openai` SDK),
   masking, prompts, output schemas, validators (schema + number contract), narration
   orchestration with reject+retry.
3. **`audit/ai_log.py`**: append-only writer (INSERT only), one row per LLM API call —
   including rejected/failed attempts (full auditability).
4. **Pipeline integration**: `create_tasks_from_signals()` narrates bodies + classifies
   register via the LLM, **rehydrates real names for the stored task** (tasks are for
   humans), and falls back to M5 templates when the gateway is unavailable or output cannot
   be validated.
5. **Settings**: `litellm_base_url`, `litellm_master_key`, `llm_tier1_model`,
   `llm_narration_enabled`, `llm_max_retries`, `pii_salt` (env; no secrets in code).
6. **Infra**: `.env.example` + compose updated (worker also gets gateway env — scheduled
   scans narrate).
7. **Tests**: a `FakeLLMClient` test double (no real API calls in CI) + the three
   acceptance contracts + masking unit tests + one optional live-gateway test
   (skipped unless the gateway is reachable).

### Out of scope (deferred)
- Tier-2 models, role-based routing, cascade escalation, `audit.llm_route_log` (M12).
  M6 talks to **one** model name (`tier1`) — the gateway maps it to Haiku 4.5.
- Prompt caching / Batch API (M12).
- Chat/conversation, intent routing, tools (M9).
- Owner report narration (M7 — will reuse this layer).
- Async narration; the pipeline narrates synchronously (pilot volume: ~1–2 s × ~20 tasks).

## 3. Files

```
apps/api/valeri_api/llm/
  __init__.py
  client.py            LLMClient protocol · LLMResponse (text, tokens, latency_ms, model) ·
                       LiteLLMClient (openai SDK → gateway, model="tier1") · get_llm_client()
  masking.py           pseudonym(customer_id) → "Kupac-xxxxxx" (HMAC, salt from env) ·
                       MaskingContext (pseudonym ↔ real name) ·
                       build_masked_payload(signal row + customer) → dict WITHOUT any PII ·
                       rehydrate(text, context) → real names for humans
  schemas.py           TaskNarration {body: str, register: analiza|preporuka|akcija,
                       confidence: 0..1} — the only accepted LLM output shape
  prompts.py           Bosnian system prompt (strict rules: never compute, never invent) +
                       narration user prompt from the masked payload (finished numbers only)
  validators.py        parse_and_validate(raw) → TaskNarration | errors ·
                       extract_numbers(text) · check_number_contract(body, allowed_numbers)
  narration.py         narrate_task(session, signal_data, client) →
                       mask → prompt → call → validate (schema + numbers) → retry →
                       ai_log every call → NarrationResult (or NarrationFailed)

apps/api/valeri_api/audit/
  models.py            (edit) + AiLog (schema="audit")
  ai_log.py            log_ai_call(session, model, masked_input, output, confidence,
                       register, tokens, latency_ms) — INSERT only

apps/api/valeri_api/signals/pipeline.py    (edit) LLM narration + rehydration + template fallback
apps/api/valeri_api/config.py              (edit) LLM + masking settings
apps/api/migrations/versions/0007_ai_log.py
apps/api/migrations/env.py                 (edit) no change needed (audit.models already imported)

apps/api/tests/test_llm.py                 masking, prompts, validators, narration flow (FakeLLMClient)
apps/api/tests/test_llm_contract.py        the three acceptance contracts + pipeline integration

infra/.env.example                         (edit) + PII_SALT
infra/docker-compose.yml                   (edit) worker gets LITELLM_BASE_URL/LITELLM_MASTER_KEY
apps/api/pyproject.toml                    (edit) + openai ; uv.lock
```

## 4. Data-model touchpoints

| Schema.table | Action | Notes |
|---|---|---|
| `audit.ai_log` | **create** (0007) + append | model, **masked_input** (asserted PII-free), output, confidence, register, tokens, latency_ms |
| `app.task` | write (pipeline) | body now LLM-narrated (rehydrated), register now LLM-classified |
| `app.signal` | read | evidence + rule + customer_id feed the narration |
| `core.customer` | read | name → pseudonym mapping (never enters the prompt) |

- **One migration**: `0007_ai_log`.
- `audit.ai_log` is **append-only**: the writer has no update/delete path.

## 5. API touchpoints

**None new.** `GET /tasks*` responses simply carry better (LLM-written) bodies. The
`/settings/llm` endpoint is M12.

## 6. Key design decisions (flagged for review)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Pseudonyms**: `Kupac-` + 6 hex chars of HMAC-SHA256(customer_id, PII_SALT); segment passed alongside; contact name/email/phone/address **never** included in any payload (stripped, not pseudonymised — narration doesn't need them) | Stable across calls (coherent narration), non-reversible without the salt, no raw business identifier in any API payload (architecture §4) |
| **D2** | **Task register comes from the LLM classification** (validated against the enum; falls back to `preporuka`); the signal keeps its SQL-computed register and confidence untouched | This is the milestone's "classify register" deliverable; detection confidence (SQL) and narration confidence (LLM self-assessment, stored in ai_log) are kept distinct |
| **D3** | **Number contract enforced by a validator**, not trust: every digit-sequence in the narration must appear verbatim in the masked payload's allowed-number set; violations → reject + retry with feedback; persistent violation → template fallback | "Rendered numbers EQUAL the SQL numbers" must be mechanically guaranteed, not hoped for |
| **D4** | **Graceful fallback to M5 templates** when: gateway unreachable, narration disabled, schema validation fails after retries, or number contract violated after retries | The scan/task pipeline must never fail because the language layer is down; the fallback body is still correct (it formats the same SQL numbers) |
| **D5** | **One `ai_log` row per LLM API call**, including rejected attempts (output stores the rejection reason + raw text) | data-model.md: "one row per LLM call"; full auditability of what the model was asked and what it answered |
| **D6** | **Tests use a `FakeLLMClient`** (scripted responses, captures prompts); no real API calls in CI; one live-gateway smoke test exists but auto-skips when `LITELLM` env is absent | Deterministic, free, offline tests; the contracts are about OUR pipeline (masking/validation/logging), not about Claude |

## 7. Tests (TDD: contracts written first)

### `tests/test_llm_contract.py` — the three acceptance contracts

1. `test_contract_output_validates_against_schema` — the narration flow only ever returns a
   `TaskNarration`; malformed JSON / wrong register / out-of-range confidence from the fake
   client → rejected, retried, and (if persistent) the flow reports failure (→ fallback).
2. `test_contract_rendered_numbers_equal_sql_numbers` — for every narrated task over the
   seeded+scanned data: every numeric token in the body exists verbatim in the signal's
   evidence allowed-number set; a fake response with an invented number ("15.000 KM") is
   rejected and never reaches a task body.
3. `test_contract_no_raw_pii_in_prompt` — the fake client captures every prompt; for every
   narrated signal: the customer's real name, contact names, e-mails, phone numbers, and
   addresses do NOT appear anywhere in any prompt or in `audit.ai_log.masked_input`;
   the pseudonym DOES appear; the stored task body (for humans) DOES contain the real name.
4. `test_pipeline_fallback_to_templates` — gateway "down" (fake raises) → tasks still
   created with template bodies; ai_log records the failed calls.
5. `test_ai_log_one_row_per_call` — happy path = 1 row; one rejection + one success = 2 rows;
   rows carry model/tokens/latency/register/confidence.

### `tests/test_llm.py` — unit tests

6. `test_pseudonym_stable_and_salted` — same customer → same pseudonym; different salt →
   different pseudonym; pseudonym contains no part of the real name.
7. `test_masked_payload_strips_all_pii` — built payload contains pseudonym + segment +
   evidence numbers only; no name/email/phone/address keys or values.
8. `test_rehydrate_restores_names` — narration text with pseudonyms → real names.
9. `test_number_extraction_and_contract` — extractor finds integers/decimals (both `.` and
   `,` forms); contract check flags invented numbers, passes evidence numbers.
10. `test_prompt_contains_only_finished_numbers` — the user prompt embeds evidence values
    verbatim and contains no instruction to compute (static check of prompt text).
11. `test_reject_retry_loop` — fake returns invalid → valid; narration succeeds with
    2 ai_log rows; retry feedback message contains the validation errors.
12. `test_narration_disabled_uses_templates` — `llm_narration_enabled=False` → no LLM calls,
    no ai_log rows, template bodies.
13. `test_live_gateway_smoke` *(auto-skipped unless LITELLM_BASE_URL is reachable)* — one real
    narration through LiteLLM → valid schema, contracts hold.

## 8. Acceptance criteria (per IMPLEMENTATION-PLAN M6)

1. **Output validates against schema** (contract test 1) — malformed output is rejected and
   retried, never stored raw into a task.
2. **Rendered numbers equal SQL numbers** (contract test 2) — mechanically enforced.
3. **No raw PII in the prompt** (contract test 3) — asserted on captured prompts and on
   `audit.ai_log.masked_input`.
4. `audit.ai_log` written per call (tests 4–5); append-only writer.
5. Tasks get LLM bodies with rehydrated names; fallback works (test 4).
6. `/numbers-check` passes; full pytest green locally + CI; ruff/black clean.
7. principle-reviewer reports PASS on the M6 diff.

## 9. Principles compliance

| Principle | M6 impact |
|---|---|
| 1. **No LLM-computed numbers** | Prompts contain only finished SQL numbers + an explicit "never compute" instruction; the **number-contract validator mechanically rejects** any narration containing a number not present in the evidence. |
| 2. Evidence on every task | Unchanged from M5 (tasks link to signals); the narration is *derived from* the evidence and verified against it. |
| 3. Confidence on every conclusion | Detection confidence (SQL) unchanged on the signal; narration confidence (LLM self-assessment) stored in `ai_log`; both are visible. |
| 4./5. No ERP writes; read-only posture | The LLM layer only reads signals/customers and writes `app.task` bodies + `audit.ai_log`. |
| 6. **PII masking before AI processing** | This milestone implements it: pseudonymisation + stripping BEFORE every prompt; rehydration only for the human-facing task body; contract test 3 enforces it; `ai_log.masked_input` proves it forever. |
| 7. **Append-only logs** | `audit.ai_log` joins `task_log`: INSERT-only writer, one row per call including failures. |
| 8. Feedback loop | Unchanged (M5 feedback persists); narration quality becomes assessable via feedback from M10. |
| 9. Register tags | The LLM classifies analiza/preporuka/akcija per narration (validated enum); stored on the task and in ai_log. |
| 10. Approval gates | N/A — narration produces internal task bodies, not customer-facing communication (that's M7's approval-gated drafts). |
| Conventions | All LLM I/O through Pydantic with reject+retry (CLAUDE.md); secrets (gateway key, PII salt) only in env; `openai` pinned + lockfile. |

## 10. Open questions

1. **D1 (pseudonym format)** — `Kupac-<hmac6>` + segment. OK?
2. **D2 (register from LLM)** — task register = LLM classification (signal keeps its own). OK?
3. **D4 (graceful fallback)** — gateway down / invalid output ⇒ template bodies, scan never
   fails. OK?
4. **D5 (ai_log granularity)** — one row per API call, including rejected attempts. OK?
5. **Synchronous narration** in the pipeline (~1–2 s per task at pilot volume; Batch API
   comes in M12). OK?
