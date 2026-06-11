/**
 * TanStack Query hooks, one group per api-spec section (frontend-spec §6).
 *
 * Query keys: ['dashboard'], ['tasks', filters], ['customers', filters], …
 * Mutations invalidate the affected keys. No server data ever lands in Zustand.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "./client"
import type {
  ActivityKind,
  ActivityRead,
  Approval,
  KbClarification,
  KbGraph,
  KbItemType,
  KbKnowledge,
  KbPendingQueue,
  ApplyResponse,
  ArticleRow,
  ChatHistory,
  ChatSession,
  CustomerDetail,
  CustomerRow,
  DashboardResponse,
  Decision,
  DismissResponse,
  IngestFileKey,
  ImportReport,
  ImportResult,
  ImportRunSummary,
  Investigation,
  InvestigationDetail,
  Items,
  LearnedRule,
  LearnedRuleDetail,
  LlmSettings,
  LlmSettingsPatch,
  LostArticleRow,
  MetricsStatus,
  RecomputeResult,
  ScanResult,
  Opportunity,
  PipelineResponse,
  OwnerReport,
  OwnerReportSummary,
  Paginated,
  InboxSummary,
  OpsStatus,
  LlmUsage,
  LlmRecentCall,
  LlmBudget,
  LlmUsageGroupBy,
  RepActivityBlock,
  RuleConfigChange,
  RuleConfigEntry,
  RuleScope,
  SignalRow,
  TaskCreate,
  TaskRow,
  User,
  UserCreate,
  UserUpdate,
} from "./types"

// ── auth ──────────────────────────────────────────────────────────────────────

export function useMe() {
  return useQuery<User>({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/api/auth/me"),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api.post<{ user: User }>("/api/auth/login", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>("/api/auth/logout"),
    onSuccess: () => queryClient.clear(),
  })
}

// ── dashboard / metrics ───────────────────────────────────────────────────────

export function useDashboard(range: string) {
  return useQuery<DashboardResponse>({
    queryKey: ["dashboard", range],
    queryFn: () => api.get<DashboardResponse>("/api/dashboard", { range }),
  })
}

// ── tasks ─────────────────────────────────────────────────────────────────────

export interface TaskFilters {
  status?: string
  assignee?: number
  rule?: string
  due?: "today" | "overdue"
}

export function useTasks(filters: TaskFilters = {}) {
  return useQuery<Paginated<TaskRow>>({
    queryKey: ["tasks", filters],
    queryFn: () =>
      api.get<Paginated<TaskRow>>("/api/tasks", { limit: 100, ...filters }),
  })
}

/** P1: create a manual task ("Novi zadatak" quick action). */
export function useCreateTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TaskCreate) => api.post<TaskRow>("/api/tasks", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
    },
  })
}

/** P1: the bell badge — what waits on a human (refetch on focus + 60s poll). */
export function useInboxSummary() {
  return useQuery<InboxSummary>({
    queryKey: ["inbox", "summary"],
    queryFn: () => api.get<InboxSummary>("/api/inbox/summary"),
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  })
}

/** P2: ops self-report for Postavke -> Podaci (owner/admin; 403 otherwise). */
export function useOpsStatus(enabled = true) {
  return useQuery<OpsStatus>({
    queryKey: ["ops", "status"],
    queryFn: () => api.get<OpsStatus>("/api/admin/ops/status"),
    enabled,
    retry: false,
  })
}

/** P3: LLM cost usage for the 'Troškovi AI' tab (owner/admin; 403 otherwise). */
export function useLlmUsage(groupBy: LlmUsageGroupBy = "feature", enabled = true) {
  return useQuery<LlmUsage>({
    queryKey: ["llmCost", "usage", groupBy],
    queryFn: () => api.get<LlmUsage>("/api/admin/llm/usage", { group_by: groupBy }),
    enabled,
    retry: false,
  })
}

export function useLlmRecent(enabled = true) {
  return useQuery<{ items: LlmRecentCall[] }>({
    queryKey: ["llmCost", "recent"],
    queryFn: () => api.get<{ items: LlmRecentCall[] }>("/api/admin/llm/recent", { limit: 10 }),
    enabled,
    retry: false,
  })
}

