# Spec — P3: LLM cost tracking, budgets & Batch (X1)

**Track:** Improvement Roadmap P3 = plan X1 (`docs/llm-cost.md` is the binding spec) · **Builds on:** M6 gateway (`llm/narration.py` + `llm/structured.py` — the only two places that call the LLM and write `ai_log`), M12 router (`role` already threads through both chokepoints), P1 inbox bell, P2 `ops/runs.py` alert derivation · **Status:** approved

## 1. Objective

Hosted Claude is billed per token and VALERI currently records only `tokens` + `latency_ms` per call — nobody can answer "where is the money going" or stop a runaway feature. P3 turns `audit.ai_log` into a cost ledger (feature/user/tier/input/output tokens, cached, batched, `cost_usd` computed at write time from DB-seeded prices), adds **`app.llm_pricing` + `app.llm_budget`**, ships the **"Troškovi AI" admin dashboard** (spend today/month vs budget, trend, breakdowns by feature/model/user, **cost-per-useful-task**, recent expensive calls), raises an **80% budget alert into the P2 bell**, enforces **per-feature daily caps + a near-cap throttle of non-essential jobs**, routes the **weekly cycle through the Anthropic Batch API** (50% rate, live fallback), and adds a **short-TTL answer cache** for identical masked questions. Optimize for cost-per-useful-task, not minimum spend (`llm-cost.md` §7).

## 2. Scope

