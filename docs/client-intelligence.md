# VALERI — Client Intelligence: conversational knowledge capture (`docs/client-intelligence.md`)

A module where VALERI’s users (owner, sales reps) **talk to the platform** and the LLM turns what they say into a **structured, queryable knowledge base** about customers — facts, commercial events (e.g. a deal), and relationships between customers — that later feeds deeper analysis. “Everything they speak about is relevant”: every message is run through extraction, but every captured record carries **provenance + confidence + evidence**, and consequential records are confirmed, not silently trusted. Build after the recovery MVP and the conversation layer (M9) and self-config provenance (M10–M11); depends on them.

Conventions follow `data-model.md`, `api-spec.md`, `architecture.md`, `frontend-spec.md`. Terminology: *users* = reps/owner who speak; *clients/kupci* = the customers the knowledge is about.

## 1. What it does (the deal example, end to end)

A rep types: *“Zaključio sam godišnji ugovor s Hotel Hills, oko 72.000 KM, kreću i s hemijom od idućeg mjeseca. Isti su vlasnik kao Hotel Europe.”*

VALERI, in the background (non-blocking; the chat answer comes normally):

1. **Extracts** structured candidates: a `commercial_event` (kind=deal, value 72.000 stated, category hemija, date≈today), a `client_fact` (intent = category_expansion → hemija), and a `client_relationship` (Hotel Hills ⇄ Hotel Europe, same_owner, **stated**).
1. **Resolves entities** — maps “Hotel Hills” and “Hotel Europe” to existing `core.customer` rows (fuzzy + alias); unresolved/ambiguous names are flagged.
1. **Merges** into the knowledge base — updates Hotel Hills’s profile summary, supersedes any stale “status/intent” fact, attaches the raw message as evidence.
1. **Applies by stakes** — the event and the expansion intent (high-confidence, low-stakes) are **auto-saved, reversible, and shown**; the *same_owner* relationship (consequential, stated) goes to a **confirmation queue** (“Potvrdi / Izmijeni / Odbaci”).
1. Later, this is **data for analysis**: the deal + expansion feed the owner report and rules; if the same_owner edge is confirmed, group-level risk reasoning can treat Hotel Hills and Hotel Europe together; the investigation agent can cite the deal.

## 2. Data model (additions; `app` schema)