export function usePatchLlmBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { limit_usd: string; alert_pct: number }) =>
      api.patch<LlmBudget>("/api/admin/llm/budget", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llmCost"] })
      queryClient.invalidateQueries({ queryKey: ["ops"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
    },
  })
}

export function useTaskStatusMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, status }: { taskId: number; status: string }) =>
      api.post<TaskRow>(`/api/tasks/${taskId}/status`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
    },
  })
}

export function useTaskFeedbackMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      taskId,
      useful,
      reason,
    }: {
      taskId: number
      useful: boolean
      reason?: string
    }) => api.post(`/api/tasks/${taskId}/feedback`, { useful, reason }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  })
}

// ── customers ─────────────────────────────────────────────────────────────────

export interface CustomerFilters {
  query?: string
  segment?: string
  risk?: string
}

export function useCustomers(filters: CustomerFilters = {}) {
  return useQuery<Paginated<CustomerRow>>({
    queryKey: ["customers", filters],
    queryFn: () => api.get<Paginated<CustomerRow>>("/api/customers", { limit: 100, ...filters }),
  })
}

export function useCustomer(customerId: number | null) {
  return useQuery<CustomerDetail>({
    queryKey: ["customers", "detail", customerId],
    queryFn: () => api.get<CustomerDetail>(`/api/customers/${customerId}`),
    enabled: customerId !== null,
  })
}

// ── articles ──────────────────────────────────────────────────────────────────

export function useArticles(query?: string) {
  return useQuery<Paginated<ArticleRow>>({
    queryKey: ["articles", query],
    queryFn: () => api.get<Paginated<ArticleRow>>("/api/articles", { limit: 100, query }),
  })
}

export function useLostArticles(customerId?: number) {
  return useQuery<Items<LostArticleRow>>({
    queryKey: ["articles", "lost", customerId],
    queryFn: () =>
      api.get<Items<LostArticleRow>>("/api/articles/lost", { customer_id: customerId }),
  })
}

// ── signals ───────────────────────────────────────────────────────────────────

export function useSignals(rule?: string) {
  return useQuery<Paginated<SignalRow>>({
    queryKey: ["signals", rule],
    queryFn: () => api.get<Paginated<SignalRow>>("/api/signals", { limit: 100, rule }),
  })
}

