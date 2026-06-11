/**
 * TypeScript mirrors of the API schemas (docs/api-spec.md).
 *
 * SQL-computed numbers arrive as exact strings — the client only formats them.
 * Every AI-derived row carries the response envelope (register/confidence/
 * conf_band/evidence).
 */

export type Register = "analiza" | "preporuka" | "akcija"
export type ConfBand = "niska" | "srednja" | "visoka"
export type RiskBand = "nizak" | "srednji" | "visok"
export type Role = "owner" | "sales_rep" | "finance" | "admin"
export type TaskStatus = "open" | "in_progress" | "done" | "dismissed"

export interface ApiError {
  error: { code: string; message: string; details?: Record<string, unknown> }
}

// ── admin: derived-metrics control (admin-recompute-panel) ─────────────────────

export interface TableStat {
  rows: number
  computed_at?: string | null
  last_scan_at?: string | null
}

export interface MetricsStatus {
  customer_metrics: TableStat
  cust_article_cadence: TableStat
  segment_basket: TableStat
  client_expectation: TableStat
  signals: TableStat
  tasks: TableStat
}

export interface RecomputeResult {
  rows: Record<string, number>
  as_of: string
}

export interface ScanResult {
  inserted: number
  suppressed: number
  as_of: string
}

// ── auth ──────────────────────────────────────────────────────────────────────

export interface User {
  id: number
  name: string
  email: string
  role: Role
  sales_rep_id: number | null
  preferred_language: string
  created_at: string
}

export interface UserCreate {
  name: string
  email: string
  role: Role
  password: string
  sales_rep_id?: number | null
  preferred_language?: string
}

export interface UserUpdate {
  name?: string
  role?: Role
  password?: string
  sales_rep_id?: number | null
  preferred_language?: string
}

export interface RuleConfigChange {
  rule: string
  param: string
  value: unknown
}

// ── data ingest (M2 + data-ingest-ui) ─────────────────────────────────────────

export interface ImportResult {
  import_id: number
}

export interface EntityStats {
  created: number
  updated: number
  unchanged: number
}
export interface LineStats {
  created: number
  replaced: number
  unchanged: number
}
export interface ImportStats {
  kupci: EntityStats
  artikli: EntityStats
  fakture: EntityStats
  stavke: LineStats
}

export interface DuplicateCode {
  code: string
  names: string[]
}
export interface RenamedArticle {
  code: string
  old_name: string
  new_name: string
}
export interface CodeSwapCandidate {
  old_code: string
  new_code: string
  name: string
  already_mapped: boolean
}
export interface MissingSegment {
  customer_code: string
  name: string
}
export interface OrphanLine {
  row_no: number
  broj_fakture: string | null
  sifra_artikla: string | null
  reason: string
}
export interface QualityReport {
  duplicate_customer_codes: DuplicateCode[]
  duplicate_article_codes: DuplicateCode[]
  renamed_articles: RenamedArticle[]
  code_swap_candidates: CodeSwapCandidate[]
  missing_segments: MissingSegment[]
  orphan_lines: OrphanLine[]
}

export interface ImportReport {
  import_id: number
  status: string
  source: string
  started_at: string
  finished_at: string | null
  stats: ImportStats | null
  quality: QualityReport | null
}

export interface ImportRunSummary {
  import_id: number
  source: string
  status: string
  started_at: string
  finished_at: string | null
  stats: ImportStats | null
}

export type IngestFileKey = "kupci" | "artikli" | "fakture" | "stavke"

// ── inbox (P1): what waits on a human — the bell badge ───────────────────────

export interface InboxSummary {
  pending_approvals: number
  pending_clarifications: number
  proposed_kb_items: number
  tasks_due_today: number
  alerts: number // P2: active ops alert conditions (owner/admin; others 0)
  total: number
}

// ── ops (P2): job ledger + freshness + alerts (Postavke → Podaci) ─────────────

export interface OpsJobStatus {
  job: string
  last_status: string | null
  last_run_at: string | null
  last_ok_at: string | null
  consecutive_failures: number
}

export interface OpsAlert {
  kind: string
  message: string
}

export interface OpsDataFreshness {
  last_invoice_date: string | null
  stale: boolean
  stale_days_threshold: number
}

