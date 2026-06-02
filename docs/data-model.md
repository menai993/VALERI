# VALERI — Data model (`docs/data-model.md`)

Canonical PostgreSQL 16 schema. The DDL below is **illustrative** — implement it with SQLAlchemy 2.x models and Alembic migrations (one migration per schema-changing milestone). Schemas: `staging` (raw imports), `core` (the clean business graph + derived metrics), `app` (pipeline, governance, conversation, learning, investigation), `audit` (append-only logs). PII columns are flagged `-- PII`; these are masked before any LLM call.

## Enums

```sql
CREATE TYPE register      AS ENUM ('analiza','preporuka','akcija');           -- analysis/recommendation/action
CREATE TYPE conf_band     AS ENUM ('niska','srednja','visoka');
CREATE TYPE risk_band     AS ENUM ('nizak','srednji','visok');
CREATE TYPE signal_status AS ENUM ('new','tasked','dismissed','suppressed','resolved');
CREATE TYPE task_status   AS ENUM ('open','in_progress','done','dismissed');
CREATE TYPE appr_status   AS ENUM ('draft','pending_approval','approved','rejected','sent');
CREATE TYPE lr_status      AS ENUM ('pending_confirm','active','reverted','expired');
CREATE TYPE autonomy       AS ENUM ('auto_applied','confirmed');
CREATE TYPE decision_kind  AS ENUM ('suppression','threshold_change','reactivation','undo','approval','rejection');
CREATE TYPE inv_status     AS ENUM ('queued','running','needs_input','done','failed');
CREATE TYPE user_role      AS ENUM ('owner','sales_rep','finance','admin');
CREATE TYPE actor_kind     AS ENUM ('valeri','user');
```

## core — business graph (M1)

```sql
CREATE TABLE core.legal_entity (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  tax_id      TEXT UNIQUE,                         -- JIB/PDV
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.customer (                        -- "object/location"; many per legal_entity
  id              BIGSERIAL PRIMARY KEY,
  legal_entity_id BIGINT NOT NULL REFERENCES core.legal_entity(id),
  name            TEXT NOT NULL,
  segment         TEXT,                             -- hotel/restoran/kafić/klinika/škola
  status          TEXT NOT NULL DEFAULT 'active',   -- active/inactive/closed
  external_code   TEXT,                             -- code in the source ERP
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_customer_legal_entity ON core.customer(legal_entity_id);
CREATE INDEX ix_customer_segment      ON core.customer(segment);

CREATE TABLE core.contact (
  id          BIGSERIAL PRIMARY KEY,
  customer_id BIGINT NOT NULL REFERENCES core.customer(id),
  name        TEXT,                                 -- PII
  email       TEXT,                                 -- PII
  phone       TEXT,                                 -- PII
  address     TEXT                                  -- PII
);
CREATE INDEX ix_contact_customer ON core.contact(customer_id);

CREATE TABLE core.sales_rep (
  id    BIGSERIAL PRIMARY KEY,
  name  TEXT NOT NULL,
  email TEXT
);

CREATE TABLE core.customer_rep (
  customer_id  BIGINT NOT NULL REFERENCES core.customer(id),
  sales_rep_id BIGINT NOT NULL REFERENCES core.sales_rep(id),
  from_date    DATE NOT NULL DEFAULT CURRENT_DATE,
  PRIMARY KEY (customer_id, sales_rep_id, from_date)
);

CREATE TABLE core.category ( id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL );

CREATE TABLE core.article (
  id          BIGSERIAL PRIMARY KEY,
  category_id BIGINT REFERENCES core.category(id),
  code        TEXT NOT NULL,
  name        TEXT NOT NULL,
  active      BOOLEAN NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX ux_article_code ON core.article(code);
CREATE INDEX ix_article_category    ON core.article(category_id);

CREATE TABLE core.article_alias (                   -- code-swap: old code → new article
  old_code         TEXT PRIMARY KEY,
  new_article_id   BIGINT NOT NULL REFERENCES core.article(id),
  mapped_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.invoice (
  id          BIGSERIAL PRIMARY KEY,
  customer_id BIGINT NOT NULL REFERENCES core.customer(id),
  date        DATE NOT NULL,
  total       NUMERIC(14,2) NOT NULL DEFAULT 0
);
CREATE INDEX ix_invoice_customer_date ON core.invoice(customer_id, date);

CREATE TABLE core.invoice_line (
  id          BIGSERIAL PRIMARY KEY,
  invoice_id  BIGINT NOT NULL REFERENCES core.invoice(id),
  article_id  BIGINT NOT NULL REFERENCES core.article(id),
  qty         NUMERIC(14,3) NOT NULL,
  unit_price  NUMERIC(14,4) NOT NULL,
  line_total  NUMERIC(14,2) NOT NULL
);
CREATE INDEX ix_line_invoice ON core.invoice_line(invoice_id);
CREATE INDEX ix_line_article ON core.invoice_line(article_id);
```

## core — derived metrics (M3; recomputed by SQL, never by the LLM)