export function useSignalFeedbackMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      signalId,
      useful,
      reason,
    }: {
      signalId: number
      useful: boolean
      reason?: string
    }) => api.post(`/api/signals/${signalId}/feedback`, { useful, reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["signals"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}

// ── self-configuration (M10) ──────────────────────────────────────────────────

/** Dismiss a signal with a reason → the learned-rule proposal (may auto-apply). */
export function useDismissSignalMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ signalId, reasonText }: { signalId: number; reasonText: string }) =>
      api.post<DismissResponse>(`/api/signals/${signalId}/dismiss`, { reason_text: reasonText }),
    onSuccess: () => {
      // The signal (and its open task) are dismissed server-side.
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["signals"] })
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["learnedRules"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

/** The one-tap confirm: activate a pending_confirm rule (writes the decision). */
export function useApplyRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (learnedRuleId: number) =>
      api.post<ApplyResponse>("/api/rules/apply", { learned_rule_id: learnedRuleId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["signals"] })
      queryClient.invalidateQueries({ queryKey: ["learnedRules"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

// ── learned rules + decisions (M11: "Šta je VALERI naučio") ───────────────────

export function useLearnedRules(status?: string) {
  return useQuery<Items<LearnedRule>>({
    queryKey: ["learnedRules", status],
    queryFn: () => api.get<Items<LearnedRule>>("/api/learned-rules", { status }),
  })
}

export function useLearnedRuleDetail(ruleId: number | null) {
  return useQuery<LearnedRuleDetail>({
    queryKey: ["learnedRules", "detail", ruleId],
    queryFn: () => api.get<LearnedRuleDetail>(`/api/learned-rules/${ruleId}`),
    enabled: ruleId !== null,
  })
}

export function useDecisions(kind?: string) {
  return useQuery<Items<Decision>>({
    queryKey: ["decisions", kind],
    queryFn: () => api.get<Items<Decision>>("/api/audit/decisions", { kind }),
  })
}

/** Edit a rule's scope (writes a reversible decision). */
export function useEditScopeMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, scope }: { ruleId: number; scope: RuleScope }) =>
      api.patch<ApplyResponse>(`/api/learned-rules/${ruleId}/scope`, { scope }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["learnedRules"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

/** Zadrži (M11): resolve a Na provjeri flag by keeping the rule (approval decision). */
export function useKeepRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (learnedRuleId: number) =>
      api.post<ApplyResponse>(`/api/learned-rules/${learnedRuleId}/keep`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["learnedRules"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

/** Undo a learned rule (status → reverted, writes a new decision). */
export function useUndoRuleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (learnedRuleId: number) =>
      api.post<ApplyResponse>(`/api/learned-rules/${learnedRuleId}/undo`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["signals"] })
      queryClient.invalidateQueries({ queryKey: ["learnedRules"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

// ── reports ───────────────────────────────────────────────────────────────────

export function useWeeklyReport() {
  return useQuery<OwnerReport>({
    queryKey: ["reports", "weekly"],
    queryFn: () => api.get<OwnerReport>("/api/reports/owner/weekly"),
    retry: false,
  })
}

export function useReportSummary() {
  return useQuery<OwnerReportSummary>({
    queryKey: ["reports", "summary"],
    queryFn: () => api.get<OwnerReportSummary>("/api/reports/owner/summary"),
    retry: false,
  })
}

// ── approvals ─────────────────────────────────────────────────────────────────

export function useApprovals(status?: string) {
  return useQuery<Items<Approval>>({
    queryKey: ["approvals", status],
    queryFn: () => api.get<Items<Approval>>("/api/approvals", { status }),
  })
}

export function useApprovalDecision() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      approvalId,
      decision,
      note,
    }: {
      approvalId: number
      decision: "approved" | "rejected" | "deferred"
      note?: string
    }) => api.post<Approval>(`/api/approvals/${approvalId}/decide`, { decision, note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
    },
  })
}

// ── settings ──────────────────────────────────────────────────────────────────

export function useRuleConfig() {
  return useQuery<Items<RuleConfigEntry>>({
    queryKey: ["settings", "rule-config"],
    queryFn: () => api.get<Items<RuleConfigEntry>>("/api/settings/rule-config"),
    retry: false,
  })
}

// ── opportunities / CRM (C-CRM1) ──────────────────────────────────────────────

export function useOpportunities(stage?: string) {
  return useQuery<Items<Opportunity>>({
    queryKey: ["opportunities", stage],
    queryFn: () => api.get<Items<Opportunity>>("/api/opportunities", { stage }),
    retry: false,
  })
}

export function usePipeline() {
  return useQuery<PipelineResponse>({
    queryKey: ["opportunities", "pipeline"],
    queryFn: () => api.get<PipelineResponse>("/api/opportunities/pipeline"),
    retry: false,
  })
}

export function useCreateOpportunity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      customer_id: number
      title: string
      value?: number
      probability?: number
      stage?: string
      source?: string
      expected_close?: string
    }) => api.post<Opportunity>("/api/opportunities", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["opportunities"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}

export function useUpdateOpportunity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: Record<string, unknown> }) =>
      api.patch<Opportunity>(`/api/opportunities/${id}`, changes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["opportunities"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}

// ── rep activity (C-CRM2) ─────────────────────────────────────────────────────

/** The sales-rep directory (id, name) — assignee selects (P1). */
export function useReps() {
  return useQuery<{ items: { id: number; name: string }[] }>({
    queryKey: ["reps", "directory"],
    queryFn: () => api.get<{ items: { id: number; name: string }[] }>("/api/reps"),
    staleTime: 5 * 60 * 1000,
  })
}

/** Per-rep activity rollup for a month (owner/admin/finance see all; reps their own). */
export function useRepActivity(date: string) {
  return useQuery<RepActivityBlock>({
    queryKey: ["reps", "activity", date],
    queryFn: () => api.get<RepActivityBlock>("/api/reps/activity", { date }),
    retry: false,
  })
}

/** Log one activity (rep's sales_rep_id is forced server-side; finance forbidden). */
export function useLogActivity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      kind: ActivityKind
      customer_id?: number
      done?: boolean
      sales_rep_id?: number
    }) => api.post<ActivityRead>("/api/activity", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reps", "activity"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
      queryClient.invalidateQueries({ queryKey: ["inbox"] })
    },
  })
}