### In scope
- **Migration `0025`**: `ai_log` cost columns (`feature`, `user_id`, `tier`, `input_tokens`, `output_tokens`, `cached`, `cached_input_tokens`, `batched`, `cost_usd`); `app.llm_pricing` (+`batch_discount` column); `app.llm_budget` (period `'YYYY-MM'` or `'default'` fallback row, seeded `limit_usd=50, alert_pct=80`); `rule_config` seeds (rule `llm_cost`: `feature_daily_caps`, `throttle_pct`, `non_essential_roles`); pricing seed rows for the three tier models (**values confirmed at docs.claude.com before merge — never hard-coded in code**).
- **Cost computation in the chokepoint**: `log_ai_call()` gains the attribution params and computes `cost_usd = (input−cached_input)×in_rate + cached_input×cache_read_rate + output×out_rate`, all `× batch_discount` when batched; **unknown model → `cost_usd NULL` + warning, never guessed**. `LLMResponse` gains `input_tokens`/`output_tokens`/`cached_input_tokens` (from gateway usage). `narration.py`/`structured.py` pass `feature=role`, `tier=routed tier`, optional `user_id` (threaded from chat/KB/selfconfig call sites).
- **Admin API + dashboard**: `GET /admin/llm/usage?from&to&group_by=feature|model|user`, `GET /admin/llm/recent?order=cost`, `GET/PATCH /admin/llm/budget`, `GET/PATCH /admin/llm/pricing` — owner+admin read, admin write; **every PATCH writes a reversible `threshold_change` decision**. Frontend: a "Troškovi AI" tab in Postavke.
- **Budget alert**: `ops/runs.py::derive_alerts` gains an `llm_budget` condition (month spend ≥ `alert_pct`% of the period's budget, `'default'` row as fallback) → P1 bell + `/admin/ops/status`, owner/admin.
- **Spend guard** (`llm/spend_guard.py`): per-feature **daily caps** (investigation start refused with a clear envelope when capped) and **near-cap throttle** (spend ≥ `throttle_pct`% of budget → non-essential roles fall back to templates / defer, recorded in `job_run.detail`; chat and on-demand paths are never throttled).
- **Batch** (`llm/batch.py`): `LiteLLMBatchClient` implementing the `LLMClient` protocol via the gateway's `/v1/batches` passthrough (poll with timeout), used by the **weekly cycle**; rows logged `batched=true` at the discounted rate; any batch failure/timeout → automatic live fallback (`batched=false`). Env-toggled `LLM_BATCH_ENABLED`.
- **Answer cache** (`llm/answer_cache.py`): in-process TTL cache keyed on `sha256(role + masked system + masked user)` — **post-masking only** — for whitelisted roles (`simple_qa`), TTL `LLM_ANSWER_CACHE_TTL_SECONDS` (default 300). A hit makes no LLM call and writes no `ai_log` row.

### Out of scope (deferred)
- E-mail delivery of budget alerts (bell-only, P2 posture); cross-process/redis caches (single api container); a batch *queue* that groups many prompts into one batch (per-call batches now — grouping is a later optimization); cost forecasting; X1 for DI features (tagged when P5 lands via the same `feature=role` mechanism); per-user budgets.

## 3. Files

```
apps/api/
  migrations/versions/0025_llm_cost.py     # ai_log columns; llm_pricing+llm_budget (+seeds); llm_cost rule_config seeds
  valeri_api/llm/models.py                 # NEW: LlmPricing, LlmBudget (app schema)
  valeri_api/llm/cost.py                   # NEW: pricing lookup, compute_cost(), spend aggregates + budget status (pure SQL)
  valeri_api/llm/spend_guard.py            # NEW: feature_cap_reached(), non_essential_throttled() (rule_config-driven)
  valeri_api/llm/answer_cache.py           # NEW: TTL cache (get/put/reset), role whitelist
  valeri_api/llm/batch.py                  # NEW: LiteLLMBatchClient (LLMClient protocol; /v1/batches; poll; raise on fail)
  valeri_api/llm/client.py                 # EDIT: LLMResponse += input/output/cached_input tokens; populate from usage
  valeri_api/llm/narration.py              # EDIT: user_id param; answer-cache hook; pass attribution to log_ai_call
  valeri_api/llm/structured.py             # EDIT: same as narration.py
  valeri_api/audit/models.py               # EDIT: AiLog new columns
  valeri_api/audit/ai_log.py               # EDIT: log_ai_call(feature, user_id, tier, in/out/cached tokens, batched) + cost
  valeri_api/api/admin_llm.py              # NEW: usage/recent/budget/pricing endpoints (decision-writing PATCHes)
  valeri_api/main.py                       # EDIT: mount admin_llm router
  valeri_api/ops/runs.py                   # EDIT: derive_alerts += llm_budget condition
  valeri_api/scanner/scheduler.py          # EDIT: weekly cycle uses batch client (fallback live) + throttle check
  valeri_api/investigation/runner.py       # EDIT: create_investigation refuses when daily cap reached
  valeri_api/conversation/service.py       # EDIT: pass user_id (and answer-cache roles apply)
  valeri_api/kb/pipeline.py                # EDIT: pass user_id
  valeri_api/selfconfig/proposal.py        # EDIT: pass user_id
  valeri_api/config.py                     # EDIT: LLM_BATCH_ENABLED, LLM_ANSWER_CACHE_TTL_SECONDS, batch poll timeout
  migrations/env.py                        # EDIT: register llm/models.py
apps/api/tests/
  test_llm_cost.py                         # cost formula golden tests (TDD-first), attribution, unknown model
  test_admin_llm_api.py                    # usage==SQL, recent, budget/pricing PATCH+decision+RBAC, cost-per-useful-task
  test_llm_budget_alerts.py                # 80% alert in derive_alerts + bell; default-row fallback
  test_llm_spend_guard.py                  # daily cap blocks investigation; throttle defers non-essential, spares chat
  test_llm_batch.py                        # weekly cycle batched=true + discounted cost; failure→live fallback
  test_llm_answer_cache.py                 # hit skips the client; post-masking key; whitelist; TTL expiry
apps/web/src/
  lib/api/types.ts + queries.ts            # EDIT: LlmUsage/LlmBudget/LlmPricing types + hooks/mutations
  components/widgets/LlmCostPanel.tsx      # NEW: spend vs budget, trend, breakdowns, cost/useful-task, recent calls, editors
  features/settings/SettingsPage.tsx       # EDIT: "Troškovi AI" tab (owner sees, admin edits)
  lib/i18n/bs.ts / en.ts                   # EDIT: cost strings
apps/web/src/test/llm-cost.test.tsx        # NEW: panel renders aggregates; budget PATCH fires
```

## 4. Data-model touchpoints

- **EDIT `audit.ai_log`** (additive, migration `0025`): `feature TEXT`, `user_id BIGINT`, `tier TEXT`, `input_tokens INT`, `output_tokens INT`, `cached BOOLEAN DEFAULT false`, `cached_input_tokens INT` *(additive beyond `llm-cost.md` §1 — needed so `cost_usd` is exactly reproducible from persisted columns)*, `batched BOOLEAN DEFAULT false`, `cost_usd NUMERIC(12,6)`. Existing rows keep NULLs (pre-P3 calls are not retro-priced). Still append-only.
- **NEW `app.llm_pricing`**: `model TEXT PK`, `input_per_mtok NUMERIC(10,4)`, `output_per_mtok NUMERIC(10,4)`, `cache_read_per_mtok NUMERIC(10,4)`, `batch_discount NUMERIC(4,3) DEFAULT 0.5` *(a price, so it lives in the DB)*, `effective_date DATE`. Seeded for `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-opus-4-8` **and** the tier aliases (the gateway may echo either form).
- **NEW `app.llm_budget`**: `period TEXT PK` (`'YYYY-MM'` | `'default'`), `limit_usd NUMERIC(12,2)`, `alert_pct INT DEFAULT 80`. Seed one `'default'` row (50 USD) so alerting works without monthly admin chores; month rows override.
- **`app.rule_config` seeds** (rule `llm_cost`): `feature_daily_caps = {"investigation": 10}`, `throttle_pct = 90`, `non_essential_roles = ["report_narration","customer_draft","over_suppression_audit","kb_summary"]`.
- Reads: `audit.task_log` (`event='outcome' AND payload->>'status'='done'`) for cost-per-useful-task; `app.job_run.detail` records throttle skips.
- `feature` values = the **M12 router-role vocabulary** (`narration`, `intent`, `simple_qa`, `nl_rule`, `report_narration`, `customer_draft`, `over_suppression_audit`, `investigation`, `investigation_synthesis`, `kb_gate`, `kb_extraction`, `kb_summary`) — finer-grained than the illustrative list in `llm-cost.md` §1, and already threaded through both chokepoints.

## 5. API touchpoints

- **NEW `GET /api/admin/llm/usage?from&to&group_by=feature|model|user`** → `{total: {cost_usd, input_tokens, output_tokens, calls}, groups: [{key, cost_usd, calls, input_tokens, output_tokens}], budget: {period, limit_usd, alert_pct, spent_usd, pct}, cost_per_useful_task: {cost_usd, useful_tasks, value} , trend: [{day, cost_usd}]}` — all SQL over `ai_log`.
- **NEW `GET /api/admin/llm/recent?order=cost&limit=20`** → top calls `{id, created_at, model, tier, feature, user_id, input_tokens, output_tokens, cached, batched, cost_usd, latency_ms}`.
- **NEW `GET/PATCH /api/admin/llm/budget`** `{period?, limit_usd, alert_pct}` — PATCH upserts the row, writes a reversible `threshold_change` decision (old values in payload).
- **NEW `GET/PATCH /api/admin/llm/pricing`** `{model, input_per_mtok, …}` — PATCH writes a reversible `threshold_change` decision.
- **RBAC**: owner+admin read, admin write (the `settings/rule-config` pattern); reps/finance 403.
- **EDIT `GET /api/admin/ops/status` + inbox `alerts`**: new alert kind `llm_budget` ("Potrošnja LLM-a je na NN% mjesečnog budžeta").
- **EDIT `POST /api/investigations`**: returns the error envelope (`code: "feature_capped"`, HTTP 429) when the daily cap is reached; no run row is created.

## 6. Tests

**TDD-first (trust-critical cost math):**
- `test_llm_cost.py::test_cost_formula_exact` — Decimal golden cases: plain, cached-input, batched, cached+batched; `cost_usd` equals hand-computed values to 6 dp.
- `test_llm_cost.py::test_unknown_model_costs_null` — no pricing row → `cost_usd IS NULL`, warning logged, row still written.
- `test_llm_cost.py::test_chokepoints_attribute_calls` — `narrate_structured` (fake client) writes `feature=role`, `tier`=routed tier, `user_id`, token splits.
- `test_admin_llm_api.py::test_usage_groups_match_sql` — endpoint aggregates == direct SQL over seeded `ai_log` rows for all three `group_by` values (+trend).
- `test_admin_llm_api.py::test_cost_per_useful_task_matches_sql` — spend ÷ tasks done in period (from `task_log`).
- `test_admin_llm_api.py::test_recent_orders_by_cost`.
- `test_admin_llm_api.py::test_budget_pricing_patch_decisions_and_rbac` — PATCHes write reversible decisions with old values; admin-only writes; owner reads; rep 403.
- `test_llm_budget_alerts.py::test_alert_at_80_pct` — seeded spend at 79% → no alert; 81% → `llm_budget` alert in `derive_alerts` + owner bell count.
- `test_llm_budget_alerts.py::test_default_period_fallback` — no month row → `'default'` row governs.
- `test_llm_spend_guard.py::test_daily_cap_blocks_investigation` — cap reached → 429 `feature_capped`, no investigation row.
- `test_llm_spend_guard.py::test_throttle_defers_non_essential_spares_chat` — spend ≥ `throttle_pct` → weekly narration falls back to templates (no LLM call, `job_run.detail.throttled=true`); a chat call still goes through.
- `test_llm_batch.py::test_weekly_cycle_batched` — fake batch client → weekly `ai_log` rows `batched=true`, cost at `batch_discount`.
- `test_llm_batch.py::test_batch_failure_falls_back_live` — batch raises → live call succeeds, `batched=false`, weekly cycle completes.
- `test_llm_answer_cache.py::test_hit_skips_client / test_post_masking_key_and_whitelist / test_ttl_expiry`.

**Frontend:** `llm-cost.test.tsx` — tab renders spend-vs-budget (pct), per-feature rows, recent calls; editing the budget fires PATCH. **Existing masking/number contract tests must stay green untouched.**

## 7. Acceptance criteria

1. Per-call `cost_usd` = tokens × DB prices exactly (golden tests); unknown model is NULL, never guessed.
2. Dashboard aggregates equal direct SQL over `ai_log` (spend, groups, trend, cost-per-useful-task).
3. The 80% budget alert appears in the owner's bell and `/admin/ops/status` within one refetch.
4. Weekly-cycle calls log `batched=true` at the discounted rate; a batch failure degrades to live calls without losing the report.
5. The investigation daily cap refuses with a clear envelope; the near-cap throttle defers only non-essential roles — chat and on-demand actions are never throttled, and **PII masking is untouched by every lever**.
6. Budget/pricing changes are admin-only and each writes a reversible `app.decision`.
7. Answer-cache hit answers an identical masked question without an LLM call inside the TTL.
8. Full backend + frontend suites green; migration `0025` cycles up/down/up clean.

## 8. Principles compliance

| # | Principle | How P3 honors it |
|---|-----------|------------------|
| 1 | No LLM-computed numbers | Cost/spend/aggregates are Python-Decimal/SQL over `ai_log`; the LLM never sees or produces a cost figure. |
| 2/3 | Evidence/confidence | N/A — no new AI conclusions; dashboard rows cite the underlying `ai_log` ids (recent calls). |
| 4/5 | No ERP writes / read-only | Untouched; everything lives in VALERI's `app`/`audit` schemas. |
| 6 | PII masking | Load-bearing constraint: the answer cache keys on **post-masking** payloads; batch/cache/throttle levers cannot disable masking (no code path exists; explicit test). |
| 7 | Append-only logs | `ai_log` stays INSERT-only (new columns, no update path); pricing/budget changes are decisions, not edits to audit rows. |
| 8 | Feedback loop | Cost-per-useful-task ties spend to task outcomes — the metric that matters (`llm-cost.md` §7). |
| 9 | Analysis/recommendation/action | Budget alerts are deterministic system notices (P2 posture); no silent behavior: throttle skips are recorded in `job_run.detail`. |
| 10 | Approval/reversibility | Budget/pricing PATCHes write reversible `threshold_change` decisions; caps/throttle thresholds live in `rule_config` (decision-writing path). |

## 9. Open questions (defaults — confirm or override)

- **D1 feature vocabulary:** use the router-role names (finer than `llm-cost.md` §1's list). *(default)*
- **D2 exact-cost column:** add `cached_input_tokens` beyond the illustrative DDL so cost is reproducible from persisted columns. *(default)*
- **D3 pricing seeds:** Haiku 4.5 ≈ 1.00/5.00, Sonnet 4.6 ≈ 3.00/15.00, Opus 4.8 ≈ 5.00/25.00 USD/MTok, cache-read = 0.1× input, batch = 0.5× — **I will verify each at docs.claude.com during implementation**; they are DB rows, editable any time. *(default)*
- **D4 RBAC:** owner+admin read, admin write — the rule-config pattern. *(default)*
- **D5 batch shape:** per-call 1-item message batches via the gateway (the 50% rate applies regardless of batch size); grouping deferred. `LLM_BATCH_ENABLED` default **true** with automatic live fallback. *(default — flip to false if the LiteLLM passthrough misbehaves in prod)*
- **D6 answer cache:** roles `["simple_qa"]`, TTL 300 s, in-process. *(default)*
- **D7 caps/throttle:** `investigation ≤ 10/day`; throttle non-essential at 90% of budget (alert already fired at 80%). *(default)*
- **D8 budget seed:** `'default'` row at **50 USD/month**, `alert_pct=80` — confirm the pilot's real monthly budget. *(default)*
- **D9 cost-per-useful-task:** spend ÷ distinct tasks with `task_log` `outcome/done` in the period. *(default)*
