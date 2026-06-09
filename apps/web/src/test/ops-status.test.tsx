/** P2: the "Stanje sistema" panel (Postavke → Podaci) renders per-job ledger
 * rollups + alert reasons, and the bell dropdown gains the alerts entry. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { TopBar } from "@/app/TopBar"
import { OpsStatusPanel } from "@/components/widgets/OpsStatusPanel"
import { I18nProvider } from "@/lib/i18n"
import type { InboxSummary, OpsStatus, User } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const ownerUser: User = {
  id: 1,
  name: "Vlasnik",
  email: "vlasnik@ultrahigijena.ba",
  role: "owner",
  sales_rep_id: null,
  preferred_language: "bs",
  created_at: "2026-01-01T00:00:00Z",
}

const opsStatus: OpsStatus = {
  jobs: [
    {
      job: "daily_scan",
      last_status: "failed",
      last_run_at: "2026-06-08T06:00:00Z",
      last_ok_at: "2026-06-06T06:00:00Z",
      consecutive_failures: 2,
    },
    {
      job: "weekly_cycle",
      last_status: "ok",
      last_run_at: "2026-06-07T02:00:00Z",
      last_ok_at: "2026-06-07T02:00:00Z",
      consecutive_failures: 0,
    },
    {
      job: "backup_restore_check",
      last_status: null,
      last_run_at: null,
      last_ok_at: null,
      consecutive_failures: 0,
    },
  ],
  data_freshness: { last_invoice_date: "2026-06-08", stale: false, stale_days_threshold: 7 },
  alerts: [
    { kind: "job_failures", message: "Posao 'daily_scan' nije uspio 2 puta zaredom." },
    { kind: "backup_unverified", message: "Provjera backupa nije nedavno uspjela." },
  ],
}

const inboxWithAlerts: InboxSummary = {
  pending_approvals: 0,
  pending_clarifications: 0,
  proposed_kb_items: 0,
  tasks_due_today: 0,
  alerts: 2,
  total: 2,
}

function mockApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      const respond = (body: unknown) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      if (path.includes("/api/auth/me")) return respond(ownerUser)
      if (path.includes("/api/admin/ops/status")) return respond(opsStatus)
      if (path.includes("/api/inbox/summary")) return respond(inboxWithAlerts)
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: path } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
}

function renderWithProviders(element: React.ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>{element}</MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
  mockApi()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("OpsStatusPanel", () => {
  it("renders job rows with translated labels and statuses", async () => {
    renderWithProviders(<OpsStatusPanel />)
    await waitFor(() => expect(screen.getByTestId("ops-jobs")).toBeInTheDocument())

    const rows = screen.getAllByTestId("ops-job-row")
    expect(rows).toHaveLength(3)
    expect(screen.getByText("Dnevni sken")).toBeInTheDocument()
    expect(screen.getByText("neuspješno")).toBeInTheDocument()
    expect(screen.getByText("Sedmični ciklus")).toBeInTheDocument()
    // A job that never ran shows "nikad" (status + both timestamps).
    expect(screen.getByText("Provjera backupa (restore)")).toBeInTheDocument()
  })

  it("renders every alert reason and the freshness verdict", async () => {
    renderWithProviders(<OpsStatusPanel />)
    await waitFor(() => expect(screen.getAllByTestId("ops-alert")).toHaveLength(2))

    expect(screen.getByText(/daily_scan.*2 puta zaredom/)).toBeInTheDocument()
    expect(screen.getByText(/Provjera backupa nije nedavno uspjela/)).toBeInTheDocument()
    expect(screen.getByTestId("ops-freshness")).toHaveTextContent("Svježe")
  })
})

describe("bell alerts entry", () => {
  it("shows the alerts row linking to the system status", async () => {
    renderWithProviders(<TopBar />)
    await waitFor(() => expect(screen.getByTestId("inbox-badge")).toHaveTextContent("2"))

    // Radix menus open on pointer/keyboard, not synthetic click (jsdom).
    fireEvent.keyDown(screen.getByTestId("inbox-bell"), { key: "Enter" })
    await waitFor(() => expect(screen.getByTestId("inbox-alerts")).toBeInTheDocument())
    expect(screen.getByTestId("inbox-alerts")).toHaveTextContent("Sistemska upozorenja: 2")
  })
})