export interface OpsStatus {
  jobs: OpsJobStatus[]
  data_freshness: OpsDataFreshness
  alerts: OpsAlert[]
}

// ── LLM cost (P3): the 'Troškovi AI' admin dashboard ─────────────────────────

export interface LlmUsageGroup {
  key: string | null
  cost_usd: string
  calls: number
  input_tokens: number
  output_tokens: number
}

export interface LlmBudget {
  period: string
  limit_usd: string | null
  alert_pct: number
  spent_usd: string
  pct: number | null
}

export interface LlmUsage {
  total: { cost_usd: string; input_tokens: number; output_tokens: number; calls: number }
  groups: LlmUsageGroup[]
  trend: { day: string; cost_usd: string }[]
  budget: LlmBudget
  cost_per_useful_task: { cost_usd: string; useful_tasks: number; value: number | null }
}

export interface LlmRecentCall {
  id: number
  created_at: string
  model: string
  tier: string | null
  feature: string | null
  user_id: number | null
  input_tokens: number | null
  output_tokens: number | null
  cached: boolean
  batched: boolean
  cost_usd: string | null
  latency_ms: number | null
}

export type LlmUsageGroupBy = "feature" | "model" | "user"

// ── envelope ──────────────────────────────────────────────────────────────────

export interface Envelope {
  register: Register
  confidence: string
  conf_band: ConfBand
  evidence: Record<string, unknown>
}

// ── dashboard / metrics ───────────────────────────────────────────────────────

export interface KpiTile {
  key: string
  value: string | number
  prior_value?: string | number | null
  delta_pct?: string | null
  delta_unit?: string | null
  spark: string[]
  progress?: { done: number; total: number } | null
}

export interface RevenueTrend {
  months: string[]
  revenue: string[]
  secondary: string[]
  substats: { key: string; value: string }[]
}

export interface AtRiskRow extends Envelope {
  signal_id: number
  customer_id: number
  customer_name: string
  segment: string | null
  last_order_date: string | null
  value: string
  baseline: string
  delta_pct: string
  risk_band: RiskBand
}

export interface LostArticleRow extends Envelope {
  signal_id: number
  customer_id: number
  customer_name: string
  segment: string | null
  article_id: number | null
  article_name: string | null
  article_code: string | null
  avg_interval_d: string | null
  gap_days: number | null
  last_seen: string | null
}

export interface InsightRow extends Envelope {
  signal_id: number
  rule: string
  customer_id: number
  customer_name: string
  segment: string | null
  task_id: number | null
  task_title: string | null
  created_at: string
}

export interface SummaryMetric {
  label: string
  value: string | number
  register: Register
}

export interface SummaryBullet {
  text: string
  register: Register
}

export interface OwnerReportSummary {
  week_start: string
  week_end: string
  metrics: SummaryMetric[]
  bullets: SummaryBullet[]
}

/** M11: one recently-hidden detection on the dashboard. */
export interface RecentlySuppressedRow {
  hit_id: number
  learned_rule_id: number
  description: string
  rule: string | null
  customer_id: number | null
  customer_name: string | null
  suppressed_at: string
}

export interface DashboardResponse {
  as_of: string
  range_days: number
  kpis: KpiTile[]
  revenue_trend: RevenueTrend
  ai_insights: InsightRow[]
  customers_at_risk: AtRiskRow[]
  lost_articles: LostArticleRow[]
  rep_activity: RepActivityBlock | null // C-CRM2: Aktivnosti komercijalista (null until logged)
  owner_report_summary: OwnerReportSummary | null
  recently_suppressed: RecentlySuppressedRow[]
  opportunities: OpportunitySummary | null // C-CRM1: the Prilike block (null until used)
  revenue_forecast: RevenueForecast | null // C-CRM2: revenue-vs-plan (null until a target is set)
}

// ── customers ─────────────────────────────────────────────────────────────────

export interface CustomerRow {
  id: number
  name: string
  segment: string | null
  status: string
  legal_entity_id: number
  legal_entity_name: string | null
  turnover_60d: string | null
  baseline_60d: string | null
  last_order_date: string | null
  risk_band: RiskBand | null
}

export interface CustomerBasketRow {
  category_id: number | null
  category_name: string | null
  n_articles: number
  total_spent: string
}

