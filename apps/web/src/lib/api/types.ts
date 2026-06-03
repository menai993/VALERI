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
  rep_activity: null
  owner_report_summary: OwnerReportSummary | null
  recently_suppressed: RecentlySuppressedRow[]
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
