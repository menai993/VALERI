# Spec — CI2: Graph-aware analysis & behavioral expectations

**Track:** Client Intelligence (optional, owner-approved) · **Builds on:** **CI1** (KB tables: `client_profile`, `client_fact`, `commercial_event`, `client_relationship`, `customer_alias`; confirm flow that activates edges), M3 (metrics/recompute), M4 (rule engine + scanner + `app.signal`), M5 (signal→task), M7 (owner report), M9/M13 (tool catalog + investigation agent) · **Status:** draft (awaiting owner review)

> **Sequencing — read first:** CI2 consumes **confirmed** (`status='active'`) `client_relationship` edges and the KB tables that **CI1 creates**. CI1 is specified and approved but **not yet implemented**. CI2 must be built **after CI1 ships** (its migration `0018`, the confirm flow, and the KB models must exist). This spec is written now so the design is ready; implementation waits on CI1. (See D9.)

## 1. Objective

Make the knowledge base **earn its keep**: use **confirmed** customer-to-customer edges and captured facts/events for deeper analysis. This is the **CI2** milestone (`docs/client-intelligence.md` §7). It delivers a per-client **behavioral-expectation model** (so deviations flag earlier), three **graph-aware detection rules** (group/owner-level risk over confirmed edges, behavioral-twin early warning, referral-source risk), the **relationship-map** view + `GET /kb/graph`, the inclusion of **captured deals/events/facts** in the weekly owner report, and a read-only **`get_client_knowledge`** tool so the investigation agent can cite KB facts with evidence. Every number is SQL-computed; only **confirmed** edges are used; every AI line carries register + confidence + evidence.

## 2. Scope

### In scope
- A per-client **behavioral-expectation** snapshot (`core.client_expectation`, recomputed by SQL) — expected order interval, expected categories, and current early-decline "signs" (interval-stretch ratio, gap-vs-expected). Numbers from SQL.
- Three graph-aware rules over **confirmed** edges, emitting `app.signal` (evidence + confidence) and flowing into the M5 task pipeline:
  - `group_risk` — owner/group/chain components decline treated **together**.
  - `behavioral_twin_warning` — a confirmed `behavioral_twin` of a churned/declined client showing the **same early signs**.
  - `referral_source_risk` — a confirmed `referral` whose **referrer goes quiet** → its referrals at risk.
- Graph traversal helper (connected component over confirmed edges) shared by rules + the map.
- `GET /api/kb/graph` (the CI1-deferred endpoint) + the **relationship-map** view (per-customer ego graph in "Šta VALERI zna").
- Weekly owner-report **captured-events section** (deals/events/facts from the KB, SQL aggregates + masked narrative, register-tagged).
- `get_client_knowledge` **read-only tool** (via `/tool`) added to the safe catalog **and** the investigation agent's `READ_ONLY_TOOLS`.
- Seed: planted graph cases (a same-owner group with a declining object, a behavioral-twin pair, a referral pair) so the rules fire deterministically.
- Thresholds in `app.rule_config` (never literals).

### Out of scope (deferred)
- Writing/creating relationships (that is CI1); CI2 only **reads confirmed** edges.
- New rel/edge types beyond CI1's `rel_type` enum; geographic-cluster / supplier_of analysis.
- Full owner-wide network map with layout physics (CI2 ships a per-customer ego graph; a global map is a later enhancement — D5).
- Document-sourced facts (DI1).
- Any LLM-computed number; any customer-facing send.

## 3. Files