export interface Customer360 {
  customer_id: number
  customer_name: string
  segment: string | null
  status: string
  turnover_60d: string | null
  baseline_60d: string | null
  last_order_date: string | null
  avg_order_interval_d: string | null
  monthly_turnover: { month: string; revenue: string }[]
  basket: CustomerBasketRow[]
}

export interface CustomerDetail {
  customer: CustomerRow
  contacts: { id: number; name: string | null; email: string | null; phone: string | null }[]
  metrics: Customer360 | null
  signals: Record<string, unknown>[]
  tasks: Record<string, unknown>[]
}

// ── articles ──────────────────────────────────────────────────────────────────

export interface ArticleRow {
  id: number
  code: string
  name: string
  active: boolean
  category_id: number | null
  category_name: string | null
}

// ── tasks ─────────────────────────────────────────────────────────────────────

export interface TaskRow {
  id: number
  signal_id: number | null
  assignee_id: number | null
  assignee_name: string | null
  owner_cc: boolean
  title: string
  body: string | null
  proposed_action: string | null
  due_date: string | null
  status: TaskStatus
  register: Register
  created_at: string
  rule: string | null
  confidence: string | null
  conf_band: ConfBand | null
  evidence: Record<string, unknown> | null
  // Customer context joined via the signal (null for manual tasks — P1):
  customer_id: number | null
  customer_name: string | null
}

/** P1: a manual, user-created task (no signal, no AI envelope). */
export interface TaskCreate {
  title: string
  body?: string
  assignee_id: number
  due_date?: string
}

// ── reports ───────────────────────────────────────────────────────────────────

export interface ReportSection {
  key: string
  title: string
  register: Register
  narrative: string
  narrative_source: "llm" | "template"
  data: Record<string, unknown>
}

export interface OwnerReport {
  week_start: string
  week_end: string
  generated_at: string
  sections: ReportSection[]
}

// ── approvals ─────────────────────────────────────────────────────────────────

export interface Approval {
  id: number
  task_id: number | null
  kind: string
  status: "draft" | "pending_approval" | "approved" | "rejected" | "sent"
  payload: Record<string, unknown> | null
  decided_by: number | null
  decided_at: string | null
  register: "akcija"
}

// ── signals ───────────────────────────────────────────────────────────────────

export interface SignalRow extends Envelope {
  id: number
  rule: string
  customer_id: number | null
  customer_name: string | null
  article_id: number | null
  status: string
  created_at: string
  task_id: number | null
}

// ── settings ──────────────────────────────────────────────────────────────────

export interface RuleConfigEntry {
  rule: string
  param: string
  value: unknown
  updated_by: number | null
  updated_at: string | null
}

// ── LLM routing settings (M12) ────────────────────────────────────────────────

export interface LlmTierInfo {
  alias: string
  description: string
}

export interface LlmSettings {
  provider: string
  tiers: Record<string, LlmTierInfo>
  role_tiers: Record<string, string>
  escalation_confidence_threshold: number
  cascade_enabled: boolean
  cascade_max_escalations: number
  masking: "locked_on"
}

export interface LlmSettingsPatch {
  role_tiers?: Record<string, string>
  escalation_confidence_threshold?: number
  cascade_enabled?: boolean
}

// ── self-configuration (M10) ──────────────────────────────────────────────────

/** The resolved scope of a learned rule (data-model.md scope JSONB shape). */
export interface RuleScope {
  kind: "once" | "entity" | "category" | "threshold" | "conditional"
  rule?: string | null
  entity_type?: string | null
  entity_id?: number | null
  category?: string | null
  metric?: string | null
  op?: string | null
  value?: number | null
  when?: string | null
}

/** SQL-computed blast radius of a proposed rule. */
export interface EffectEstimate {
  window_days: number
  total_signals: number
  by_rule: Record<string, number>
}

export interface LearnedRule {
  id: number
  source_signal_id: number | null
  source_message_id: number | null
  domain: string
  rule_type: string
  scope: RuleScope
  description: string
  effect_estimate: EffectEstimate | null
  status: "pending_confirm" | "active" | "reverted" | "expired"
  autonomy: "auto_applied" | "confirmed"
  created_by: number | null
  created_at: string
  expires_at: string | null
  suppression_count: number
  // M11 — origin (rehydrated names) + the open Na provjeri flag:
  source_customer_name: string | null
  created_by_name: string | null
  na_provjeri: boolean
}