// ── knowledge base / Client Intelligence (CI1) ────────────────────────────────

/** The 'Šta VALERI zna' panel for one customer (profile + facts + events + relationships). */
export function useCustomerKnowledge(customerId: number | null) {
  return useQuery<KbKnowledge>({
    queryKey: ["kb", "knowledge", customerId],
    queryFn: () => api.get<KbKnowledge>(`/api/customers/${customerId}/knowledge`),
    enabled: customerId !== null,
    retry: false,
  })
}

/** The relationship map around a customer (CI2): confirmed nodes + edges. */
export function useKbGraph(customerId: number | null, depth = 1) {
  return useQuery<KbGraph>({
    queryKey: ["kb", "graph", customerId, depth],
    queryFn: () => api.get<KbGraph>("/api/kb/graph", { customer_id: customerId ?? 0, depth }),
    enabled: customerId !== null,
    retry: false,
  })
}

/** The confirmation queue (Zabilješke): proposed records + pending clarifications. */
export function useKbPending() {
  return useQuery<KbPendingQueue>({
    queryKey: ["kb", "pending"],
    queryFn: () => api.get<KbPendingQueue>("/api/kb/pending"),
    retry: false,
  })
}

function useKbInvalidate() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ["kb"] })
    queryClient.invalidateQueries({ queryKey: ["decisions"] })
    queryClient.invalidateQueries({ queryKey: ["inbox"] })
  }
}

/** Confirm a proposed fact/event/relationship → active. */
export function useConfirmKbItem() {
  const invalidate = useKbInvalidate()
  return useMutation({
    mutationFn: ({ itemId, itemType }: { itemId: number; itemType: KbItemType | "relationship" }) =>
      api.post(`/api/kb/items/${itemId}/confirm?item_type=${itemType}`),
    onSuccess: invalidate,
  })
}

/** Reject a proposed record. */
export function useRejectKbItem() {
  const invalidate = useKbInvalidate()
  return useMutation({
    mutationFn: ({ itemId, itemType }: { itemId: number; itemType: KbItemType | "relationship" }) =>
      api.post(`/api/kb/items/${itemId}/reject?item_type=${itemType}`),
    onSuccess: invalidate,
  })
}

/** Answer a clarification (link / new prospect / not-a-match). */
export function useAnswerClarification() {
  const invalidate = useKbInvalidate()
  return useMutation({
    mutationFn: ({
      clarificationId,
      option,
    }: {
      clarificationId: number
      option: KbClarification["options"][number]
    }) => api.post(`/api/kb/clarifications/${clarificationId}/answer`, { option }),
    onSuccess: invalidate,
  })
}

// ── investigations (M13) ──────────────────────────────────────────────────────

export function useInvestigations(status?: string) {
  return useQuery<Items<Investigation>>({
    queryKey: ["investigations", status],
    queryFn: () => api.get<Items<Investigation>>("/api/investigations", { status }),
    retry: false,
  })
}

export function useInvestigation(investigationId: number | null) {
  return useQuery<InvestigationDetail>({
    queryKey: ["investigations", "detail", investigationId],
    queryFn: () => api.get<InvestigationDetail>(`/api/investigations/${investigationId}`),
    enabled: investigationId !== null,
    // Poll while the worker is processing it (queued/running → live progress).
    refetchInterval: (query) => {
      const status = query.state.data?.investigation.status
      return status === "queued" || status === "running" ? 3000 : false
    },
  })
}

export function useCreateInvestigation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { question: string; signal_id?: number }) =>
      api.post<{ investigation_id: number; status: string }>("/api/investigations", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["investigations"] }),
  })
}

export function useResumeInvestigation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      investigationId,
      decision,
    }: {
      investigationId: number
      decision: "approve" | "reject"
    }) => api.post(`/api/investigations/${investigationId}/resume`, { decision }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] })
      // Approved actions may have created tasks.
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}

