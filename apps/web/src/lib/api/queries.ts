/**
 * TanStack Query hooks, one group per api-spec section (frontend-spec §6).
 *
 * Query keys: ['dashboard'], ['tasks', filters], ['customers', filters], …
 * Mutations invalidate the affected keys. No server data ever lands in Zustand.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "./client"
import type {
  Approval,
  ApplyResponse,
  ArticleRow,
  ChatHistory,
  ChatSession,
  CustomerDetail,
  CustomerRow,
  DashboardResponse,
  Decision,
  DismissResponse,
  Investigation,
  InvestigationDetail,
  Items,
  LearnedRule,
  LearnedRuleDetail,
  LlmSettings,
  LlmSettingsPatch,
  LostArticleRow,
  OwnerReport,
  OwnerReportSummary,
  Paginated,
  RuleConfigEntry,
  RuleScope,
  SignalRow,
  TaskRow,
  User,
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
}

export function useTasks(filters: TaskFilters = {}) {
  return useQuery<Paginated<TaskRow>>({
    queryKey: ["tasks", filters],
    queryFn: () =>
      api.get<Paginated<TaskRow>>("/api/tasks", { limit: 100, ...filters }),
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["approvals"] }),
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