```sql
CREATE TYPE fact_source AS ENUM ('data','inferred','stated');     -- where the record came from
CREATE TYPE kb_status   AS ENUM ('proposed','active','superseded','rejected');
CREATE TYPE event_kind  AS ENUM ('deal','meeting','call','complaint','quote','visit','note','other');
CREATE TYPE rel_type    AS ENUM ('same_owner','same_group','chain','shared_decision_maker',
                                 'referral','competitor','geographic_cluster','behavioral_twin','supplier_of');

CREATE TABLE app.client_profile (                  -- one living rollup per customer (LLM-maintained narrative + key qualitative fields)
  customer_id     BIGINT PRIMARY KEY REFERENCES core.customer(id),
  summary         TEXT,                            -- short Bosnian narrative VALERI keeps current
  decision_maker  TEXT,
  preferences     JSONB,                           -- {category_pref:[], price_sensitivity:'', channel:''...}
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE app.client_fact (                     -- atomic qualitative facts; dedup by (customer_id, fact_type, fact_key)
  id               BIGSERIAL PRIMARY KEY,
  customer_id      BIGINT NOT NULL REFERENCES core.customer(id),
  fact_type        TEXT NOT NULL,                  -- preference/constraint/decision_maker/intent/context/competitor/payment_note/...
  fact_key         TEXT NOT NULL,
  value            JSONB NOT NULL,
  source           fact_source NOT NULL,
  source_message_id BIGINT REFERENCES app.message(id),
  source_user_id   BIGINT,
  confidence       NUMERIC(4,3) NOT NULL,
  conf_band        conf_band NOT NULL,
  status           kb_status NOT NULL DEFAULT 'active',
  superseded_by    BIGINT REFERENCES app.client_fact(id),
  valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_fact_customer_active ON app.client_fact(customer_id) WHERE status='active';

CREATE TABLE app.commercial_event (                -- captured events: a deal, meeting outcome, complaint, quote...
  id               BIGSERIAL PRIMARY KEY,
  customer_id      BIGINT REFERENCES core.customer(id),
  kind             event_kind NOT NULL,
  summary          TEXT NOT NULL,
  value            NUMERIC(14,2),                  -- STATED value (provenance=stated), stored as data
  categories       JSONB,                          -- category/article ids or names mentioned
  occurred_on      DATE,
  source_message_id BIGINT REFERENCES app.message(id),
  source_user_id   BIGINT,
  confidence       NUMERIC(4,3) NOT NULL,
  status           kb_status NOT NULL DEFAULT 'active',
  opportunity_id   BIGINT,                          -- optional link if Phase-2 CRM is on
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_event_customer ON app.commercial_event(customer_id);

CREATE TABLE app.client_relationship (             -- the connect-the-dots graph; dedup by (from,to,rel_type)
  id               BIGSERIAL PRIMARY KEY,
  from_customer_id BIGINT NOT NULL REFERENCES core.customer(id),
  to_customer_id   BIGINT NOT NULL REFERENCES core.customer(id),
  rel_type         rel_type NOT NULL,
  source           fact_source NOT NULL,
  source_message_id BIGINT REFERENCES app.message(id),
  confidence       NUMERIC(4,3) NOT NULL,
  status           kb_status NOT NULL DEFAULT 'proposed',  -- consequential edges start 'proposed' (await confirm)
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_rel_from ON app.client_relationship(from_customer_id);
CREATE INDEX ix_rel_to   ON app.client_relationship(to_customer_id);

CREATE TABLE app.kb_extraction (                   -- one row per extraction pass (provenance/debug)
  id          BIGSERIAL PRIMARY KEY,
  message_id  BIGINT REFERENCES app.message(id),
  raw_text    TEXT,
  extracted   JSONB,                                -- candidate facts/events/edges before apply
  model       TEXT,
  confidence  NUMERIC(4,3),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

KB writes reuse `app.decision` (reversible, append-only) and the extraction LLM call writes `audit.ai_log`. A captured “deal” creates/updates `app.opportunity` only if the Phase-2 CRM track is enabled; otherwise it lives as a `commercial_event`.

## 3. Capture flow

On **every** user message (and any logged note), in parallel with the normal chat answer:

1. **Relevance gate (Tier-1):** skip pure questions/greetings; proceed if the message asserts something about a customer/deal/relationship. (Cost: Tier-1 + a short gate; runs async via the worker.)
1. **Extraction (Tier-1, structured output):** given the message + recent context + the user’s current customer focus, return typed candidates (facts/events/relationships) with `value`, `confidence`, and the **entities mentioned** — into a Pydantic schema; reject+retry malformed output; log to `app.kb_extraction`.
1. **Entity resolution (server-side, deterministic):** match mentioned names to `core.customer`/`article`/`sales_rep` via fuzzy + `article_alias` + recent context. No match → mark unresolved (offer “create prospect” / attach later). Ambiguous → flag for confirmation. This is the “connect the dots” step and it is **not** done by the model guessing IDs.
1. **Merge/dedup:** new fact about an existing `(customer, fact_type, fact_key)` supersedes the old (`superseded_by`); update `client_profile.summary`; never create duplicate facts/edges.
1. **Apply by stakes (graduated autonomy, same discipline as self-config):**
- high-confidence, low-stakes facts/events → **auto-save** (reversible, logged as `decision`, shown inline);
- consequential records (a relationship like same_owner, a negative fact, a large stated deal) or low confidence → **confirmation queue** (`status='proposed'`), nothing applied until confirmed.
1. **Provenance always:** every record links `source_message_id`, `source_user_id`, timestamp, `source` (stated/inferred/data), and confidence; the raw utterance is the evidence.

## 4. Guardrails (what makes rich capture safe)

- **Provenance + confidence + evidence on every record** — the owner can trace any fact/edge to the sentence and user that produced it.
- **Stated ≠ verified.** Consequential inferences are suggestions to confirm, never silent truth; confirmations/corrections are reversible and logged, and feed the extraction quality over time (the feedback loop).
- **Numbers for analysis come from SQL.** The LLM extracts qualitative facts and a *stated* deal value (stored as data, tagged `stated`); any aggregate/trend over events is computed by SQL, not the model.
- **No hallucinated facts.** Low-confidence extractions go to the queue, not the KB; a validation step checks each candidate is grounded in the message text.
- **Privacy scales with richness.** Personal PII (people’s emails/phones/personal data) is masked before the model; entity resolution runs server-side on real names; keep a **Zero-Data-Retention** agreement so free-text utterances aren’t retained by the API; the KB is internal to the distributor’s sales use, and client-to-client links are commercially sensitive — never exposed externally and never used for invasive profiling (commercial relevance only).
- **Reversible & visible.** Every KB write is an internal action that auto-applies only if reversible and shown; nothing customer-facing is sent.
- **Register tags:** captured facts are Analiza; suggested links are Preporuka; auto-saved writes are Akcija.

## 5. API (additions; see `api-spec.md` conventions)

- `POST /api/kb/capture` `{text, customer_id?}` → run extraction (also used for notes outside chat); returns proposed items (capture also runs automatically on `POST /chat/.../messages`).
- `POST /api/kb/notes` `{customer_id, text}` → log a note (also extracted).
- `GET /api/kb/pending` → confirmation queue (proposed facts/events/edges).
- `POST /api/kb/items/{id}/confirm` · `POST /api/kb/items/{id}/reject` · `PATCH /api/kb/items/{id}` → edit (each writes a reversible `decision`).
- `GET /api/customers/{id}/knowledge` → profile + active facts + events timeline + relationships.
- `GET /api/kb/graph?customer_id=&depth=` → relationship graph for the map.

## 6. Frontend (additions; see `frontend-spec.md`)

- **Client 360 → “Šta VALERI zna”** panel: profile summary; facts grouped by type with a source/confidence chip and Undo/Edit; a timeline of commercial events (the deal shows here); a mini relationship list.
- **Capture chip in chat:** after a message, a subtle inline “VALERI je zabilježio: …” with quick **Potvrdi / Poništi** (transparency — the user always sees what was captured).
- **Zabilješke / review queue:** a list of `proposed` items awaiting confirmation (Potvrdi / Izmijeni / Odbaci), with the source sentence shown.
- **Relationship map** (owner): a graph of customers and their edges (same_owner/group/referral/behavioral_twin), each edge labeled with source + confidence; click an edge to see its evidence.

## 7. How the knowledge base feeds deeper analysis

- **Client 360 & behavioral expectations:** facts + events enrich each customer’s profile and what VALERI expects from them (so deviations flag earlier).
- **Graph-aware rules:** confirmed edges enable group-level risk (treat a chain/owner’s objects together), behavioral-twin early warning (a twin of a churned client showing the same signs), and referral-source risk (a quiet referrer → its referrals at risk).
- **Owner report & investigation:** captured deals/events/facts appear in the weekly report and are available to the investigation agent via a `get_client_knowledge` tool (read-only, evidence-carrying).
- All of the above keep numbers in SQL and every AI line tagged with register + confidence + evidence.

This is a deeper version of Capability A (the business graph) extended from transactional to **relational + behavioral + qualitative**, leaning on Capability B (context) and F (feedback). Build it as the **Client Intelligence track** (below) after the MVP and conversation layer.

## 8. Entity resolution, disambiguation & clarification policy

VALERI **never forces an uncertain match or silently invents an entity or fact.** Resolution returns ranked candidates with a similarity/confidence; whether to auto-write, confirm, ask, or queue depends on **confidence × stakes**. Asking one short, specific question is the default reflex whenever something is ambiguous or high-stakes — and this applies to **any** ambiguity, not just customer names.

### 8.1 Resolution mechanics

- Match mentioned names against `core.customer` / `core.article` / `core.sales_rep` using Postgres `pg_trgm` similarity + full-text + the learned `app.customer_alias` table, plus recent conversation context (the entity the user is currently discussing). Deterministic and server-side — the model never guesses IDs.
- Return the top‑N candidates, each with a similarity score and a **distinguishing detail** (segment, location, last order) for disambiguation.

### 8.2 Decision matrix (confidence × stakes)

|Situation                                                                           |Action                                                                                          |
|------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
|Confident unique match + low-stakes fact                                            |Auto-attach (reversible, shown)                                                                 |
|Confident match + **high-stakes** fact (payment, churn, negative claim, large value)|**Confirm** (“samo da potvrdim…”) before writing                                                |
|Ambiguous (several close candidates, or one medium match)                           |**Ask** “da li ste mislili X ili Y?” + a “novi kupac” option; record stays `proposed`/unresolved|
|No reasonable candidate                                                             |**Ask** “novi kupac ‘Fupupu’?” or queue as unresolved                                           |

Thresholds — the auto-attach similarity cutoff and the stakes level that forces a confirm — live in `app.rule_config`, so caution is tunable (stricter for money/risk facts).

### 8.3 Ambiguity is general (not just names)

Clarification triggers for: **entity** (which customer/article/contact/supplier), **new-vs-existing**, **reference** (“them” / “the usual order” / “that café”), **merge** (same deal as one already captured?), **value/unit** (“70k” → KM? per year? total?), and **conflict** (statement contradicts a known fact). One short question per ambiguity, tappable options, dismissible/skippable; an unanswered item simply **stays in the review queue, never lost**. Asking is **non-blocking** — the chat keeps flowing; clarifications appear as inline chips or in the queue.

### 8.4 New tables

```sql
CREATE TABLE app.customer_alias (        -- confirmed nicknames/misspellings → first-class aliases (mirrors article_alias)
  alias        TEXT PRIMARY KEY,
  customer_id  BIGINT NOT NULL REFERENCES core.customer(id),
  source       fact_source NOT NULL DEFAULT 'stated',
  confidence   NUMERIC(4,3) NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE clar_kind AS ENUM ('entity','reference','merge','value','conflict','new_entity');
CREATE TABLE app.clarification (         -- the question/answer object
  id                BIGSERIAL PRIMARY KEY,
  kind              clar_kind NOT NULL,
  question          TEXT NOT NULL,
  options           JSONB NOT NULL,       -- [{label, action, ...ids}]
  target_record_ref TEXT NOT NULL,        -- e.g. "client_fact:proposed:123"
  status            TEXT NOT NULL DEFAULT 'pending',  -- pending/answered/dismissed
  answer            JSONB,
  answered_by       BIGINT,
  answered_at       TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Resolution consults `customer_alias` first. Answering a clarification writes a reversible `app.decision`, updates the target record, and may write a `customer_alias`.

### 8.5 Learning loop

Every answer teaches: confirming “Fupupu = Fupy” → a `customer_alias`; “same deal” → prevents a duplicate; resolving “them” → better reference resolution; a rejection → suppress that bad match. Resolution gets smarter and asks **less** over time.

### 8.6 Worked example — the Fupupu case (the build contract)

User says: *“kupac Fupupu kasni s plaćanjem.”* Real customer is **Fupy**.

(a) Extraction output:

```json
{ "facts": [ { "type": "payment_late", "mentioned_name": "Fupupu",
               "value": {"status": "late"}, "stakes": "high",
               "source": "stated", "confidence": 0.86,
               "evidence_span": "kupac Fupupu kasni s plaćanjem" } ],
  "events": [], "relationships": [] }
```

(b) Resolution result (medium / ambiguous):

```json
{ "mentioned_name": "Fupupu",
  "candidates": [ {"customer_id": 142, "name": "Fupy", "similarity": 0.55,
                   "segment": "kafić", "last_order": "2025-04-30"} ],
  "decision": "clarify",
  "reason": "high-stakes fact and no confident match" }
```

(c) Clarification raised (what the user sees / the stored object):

```json
{ "kind": "entity",
  "question": "Da li 'Fupupu' znači kupca Fupy (kafić, zadnja narudžba 30.04.), ili je to novi kupac?",
  "options": [
    {"label": "Da, Fupy", "action": "link", "customer_id": 142},
    {"label": "Nije — drugi kupac", "action": "pick_other"},
    {"label": "Novi kupac 'Fupupu'", "action": "create_prospect"} ],
  "target_record_ref": "client_fact:proposed:<id>", "status": "pending" }
```

**What is stored meanwhile:** a `client_fact` `payment_late` with `mentioned_name="Fupupu"`, `status='proposed'`, `customer_id` NULL (unresolved), `evidence` = the sentence, `confidence` from extraction. **Nothing lands on Fupy until the user answers.** On “Da, Fupy” → the fact re-links to customer 142, `status='active'`, a `customer_alias` “Fupupu”→142 is written, and a reversible `decision` is logged. On “Nije” → stays unresolved or becomes a new prospect; the bad match is remembered and not re-suggested.

### 8.7 Guardrails (unchanged)

Numbers come from SQL; the LLM extracts/proposes and **asks**, but never auto-asserts a high-stakes fact; every answer is a reversible, logged `decision` with provenance; ask **only** when ambiguous or high-stakes (tunable in `rule_config`) so the user is never nagged on confident, low-stakes saves.