// ── LLM routing settings (M12) ────────────────────────────────────────────────

export function useLlmSettings() {
  return useQuery<LlmSettings>({
    queryKey: ["settings", "llm"],
    queryFn: () => api.get<LlmSettings>("/api/settings/llm"),
    retry: false,
  })
}

export function usePatchLlmSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: LlmSettingsPatch) => api.patch<LlmSettings>("/api/settings/llm", patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "llm"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

export function useUsers() {
  return useQuery<Items<User>>({
    queryKey: ["settings", "users"],
    queryFn: () => api.get<Items<User>>("/api/settings/users"),
    retry: false,
  })
}

/** Admin: edit a detection threshold (writes a reversible decision server-side). */
export function usePatchRuleConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (changes: RuleConfigChange[]) =>
      api.patch<Items<RuleConfigEntry>>("/api/settings/rule-config", { changes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "rule-config"] })
      queryClient.invalidateQueries({ queryKey: ["decisions"] })
    },
  })
}

export function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UserCreate) => api.post<User>("/api/settings/users", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings", "users"] }),
  })
}

export function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: UserUpdate }) =>
      api.patch<User>(`/api/settings/users/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["settings", "users"] }),
  })
}

// ── data ingest (M2 + data-ingest-ui) ─────────────────────────────────────────

export function useImportRuns() {
  return useQuery<Items<ImportRunSummary>>({
    queryKey: ["ingest", "imports"],
    queryFn: () => api.get<Items<ImportRunSummary>>("/api/ingest/imports"),
    retry: false,
  })
}

export function useImportReport(importId: number | null) {
  return useQuery<ImportReport>({
    queryKey: ["ingest", "report", importId],
    queryFn: () => api.get<ImportReport>(`/api/ingest/report/${importId}`),
    enabled: importId !== null,
    retry: false,
  })
}

/** Import the 4 export files (multipart) → {import_id}. Invalidates the history list. */
export function useImportMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (files: Record<IngestFileKey, File>) => {
      const form = new FormData()
      for (const [key, file] of Object.entries(files)) form.append(key, file)
      return api.upload<ImportResult>("/api/ingest/import", form)
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ingest", "imports"] }),
  })
}

// ── admin: derived-metrics control (admin-recompute-panel) ─────────────────────

export function useMetricsStatus() {
  return useQuery<MetricsStatus>({
    queryKey: ["admin", "metrics-status"],
    queryFn: () => api.get<MetricsStatus>("/api/admin/metrics/status"),
    retry: false,
  })
}

/** Invalidate everything that reads the derived tables after a refresh. */
function useDerivedDataRefresh() {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ["admin", "metrics-status"] })
    queryClient.invalidateQueries({ queryKey: ["dashboard"] })
    queryClient.invalidateQueries({ queryKey: ["metrics"] })
    queryClient.invalidateQueries({ queryKey: ["customers"] })
    queryClient.invalidateQueries({ queryKey: ["signals"] })
  }
}

export function useRecomputeMutation() {
  const refresh = useDerivedDataRefresh()
  return useMutation({
    mutationFn: () => api.post<RecomputeResult>("/api/admin/metrics/recompute"),
    onSuccess: refresh,
  })
}

export function useRunScanMutation() {
  const refresh = useDerivedDataRefresh()
  return useMutation({
    mutationFn: () => api.post<ScanResult>("/api/admin/scan"),
    onSuccess: refresh,
  })
}

// ── chat (M9) ─────────────────────────────────────────────────────────────────

export function useChatSessions() {
  return useQuery<Items<ChatSession>>({
    queryKey: ["chat", "sessions"],
    queryFn: () => api.get<Items<ChatSession>>("/api/chat/sessions"),
  })
}

export function useChatHistory(sessionId: number | null) {
  return useQuery<ChatHistory>({
    queryKey: ["chat", "history", sessionId],
    queryFn: () => api.get<ChatHistory>(`/api/chat/sessions/${sessionId}`),
    enabled: sessionId !== null,
  })
}

export function useCreateChatSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ session_id: number }>("/api/chat/sessions"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["chat", "sessions"] }),
  })
}
