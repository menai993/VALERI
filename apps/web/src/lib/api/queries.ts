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
  ArticleRow,
  CustomerDetail,
  CustomerRow,
  DashboardResponse,
  Items,
  LostArticleRow,
  OwnerReport,
  OwnerReportSummary,
  Paginated,
  RuleConfigEntry,
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

export function useUsers() {
  return useQuery<Items<User>>({
    queryKey: ["settings", "users"],
    queryFn: () => api.get<Items<User>>("/api/settings/users"),
    retry: false,
  })
}