```sql
CREATE TABLE core.customer_metrics (
  customer_id           BIGINT PRIMARY KEY REFERENCES core.customer(id),
  turnover_60d          NUMERIC(14,2),
  turnover_6m_avg_60d   NUMERIC(14,2),              -- 6-month baseline normalised to a 60-day window
  last_order_date       DATE,
  avg_order_interval_d  NUMERIC(8,2),
  segment               TEXT,
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.cust_article_cadence (
  customer_id      BIGINT NOT NULL REFERENCES core.customer(id),
  article_id       BIGINT NOT NULL REFERENCES core.article(id),
  avg_interval_d   NUMERIC(8,2),
  last_seen        DATE,
  PRIMARY KEY (customer_id, article_id)
);

CREATE TABLE core.segment_basket (
  segment      TEXT NOT NULL,
  category_id  BIGINT NOT NULL REFERENCES core.category(id),
  prevalence   NUMERIC(5,4),                        -- share of segment customers buying this category
  PRIMARY KEY (segment, category_id)
);
```

## app — governance, pipeline, learning, conversation, investigation

```sql
-- thresholds (M4) — never hard-code rule parameters
CREATE TABLE app.rule_config (
  rule        TEXT NOT NULL,
  param       TEXT NOT NULL,
  value       JSONB NOT NULL,
  updated_by  BIGINT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (rule, param)
);

-- signals (M4). evidence JSONB shape:
--   { "metric":"turnover_60d", "value":..., "baseline":..., "delta_pct":...,
--     "invoices":[id...], "lines":[id...], "period":{"from":...,"to":...},
--     "seasonal_check":{...} }
CREATE TABLE app.signal (
  id          BIGSERIAL PRIMARY KEY,
  rule        TEXT NOT NULL,                        -- customer_decline/lost_article/lost_category/sleeping/narrow_basket/spend_anomaly...
  customer_id BIGINT REFERENCES core.customer(id),
  article_id  BIGINT REFERENCES core.article(id),
  evidence    JSONB NOT NULL,
  confidence  NUMERIC(4,3) NOT NULL,
  conf_band   conf_band NOT NULL,
  register    register NOT NULL DEFAULT 'analiza',
  status      signal_status NOT NULL DEFAULT 'new',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_signal_status ON app.signal(status);
CREATE INDEX ix_signal_customer ON app.signal(customer_id);

-- tasks (M5)
CREATE TABLE app.task (
  id              BIGSERIAL PRIMARY KEY,
  signal_id       BIGINT REFERENCES app.signal(id),
  assignee_id     BIGINT REFERENCES core.sales_rep(id),
  owner_cc        BOOLEAN NOT NULL DEFAULT false,
  title           TEXT NOT NULL,
  body            TEXT,                              -- Bosnian, LLM-written from finished numbers
  proposed_action TEXT,
  due_date        DATE,
  status          task_status NOT NULL DEFAULT 'open',
  register        register NOT NULL DEFAULT 'preporuka',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_task_assignee_status ON app.task(assignee_id, status);

CREATE TABLE app.task_feedback (
  id        BIGSERIAL PRIMARY KEY,
  task_id   BIGINT NOT NULL REFERENCES app.task(id),
  useful    BOOLEAN NOT NULL,
  reason    TEXT,
  by_user   BIGINT,
  at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.approval (                          -- M7; gates customer-facing drafts
  id          BIGSERIAL PRIMARY KEY,
  task_id     BIGINT REFERENCES app.task(id),
  kind        TEXT NOT NULL,                         -- offer/message/...
  status      appr_status NOT NULL DEFAULT 'draft',
  decided_by  BIGINT,
  decided_at  TIMESTAMPTZ
);

-- conversation (M9)
CREATE TABLE app.conversation (
  id         BIGSERIAL PRIMARY KEY,
  user_id    BIGINT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  title      TEXT
);
CREATE TABLE app.message (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES app.conversation(id),
  role            TEXT NOT NULL,                     -- user/assistant
  content         TEXT,
  register        register,
  tool_calls      JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE app.tool_call_log (
  id         BIGSERIAL PRIMARY KEY,
  message_id BIGINT REFERENCES app.message(id),
  tool       TEXT NOT NULL,
  args       JSONB,
  result_ref TEXT,
  latency_ms INT,
  ok         BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- self-configuration / learning (M10–M11). scope JSONB shape:
--   { "kind":"once|category|entity|threshold|conditional",
--     "category":"fuel", "entity_type":"customer", "entity_id":123,
--     "metric":"spend_dev", "op":">", "value":0.50, "when":"season=summer" }
CREATE TABLE app.learned_rule (
  id                 BIGSERIAL PRIMARY KEY,
  source_signal_id   BIGINT REFERENCES app.signal(id),
  source_message_id  BIGINT REFERENCES app.message(id),
  domain             TEXT NOT NULL,                  -- sales/spend/...
  rule_type          TEXT NOT NULL,                  -- suppress/threshold/...
  scope              JSONB NOT NULL,
  description        TEXT NOT NULL,                   -- human-readable Bosnian, editable
  effect_estimate    JSONB,                           -- predicted/actual suppressed counts
  status             lr_status NOT NULL DEFAULT 'active',
  autonomy           autonomy NOT NULL,
  created_by         BIGINT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at         TIMESTAMPTZ
);
CREATE INDEX ix_learned_rule_active ON app.learned_rule(status) WHERE status='active';

CREATE TABLE app.decision (                           -- APPEND-ONLY: "show the decision on the platform"
  id                   BIGSERIAL PRIMARY KEY,
  kind                 decision_kind NOT NULL,
  actor                actor_kind NOT NULL,           -- 'valeri' (auto) or 'user'
  summary              TEXT NOT NULL,
  payload              JSONB,
  reversible           BOOLEAN NOT NULL DEFAULT true,
  reverted_decision_id BIGINT REFERENCES app.decision(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.suppression_hit (
  id              BIGSERIAL PRIMARY KEY,
  learned_rule_id BIGINT NOT NULL REFERENCES app.learned_rule(id),
  signal_id       BIGINT REFERENCES app.signal(id),
  suppressed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- investigation (M13)
CREATE TABLE app.investigation (
  id          BIGSERIAL PRIMARY KEY,
  trigger     TEXT NOT NULL,                          -- user/auto/signal
  question    TEXT NOT NULL,
  status      inv_status NOT NULL DEFAULT 'queued',
  model_tier  TEXT,
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  report      JSONB,                                  -- {narrative, findings[], confidence, next_step, trace_ref}
  thread_id   TEXT                                    -- LangGraph checkpoint thread
);
CREATE TABLE app.investigation_step (
  id               BIGSERIAL PRIMARY KEY,
  investigation_id BIGINT NOT NULL REFERENCES app.investigation(id),
  step_no          INT NOT NULL,
  node             TEXT,
  tool             TEXT,
  input            JSONB,
  output           JSONB,
  at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## auth (M8)

```sql
CREATE TABLE app.app_user (
  id            BIGSERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  role          user_role NOT NULL,
  password_hash TEXT NOT NULL,
  sales_rep_id  BIGINT REFERENCES core.sales_rep(id),  -- link a rep login to its rep row
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## audit — append-only

```sql
CREATE TABLE audit.ai_log (                            -- M6: one row per LLM call
  id           BIGSERIAL PRIMARY KEY,
  model        TEXT NOT NULL,
  masked_input JSONB NOT NULL,                          -- assert: no raw PII
  output       JSONB,
  confidence   NUMERIC(4,3),
  register     register,
  tokens       INT,
  latency_ms   INT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE audit.task_log (                           -- M5: task lifecycle
  id      BIGSERIAL PRIMARY KEY,
  task_id BIGINT REFERENCES app.task(id),
  event   TEXT NOT NULL,                                -- created/assigned/viewed/actioned/outcome/feedback
  payload JSONB,
  at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE audit.llm_route_log (                      -- M12
  id         BIGSERIAL PRIMARY KEY,
  request_id TEXT,
  task_role  TEXT,
  chosen_tier TEXT,
  model      TEXT,
  reason     TEXT,
  confidence NUMERIC(4,3),
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Phase-2 CRM (optional — only if the opportunity/pipeline product is approved)

```sql
CREATE TYPE opp_stage AS ENUM ('lead','qualified','proposal','negotiation','won','lost');

CREATE TABLE app.opportunity (
  id            BIGSERIAL PRIMARY KEY,
  customer_id   BIGINT NOT NULL REFERENCES core.customer(id),
  title         TEXT NOT NULL,
  value         NUMERIC(14,2),
  probability   NUMERIC(5,4),
  stage         opp_stage NOT NULL DEFAULT 'lead',
  source        TEXT,                                  -- referral/inbound/...
  expected_close DATE,
  owner_rep_id  BIGINT REFERENCES core.sales_rep(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE app.opportunity_stage_history (
  id             BIGSERIAL PRIMARY KEY,
  opportunity_id BIGINT NOT NULL REFERENCES app.opportunity(id),
  stage          opp_stage NOT NULL,
  at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE app.activity (                              -- rep activity (also enables "Aktivnosti komercijalista")
  id           BIGSERIAL PRIMARY KEY,
  sales_rep_id BIGINT NOT NULL REFERENCES core.sales_rep(id),
  customer_id  BIGINT REFERENCES core.customer(id),
  kind         TEXT NOT NULL,                            -- meeting/call/offer/follow_up/analysis
  done         BOOLEAN NOT NULL DEFAULT false,
  at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Notes
- The scanner reads `app.rule_config` **and** active `app.learned_rule` on every run.
- `staging.*` mirrors the source export columns; the ingest layer maps `staging` → `core`. Keep raw rows for traceability.
- Money is `NUMERIC`, never float. All timestamps `TIMESTAMPTZ`.
- LangGraph uses its Postgres checkpoint tables in the same DB (created by its migration/setup).