/** M11: one suppression hit joined to its suppressed signal — "what it hid". */
export interface SuppressionHitDetail {
  id: number
  learned_rule_id: number
  signal_id: number | null
  suppressed_at: string
  rule: string | null
  customer_id: number | null
  customer_name: string | null
  evidence: Record<string, unknown> | null
  confidence: number | null
  conf_band: ConfBand | null
}

/** GET /learned-rules/{id} response. */
export interface LearnedRuleDetail {
  rule: LearnedRule
  hits: SuppressionHitDetail[]
  decisions: Decision[]
}

export interface Decision {
  id: number
  kind: string
  actor: "valeri" | "user"
  summary: string
  payload: Record<string, unknown> | null
  reversible: boolean
  reverted_decision_id: number | null
  created_at: string
}

/** What Tier-1 proposed from the dismissal reason (description is Bosnian). */
export interface RuleChangeProposal {
  rule_type: string
  scope: RuleScope
  description: string
  interpretation_confidence: number
}

/** POST /signals/{id}/dismiss response: the proposal + whether it already applied. */
export interface DismissResponse {
  signal_id: number
  proposal: RuleChangeProposal
  effect_estimate: EffectEstimate
  requires_confirm: boolean
  applied: boolean
  learned_rule: LearnedRule
  decision_id: number | null
  register: "preporuka" | "akcija"
}

/** POST /rules/apply and /learned-rules/{id}/undo response. */
export interface ApplyResponse {
  learned_rule: LearnedRule
  decision: Decision
  register: "akcija"
}

// ── opportunities / CRM (C-CRM1) ──────────────────────────────────────────────

export type OppStage = "lead" | "qualified" | "proposal" | "negotiation" | "won" | "lost"

export interface Opportunity {
  id: number
  customer_id: number
  customer_name: string | null
  title: string
  value: string | null
  probability: string | null
  stage: OppStage
  source: string | null
  expected_close: string | null
  owner_rep_id: number | null
  owner_rep_name: string | null
  effective_probability: string | null
  weighted_value: string | null
  created_at: string
}

export interface PipelineStageColumn {
  stage: OppStage
  count: number
  value: string
  weighted_value: string
  opportunities: Opportunity[]
}

export interface PipelineResponse {
  stages: PipelineStageColumn[]
  total_weighted_value: string
  conversion_rate: string
  open_count: number
}

/** The dashboard 'Prilike' block (Otvorene prilike / Stopa konverzije / Najveće prilike). */
export interface OpportunitySummary {
  open_count: number
  conversion_rate: string
  weighted_value: string
  top: {
    id: number
    title: string
    customer_name: string | null
    value: string | null
    probability: string | null
    weighted_value: string
  }[]
}

// ── rep activity + forecasting (C-CRM2) ───────────────────────────────────────

export type ActivityKind = "meeting" | "call" | "offer" | "follow_up" | "analysis"

/** One rep's activity rollup for the month: counts by kind + completion (all SQL). */
export interface RepActivityRow {
  sales_rep_id: number
  name: string | null
  total: number
  done: number
  completion: string // done / total, "0.0000" when none
  by_kind: Record<string, number>
}

export interface RepActivityBlock {
  as_of: string
  reps: RepActivityRow[]
}

/** Revenue-vs-plan + a simple run-rate forecast for the current month (SQL/Python). */
export interface RevenueForecast {
  period: string // 'YYYY-MM'
  actual_mtd: string // SUM(invoice.total) this month
  target: string | null // revenue_target for the period (null if unset)
  variance: string | null // actual − target (null if no target)
  forecast: string // actual_mtd / days_elapsed × days_in_month
  days_elapsed: number
  days_in_month: number
}

export interface ActivityRead {
  id: number
  sales_rep_id: number
  customer_id: number | null
  kind: ActivityKind
  done: boolean
  at: string
}

// ── knowledge base / Client Intelligence (CI1) ────────────────────────────────

export type FactSource = "data" | "inferred" | "stated"
export type KbStatus = "proposed" | "active" | "superseded" | "rejected"
export type KbItemType = "fact" | "event"

