/** P1: completing a task offers "Šta je urađeno?" in the same flow — saving
 * posts the activity kind to /api/activity; Preskoči skips; due chips render. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/ui/toast"
import { TasksPage } from "@/features/tasks/TasksPage"
import { I18nProvider } from "@/lib/i18n"
import type { TaskRow } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const task: TaskRow = {
  id: 11,
  signal_id: 3,
  assignee_id: 2,
  assignee_name: "Amela Hodžić",
  owner_cc: false,
  title: "Kontaktirati kupca zbog pada prometa",
  body: "Promet je pao.",
  proposed_action: "Nazvati i ponuditi akciju.",
  due_date: "2026-06-09",
  status: "in_progress",
  register: "preporuka",
  created_at: "2026-06-08T10:00:00Z",
  rule: "customer_decline",
  confidence: "0.870",
  conf_band: "visoka",
  evidence: { metric: "turnover_60d" },
  customer_id: 7,
  customer_name: "Hotel Stari Grad",
}

function renderPage(calls: string[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push(`${init?.method ?? "GET"} ${url}`)
      if (url.includes("/api/activity")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ id: 1, sales_rep_id: 2, customer_id: 7, kind: "call",
              done: true, at: "2026-06-09T10:00:00Z" }),
            { status: 201, headers: { "Content-Type": "application/json" } },
          ),
        )
      }
      if (url.includes("/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ...task, status: "done" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [task], next_cursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/zadaci"]}>
            <TasksPage />
          </MemoryRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("task → activity flow", () => {
  it("marking done opens the activity prompt; saving posts the kind", async () => {
    const calls: string[] = []
    renderPage(calls)
    await waitFor(() => expect(screen.getByTestId("task-card")).toBeInTheDocument())
    expect(screen.getByText("Hotel Stari Grad")).toBeInTheDocument() // customer context

    fireEvent.click(screen.getByTestId("mark-done"))
    await waitFor(() => expect(screen.getByTestId("activity-prompt")).toBeInTheDocument())

    fireEvent.click(screen.getByTestId("activity-save"))
    await waitFor(() =>
      expect(calls.some((c) => c.startsWith("POST") && c.includes("/api/activity"))).toBe(true),
    )
    await waitFor(() => expect(screen.getByText("Aktivnost zabilježena.")).toBeInTheDocument())
  })

  it("Preskoči closes the prompt without posting an activity", async () => {
    const calls: string[] = []
    renderPage(calls)
    await waitFor(() => expect(screen.getByTestId("task-card")).toBeInTheDocument())
    fireEvent.click(screen.getByTestId("mark-done"))
    await waitFor(() => expect(screen.getByTestId("activity-prompt")).toBeInTheDocument())

    fireEvent.click(screen.getByTestId("activity-skip"))
    await waitFor(() =>
      expect(screen.queryByTestId("activity-prompt")).not.toBeInTheDocument(),
    )
    expect(calls.some((c) => c.startsWith("POST") && c.includes("/api/activity"))).toBe(false)
  })

  it("a manual task shows 'Ručni zadatak' instead of an AI register chip", async () => {
    const calls: string[] = []
    const manual = { ...task, id: 12, signal_id: null, rule: null, confidence: null,
      conf_band: null, evidence: null, customer_id: null, customer_name: null }
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ items: [manual], next_cursor: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    )
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <I18nProvider>
          <ToastProvider>
            <MemoryRouter initialEntries={["/zadaci"]}>
              <TasksPage />
            </MemoryRouter>
          </ToastProvider>
        </I18nProvider>
      </QueryClientProvider>,
    )
    await waitFor(() => expect(screen.getByTestId("manual-task-badge")).toBeInTheDocument())
    expect(screen.getByTestId("manual-task-badge")).toHaveTextContent("Ručni zadatak")
    expect(screen.queryByText("Preporuka")).not.toBeInTheDocument()
    expect(calls).toEqual([])
  })

  it("renders the Danas/Kasni due filter chips", async () => {
    renderPage([])
    await waitFor(() => expect(screen.getByTestId("due-today")).toBeInTheDocument())
    expect(screen.getByTestId("due-overdue")).toHaveTextContent("Kasni")
  })
})
