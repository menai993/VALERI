# VALERI — LLM usage, expense & optimization (`docs/llm-cost.md`)

Hosted Claude is billed per token, so VALERI tracks what it spends, shows it, and has levers to bring it down. The foundation already exists: `audit.ai_log` records the model, tokens and latency of every call, and `audit.llm_route_log` records every routing decision. This module turns that into spend, surfaces it, and adds controls. Build with/after M12 (routing and cost optimization are the same concern). Conventions per `data-model.md` / `api-spec.md` / `frontend-spec.md`.

## 1. Schema additions (`app`/`audit`)

Extend `audit.ai_log` with cost attribution columns:

```sql
ALTER TABLE audit.ai_log
  ADD COLUMN feature       TEXT,        -- narration | intent | selfconfig | kb_capture | investigation | over_suppression_audit | rule_proposal | report
  ADD COLUMN user_id       BIGINT,
  ADD COLUMN tier          TEXT,        -- tier1 | tier2 | tier2_strong
  ADD COLUMN input_tokens  INT,
  ADD COLUMN output_tokens INT,
  ADD COLUMN cached        BOOLEAN DEFAULT false,   -- prompt-cache hit
  ADD COLUMN batched       BOOLEAN DEFAULT false,   -- Batch API call
  ADD COLUMN cost_usd      NUMERIC(12,6);
```

```sql
CREATE TABLE app.llm_pricing (          -- editable; update when Anthropic prices change
  model              TEXT PRIMARY KEY,
  input_per_mtok     NUMERIC(10,4) NOT NULL,   -- USD per 1M input tokens
  output_per_mtok    NUMERIC(10,4) NOT NULL,   -- USD per 1M output tokens
  cache_read_per_mtok NUMERIC(10,4),           -- if used
  effective_date     DATE NOT NULL DEFAULT CURRENT_DATE
);
CREATE TABLE app.llm_budget (
  period       TEXT PRIMARY KEY,              -- e.g. '2026-06' (monthly)
  limit_usd    NUMERIC(12,2) NOT NULL,
  alert_pct    INT NOT NULL DEFAULT 80
);
```

**Do not hard-code prices** — seed `llm_pricing` from current Anthropic pricing and confirm figures at <https://docs.claude.com> (or platform.claude.com pricing); they change.

## 2. Cost computation & attribution

On every LLM call (in the gateway, M6/M12), record `input_tokens`, `output_tokens`, `tier`, `feature`, `user_id`, `cached`, `batched`, and compute
`cost_usd = input_tokens/1e6 * input_per_mtok + output_tokens/1e6 * output_per_mtok` (apply the cache-read rate for cached input). Attribution by **feature + user + tier** is what answers “where is the money going,” not just “how much.”

## 3. “Troškovi AI” dashboard (admin)

A screen (admin-gated) showing: spend **today / this month vs budget** (with a progress bar), a **trend** line, and breakdowns **by feature**, **by model/tier**, and **by user** — plus the key metric **cost per useful task** (total spend ÷ tasks reps acted on), which tells you whether the spend produces value rather than just its size. Include a “recent expensive calls” list (top `ai_log` rows by cost) for spotting runaways.

## 4. Budgets, alerts, caps

- A **monthly budget** (`llm_budget`) with an alert to the owner/admin at `alert_pct` (default 80%).
- **Per-feature daily caps** (in `rule_config`, e.g. investigations ≤ N/day) so one feature can’t blow the budget.
- **Near-cap throttle:** when close to the limit, defer non-essential jobs (scheduled narration, over-suppression audits) to the next window or Batch; never throttle the trust-critical paths or block a user mid-action without telling them.

## 5. API (admin)

- `GET /api/admin/llm/usage?from&to&group_by=feature|model|user` → spend + token aggregates.
- `GET /api/admin/llm/recent?order=cost` → recent/expensive calls.
- `GET/PATCH /api/admin/llm/budget` ; `GET/PATCH /api/admin/llm/pricing`.

## 6. Optimization levers (in order of impact)

1. **Route ruthlessly (M12).** Keep the cheap tier doing the bulk — Haiku for narration/intent/extraction/simple Q&A, Sonnet only for real reasoning, Opus only for the hardest investigations. Routing research shows the large model can stay at ~10–15% of calls with most of the quality, which is where the big savings live.
1. **Prompt caching.** Cache the stable prompt prefix that repeats across calls — system instructions, the semantic-layer/metric definitions, the masking rules. You pay for it once and reuse it cheaply; large win for the weekly scan narration and repetitive task write-ups. Caveat: cache lifetime is short, so it helps most within bursts of activity, not across long idle gaps.
1. **Batch the non-interactive work.** The weekly owner-report narration, bulk task bodies, and over-suppression re-checks aren’t real-time — run them through the Batch API (~half price). Reserve live calls for chat and on-demand actions.
1. **Send the model only what it needs.** The biggest token waste is raw data in prompts; Principle 1 already prevents it (SQL computes, the model gets finished numbers + short structured context). Enforce it as a cost rule: small structured inputs, tight Pydantic output schemas, and a capped `max_tokens`. (Output tokens cost more than input, so tight outputs save the most.)
1. **Gate the expensive paths.** The KB-capture relevance gate (skip greetings/pure questions), the investigation agent’s loop + token/time budgets, and a similarity threshold before triggering an investigation — cheap gate, expensive payload only when warranted.
1. **Cache answers, not just prompts.** Identical/near-identical questions (e.g. “prihod ovog mjeseca”) and the dashboard’s AI insights can return a cached result for a short window instead of re-calling.
1. **Right-size outputs.** Narration doesn’t need long generations — constrain them.

## 7. The metric that matters

Optimize for **cost per useful task**, not minimum spend. A Haiku-heavy, cached, batched setup with Opus reserved for the few hard problems is both cheap and good; the dashboard’s cost-per-useful-task keeps you optimizing value, not just shrinking the bill.

## 8. Guardrails

- **Never disable PII masking to save tokens** — masking is load-bearing (Principle 6), not an optimization target.
- Cost optimization must not weaken the confirmation/approval/evidence discipline; cheaper ≠ less careful.
- Numbers still come from SQL (which also keeps prompts small and cheap).