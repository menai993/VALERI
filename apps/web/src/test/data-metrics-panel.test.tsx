/** admin-recompute-panel: the admin "Podaci i metrike" tab — shows derived-table
 * counts/freshness and triggers recompute/scan. Admin-only. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { SettingsPage } from "@/features/settings/SettingsPage"
import { I18nProvider } from "@/lib/i18n"
import type { MetricsStatus, User } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const adminUser: User = {
  id: 2,
  name: "Administrator",
  email: "admin@ultrahigijena.ba",
  role: "admin",
  sales_rep_id: null,
  preferred_language: "bs",
  created_at: "2026-01-01T00:00:00Z",
}
const ownerUser: User = { ...adminUser, id: 1, name: "Vlasnik", role: "owner" }

const status: MetricsStatus = {
  customer_metrics: { rows: 82, computed_at: "2026-06-03T20:00:00Z" },
  cust_article_cadence: { rows: 1007 },
  segment_basket: { rows: 24 },
  client_expectation: { rows: 82 },
  signals: { rows: 55, last_scan_at: "2026-06-03T20:05:00Z" },
  tasks: { rows: 0 },
}

function mockApi(user: User) {
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
      if (path.includes("/api/auth/me")) return respond(user)
      if (path.includes("/api/admin/metrics/status")) return respond(status)
      if (path.includes("/api/admin/metrics/recompute"))
        return respond({ rows: { "core.customer_metrics": 82 }, as_of: "2026-06-03" })
      if (path.includes("/api/admin/scan"))
        return respond({ inserted: 55, suppressed: 3, as_of: "2026-06-03" })
      if (path.includes("/api/settings/rule-config")) return respond({ items: [] })
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: path } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
}

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
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

describe("Settings → Podaci i metrike (admin-recompute-panel)", () => {
  it("renders the derived-table counts and last-computed time", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(adminUser)
    renderSettings()

    await waitFor(() => expect(screen.getByText("Podaci i metrike")).toBeInTheDocument())
    await user.click(screen.getByText("Podaci i metrike"))

    await waitFor(() => expect(screen.getByTestId("data-metrics-table")).toBeInTheDocument())
    const table = screen.getByTestId("data-metrics-table")
    expect(table).toHaveTextContent("82") // customer_metrics
    expect(table).toHaveTextContent("55") // signals
    expect(screen.getByTestId("data-metrics-computed-at")).toHaveTextContent("Zadnji put izračunato")
  })

  it("clicking 'Preračunaj sada' POSTs the recompute endpoint", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(adminUser)
    renderSettings()

    await waitFor(() => expect(screen.getByText("Podaci i metrike")).toBeInTheDocument())
    await user.click(screen.getByText("Podaci i metrike"))
    await waitFor(() => expect(screen.getByTestId("recompute-button")).toBeInTheDocument())

    await user.click(screen.getByTestId("recompute-button"))

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls
      const post = calls.find(
        ([url, init]) =>
          String(url).includes("/api/admin/metrics/recompute") &&
          (init as RequestInit | undefined)?.method === "POST",
      )
      expect(post).toBeDefined()
    })
  })

  it("a non-admin (owner) does not see the Data tab", async () => {
    mockApi(ownerUser)
    renderSettings()
    await waitFor(() => expect(screen.getByText("Pragovi detekcije")).toBeInTheDocument())
    expect(screen.queryByText("Podaci i metrike")).not.toBeInTheDocument()
  })
})