```
apps/api/valeri_api/
  kb/graph.py                 # connected_group(session, customer_id, rel_types) + graph_for_customer()
                              #   — traversal over confirmed (status='active') edges only
  kb/service.py               # (edit) graph_for_customer() exposed for the /kb/graph endpoint
  metrics/expectations.py     # compute_expectations(session, as_of) → upsert core.client_expectation (SQL)
  metrics/recompute.py        # (edit) call compute_expectations in the recompute pass
  rules/group_risk.py         # RULE_NAME='group_risk'; SQL over confirmed owner/group/chain components
  rules/behavioral_twin.py    # RULE_NAME='behavioral_twin_warning'; SQL over confirmed behavioral_twin edges
  rules/referral_risk.py      # RULE_NAME='referral_source_risk'; SQL over confirmed referral edges
  scanner/scan.py             # (edit) add the three graph rules to ALL_RULES (no-op when no edges)
  tools/get_client_knowledge.py   # read-only tool: profile + active facts + confirmed events/edges + evidence
  tools/catalog.py            # (edit) register GET_CLIENT_KNOWLEDGE
  investigation/nodes.py      # (edit) add "get_client_knowledge" to READ_ONLY_TOOLS
  reports/builder.py          # (edit) _captured_events_section (key 'zabiljezeni_dogadjaji', register 'analiza')
  reports/sql/weekly_aggregates.sql  # (edit) captured-events aggregates (counts by kind, stated deal value)
  api/kb.py                   # (edit) GET /kb/graph?customer_id=&depth=
  seed/kb_graph.py            # plant confirmed edges + twin/referral patterns + supporting facts/events
  seed/{generate,loader,types}.py    # (edit) wire the graph seed
  migrations/versions/0019_client_expectations.py   # core.client_expectation table (+ indexes)

apps/api/tests/
  tests/fixtures/graph/*.py          # labeled graph fixtures (group, twin, referral; positive + must-not-fire)
  tests/test_expectations.py         # expectation numbers == SQL (TDD, numbers first)
  tests/test_group_risk.py           # confirmed same_owner group → one group signal (members together); proposed edge → none
  tests/test_behavioral_twin.py      # planted twin early-warning fires; twin without signs does NOT
  tests/test_referral_risk.py        # quiet referrer → referral flagged; active referrer → none
  tests/test_get_client_knowledge.py # tool returns confirmed KB with evidence+confidence; RBAC; in agent READ_ONLY_TOOLS
  tests/test_kb_graph_api.py         # /kb/graph: confirmed nodes+edges only; source+confidence; RBAC
  tests/test_reports.py              # (edit) captured-events section present, register-tagged, counts/value == SQL

apps/web/src/
  lib/api/types.ts            # (edit) GraphNode, GraphEdge, KbGraph
  lib/api/queries.ts          # (edit) useKbGraph(customerId, depth)
  components/widgets/RelationshipMap.tsx  # ego-graph (SVG, no new dep): nodes + labeled edges + evidence on click
  components/widgets/KnowledgePanel.tsx   # (edit, from CI1) mount RelationshipMap
  lib/i18n/bs.ts + en.ts      # (edit) graph/rel-type strings
  test/relationship-map.test.tsx          # renders nodes + labeled edges + edge evidence (source+confidence)
```

## 4. Data-model touchpoints