/** A captured fact or commercial event (carries the AI envelope). */
export interface KbItem {
  item_type: KbItemType
  id: number
  customer_id: number | null
  customer_name: string | null
  mentioned_name: string | null
  title: string
  detail: Record<string, unknown> | null
  register: Register
  source: FactSource
  confidence: string
  conf_band: ConfBand
  status: KbStatus
  evidence_text: string | null
  source_message_id: number | null
  created_at: string
}

/** A captured customer↔customer relationship (a suggested link until confirmed). */
export interface KbRelationship {
  item_type: "relationship"
  id: number
  from_customer_id: number
  from_name: string | null
  to_customer_id: number
  to_name: string | null
  rel_type: string
  register: Register
  source: FactSource
  confidence: string
  conf_band: ConfBand
  status: KbStatus
  evidence_text: string | null
  created_at: string
}

export type ClarKind = "entity" | "reference" | "merge" | "value" | "conflict" | "new_entity"

export interface KbClarificationOption {
  label: string
  action: string
  customer_id?: number
}

export interface KbClarification {
  id: number
  kind: ClarKind
  question: string
  options: KbClarificationOption[]
  target_record_ref: string
  status: string
  created_at: string
}

export interface KbProfile {
  customer_id: number
  summary: string | null
  decision_maker: string | null
  preferences: Record<string, unknown> | null
  updated_at: string
}

export interface CaptureResponse {
  auto_saved: (KbItem | KbRelationship)[]
  proposed: (KbItem | KbRelationship)[]
  clarifications: KbClarification[]
}

export interface KbPendingQueue {
  facts: KbItem[]
  events: KbItem[]
  relationships: KbRelationship[]
  clarifications: KbClarification[]
}

export interface KbKnowledge {
  profile: KbProfile | null
  facts: KbItem[]
  events: KbItem[]
  relationships: KbRelationship[]
}

/** CI2 relationship map (GET /kb/graph) — confirmed nodes + edges only. */
export interface GraphNode {
  customer_id: number
  name: string | null
  segment: string | null
  risk_band: ConfBand | null
}

export interface GraphEdge {
  from: number
  to: number
  rel_type: string
  source: FactSource
  confidence: string
  evidence_message_id: number | null
}

export interface KbGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ── investigations (M13) ──────────────────────────────────────────────────────

export type InvestigationStatus = "queued" | "running" | "needs_input" | "done" | "failed"

export interface Investigation {
  id: number
  trigger: string
  question: string
  status: InvestigationStatus
  model_tier: string | null
  started_at: string | null
  finished_at: string | null
  created_by: number | null
  signal_id: number | null
  created_at: string
}

export interface InvestigationFinding {
  text: string
  confidence: number
  register: Register
}

/** The stored report (narrative + findings + next step), all Bosnian, numbers from SQL. */
export interface InvestigationReportData {
  narrative: string
  findings: InvestigationFinding[]
  confidence: number
  next_step: string
  next_step_register: Register
  register: Register
  narrative_source: "llm" | "template"
  budget_exhausted?: string
  trace_ref?: string
}

export interface InvestigationStep {
  id: number
  step_no: number
  node: string | null
  tool: string | null
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  at: string
}

export interface InvestigationDetail {
  investigation: Investigation
  report: InvestigationReportData | null
  steps: InvestigationStep[]
  pending_actions: Record<string, unknown>[]
}

// ── generic list shapes ───────────────────────────────────────────────────────

export interface Paginated<T> {
  items: T[]
  next_cursor: number | null
}

export interface Items<T> {
  items: T[]
}

// ── chat (M9) ─────────────────────────────────────────────────────────────────

export interface ChatSession {
  id: number
  title: string | null
  started_at: string
}

export interface ChatToolCall {
  tool: string
  params: Record<string, unknown>
  ok: boolean
  error_code: string | null
  narration_source: string
}

export interface ChatMessageRow {
  id: number
  role: "user" | "assistant"
  content: string | null
  register: Register | null
  tool_calls: ChatToolCall[] | null
  created_at: string
}

export interface ChatHistory {
  id: number
  title: string | null
  started_at: string
  messages: ChatMessageRow[]
}
