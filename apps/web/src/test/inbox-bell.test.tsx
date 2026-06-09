/** P1: the notifications bell — badge = the server total; the dropdown lists
 * per-category counts with links; zero → no badge (no decorative noise). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { TopBar } from "@/app/TopBar"
import { I18nProvider } from "@/lib/i18n"
import type { InboxSummary } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const fullInbox: InboxSummary = {
  pending_approvals: 2,
  pending_clarifications: 1,
  proposed_kb_items: 3,
  tasks_due_today: 4,
  alerts: 0,
  total: 10,
}

const emptyInbox: InboxSummary = {
  pending_approvals: 0,
  pending_clarifications: 0,
  proposed_kb_items: 0,
  tasks_due_today: 0,
  alerts: 0,
  total: 0,
}

function renderBar(inbox: InboxSummary) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes("/inbox/summary")
        ? inbox
        : { id: 1, name: "Vlasnik", email: "v@x.ba", role: "owner", sales_rep_id: null,
            preferred_language: "bs", created_at: "2026-01-01T00:00:00Z" }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <TopBar />
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

describe("inbox bell", () => {
  it("shows the total badge and per-category dropdown entries", async () => {
    renderBar(fullInbox)
    await waitFor(() => expect(screen.getByTestId("inbox-badge")).toHaveTextContent("10"))

    // Radix menus open on pointer/keyboard, not synthetic click (jsdom).
    fireEvent.keyDown(screen.getByTestId("inbox-bell"), { key: "Enter" })
    await waitFor(() => expect(screen.getByText(/Odobrenja na čekanju: 2/)).toBeInTheDocument())
    // Clarifications + proposed records combine into the Zabilješke entry (1+3).
    expect(screen.getByText(/Pitanja za pojašnjenje: 4/)).toBeInTheDocument()
    expect(screen.getByText(/Zadaci za danas: 4/)).toBeInTheDocument()
  })

  it("renders no badge when nothing is pending", async () => {
    renderBar(emptyInbox)
    await waitFor(() => expect(screen.getByTestId("inbox-bell")).toBeInTheDocument())
    expect(screen.queryByTestId("inbox-badge")).not.toBeInTheDocument()
  })
})