- **New (migration `0019`, `core` schema):** `core.client_expectation` — `customer_id BIGINT PK REFERENCES core.customer(id)`, `expected_interval_d NUMERIC(8,2)`, `expected_categories JSONB`, `gap_days INT`, `stretch_ratio NUMERIC(6,3)` (current interval ÷ expected), `early_decline BOOLEAN`, `computed_at TIMESTAMPTZ`. Recomputed by SQL (mirrors `core.customer_metrics`); never written by the LLM.
- **Reads (CI1 tables):** `app.client_relationship` (only `status='active'`), `app.commercial_event`/`app.client_fact` (only `status='active'`), `app.client_profile`. **Reads (core):** `customer`, `customer_metrics`, `cust_article_cadence`, `segment_basket`, `invoice`/`invoice_line`.
- **Writes:** `app.signal` (the three new rules; `evidence` JSONB carries member ids / cited twin / referrer + per-member SQL numbers; `confidence` + `conf_band` from SQL) → `app.task` via the M5 pipeline. No new signal columns (member set lives in `evidence`).
- **Thresholds (`app.rule_config`):** `group_risk.*`, `behavioral_twin_warning.*`, `referral_source_risk.*`, `client_expectation.*` (see D6). No new enums (CI1's `0018` already defines `rel_type`/`event_kind`/`kb_status`).
- No ERP/source writes; `app.decision`/`audit.ai_log` reused only by the report narrative (an LLM call) — the rules and tool make **no** mutation, so write no decision.

## 5. API touchpoints

- `GET /api/kb/graph?customer_id=&depth=` → `{nodes:[{customer_id,name,segment,risk_band?}], edges:[{from,to,rel_type,source,confidence,evidence_message_id}]}` — **confirmed edges only**; RBAC: a rep only its own customers (group members outside scope are returned as masked stubs or omitted — D-rbac in D7).
- `GET /api/reports/owner/weekly` → now includes the `zabiljezeni_dogadjaji` section (no path change).
- Safe-tool catalog gains `get_client_knowledge` (server-side only; not an HTTP route) — used by chat and the investigation agent.
- No changes to other endpoints.

## 6. Tests

**TDD order — numbers/rules/tool first, with labeled fixtures.**

- `test_expectations.py`
  - `test_expectation_numbers_match_sql` — `expected_interval_d`, `gap_days`, `stretch_ratio`, `early_decline` equal hand-computed SQL fixtures to the cent.
- `test_group_risk.py`
  - `test_confirmed_same_owner_group_fires_together` — two objects under a confirmed `same_owner` edge, one sharply declining → exactly **one** `group_risk` signal whose `evidence.members` = both customer ids and whose combined turnover/baseline == SQL. *(acceptance 1)*
  - `test_proposed_edge_does_not_trigger` — the same pair with the edge `status='proposed'` → **no** group signal (confirmed-only).
  - `test_healthy_group_does_not_fire` — a confirmed group with no decline → no signal.
- `test_behavioral_twin.py`
  - `test_twin_early_warning_fires` — confirmed `behavioral_twin` A↔B; A churned (sleeping/declined), B shows the same early signs (`stretch_ratio ≥ threshold`, gap) → a `behavioral_twin_warning` for **B** citing **A** in evidence. *(acceptance 2)*
  - `test_twin_without_signs_does_not_fire` — B healthy → no signal.
- `test_referral_risk.py`
  - `test_quiet_referrer_flags_referral` — confirmed `referral` R→X, R sleeping/declining → `referral_source_risk` on X citing R; active R → none.
- `test_get_client_knowledge.py`
  - `test_returns_confirmed_kb_with_evidence` — profile + active facts + confirmed events + confirmed edges, each with `evidence` (source sentence/message id) + `confidence`; **proposed** records excluded.
  - `test_rbac_blocks_out_of_scope` — a rep calling for a customer not theirs → `forbidden`.
  - `test_registered_for_agent` — `"get_client_knowledge"` is in `TOOLS` and in investigation `READ_ONLY_TOOLS`; `mutates is False`.
- `test_kb_graph_api.py`
  - `test_graph_confirmed_only` — `/kb/graph` returns only `status='active'` edges, each with source + confidence; proposed excluded.
  - `test_graph_rbac` — a rep's graph is limited to their visible customers.
- `test_reports.py` (edit)
  - `test_captured_events_section` — the weekly report has `zabiljezeni_dogadjaji`, register `analiza`, with event count + total stated deal value == SQL. *(acceptance 3)*
- `relationship-map.test.tsx`
  - renders nodes + labeled edges (rel_type) and reveals an edge's evidence (source + confidence) on click.

## 7. Acceptance criteria (matches IMPLEMENTATION-PLAN CI2)

1. A **confirmed** `same_owner` edge yields a **group-level** risk signal treating both objects **together** (members + combined SQL numbers in evidence); a `proposed` edge yields nothing.
2. A **behavioral-twin early warning** fires on the planted case (twin of a churned client showing the same signs) and stays quiet for a healthy twin.
3. The weekly **owner report includes captured events** (deals/events/facts), register-tagged, numbers from SQL.
4. The **investigation agent can cite KB facts with evidence** via the read-only `get_client_knowledge` tool (RBAC-checked, confirmed records only, no LLM-computed numbers).
5. Confirmed edges only; every AI line carries register + confidence + evidence.
6. Reviewers green: `tool-catalog-guardian`, `principle-reviewer`.

## 8. Principles compliance

| # | Principle | How CI2 honors it |
|---|-----------|-------------------|
| 1 | AI doesn't compute numbers | Expectations, group/twin/referral risk, and report aggregates are all SQL; rules emit confidence from SQL; the report narrative goes through `narrate_structured` (number contract). `get_client_knowledge` returns SQL/stored values only. |
| 2 | Evidence on every record | Every graph signal's `evidence` carries the member ids / cited twin / referrer + per-member numbers + the confirmed edge's `source_message_id`; the tool returns each record's source sentence. |
| 3 | Confidence on every conclusion | Each graph signal has `confidence` + `conf_band` (SQL); the tool returns each fact/edge's stored confidence. |
| 4 | No writes to source ERP | Reads only; rules write `app.signal`/`app.task` (VALERI's own DB). |
| 5 | Read-only / staging | Traversal, expectations, rules, tool are read-only SELECTs over `core`/`app`. |
| 6 | PII masking before AI | The only LLM call (report narrative) masks customer identity before the model; the tool/rules make no LLM call; graph data shown to humans is rehydrated server-side. |
| 7 | Append-only logs | Report narrative → `audit.ai_log`; graph signals follow the M4/M5 append-only signal/task/`task_log` path; no decision needed (no config change / mutation by rules or the tool). |
| 8 | Feedback loop is core | CI2 acts **only on confirmed** edges — the human confirmation from CI1 is the gate; nothing inferred is treated as truth. |
| 9 | Analysis/recommendation/action | Group/referral risk → `preporuka` (actionable); twin early-warning → `preporuka`; captured-events report section → `analiza` (D4). |
| 10 | Approval / reversible self-config | Graph rules create internal signals→tasks (no auto customer-facing send; drafts stay approval-gated per M7). The tool is read-only. No new self-config surface. |

## 9. Open questions (decision defaults — confirm or override)

- **D1 — expectation storage:** new `core.client_expectation` table recomputed by SQL **[recommended]** vs compute inline per-rule. Default: table (transparent, evidence-able, reusable).
- **D2 — scan integration:** add the three graph rules to `ALL_RULES` (they no-op without confirmed edges) **[recommended]** vs a separate `run_graph_scan`. Default: `ALL_RULES`.
- **D3 — group signal anchor:** `signal.customer_id` = the most-at-risk member, `evidence.members` = all member ids, task → that member's rep **[recommended]**.
- **D4 — registers:** `group_risk` + `referral_source_risk` = `preporuka`; `behavioral_twin_warning` = `preporuka`; captured-events report section = `analiza`. Confirm.
- **D5 — map scope:** per-customer **ego graph** (depth 1–2) in "Šta VALERI zna" for CI2 **[recommended]**; a global owner-wide network view deferred.
- **D6 — thresholds (`app.rule_config`):** `group_risk.decline_ratio=0.7`, `group_risk.min_members=2`; `behavioral_twin_warning.stretch_ratio=1.5`; `referral_source_risk.quiet_days=60`; `client_expectation.early_decline_stretch=1.4`. Default these (tunable).
- **D7 — graph RBAC for cross-scope members:** a rep's `/kb/graph` omits members outside their scope (fail-closed) rather than masking them **[recommended]**; group_risk tasks still assign to the at-risk member's own rep.
- **D8 — captured-events window:** events with `occurred_on` in the report week + the latest few facts **[recommended]** vs all-time. Default: the week + recent.
- **D9 — CI1 dependency (blocking):** CI2 requires CI1 merged (KB tables `0018` + confirm flow producing `status='active'` edges). **Build CI1 first.** Confirm you want the CI2 spec finalized now and implemented after CI1.
- **D10 — map rendering:** lightweight inline **SVG** ego graph, **no new dependency** **[recommended]** vs adding a graph library.
