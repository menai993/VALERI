/** P1: the Odobrenja screen — pending list renders the draft (kind/customer/
 * message), Odobri fires the decide call, and the decision leaves the queue. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/ui/toast"
import { ApprovalsPage } from "@/features/approvals/ApprovalsPage"
import { I18nProvider } from "@/lib/i18n"
import type { Approval } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const pendingApproval: Approval = {
  id: 7,
  task_id: 12,
  kind: "message",
  status: "pending_approval",
  payload: {
    message: "Poštovani, primijetili smo pad narudžbi — možemo li pomoći?",
    customer_name: "Hotel Stari Grad",
    rule: "customer_decline",
  },
  decided_by: null,
  decided_at: null,
  register: "akcija",
}

function renderPage(items: Approval[], onDecide?: () => void) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/decide")) {
        onDecide?.()
        return Promise.resolve(
          new Response(JSON.stringify({ ...pendingApproval, status: "approved" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items }), {
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
          <MemoryRouter>
            <ApprovalsPage />
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

describe("ApprovalsPage", () => {
  it("renders a pending draft with kind, customer and message + one-tap actions", async () => {
    renderPage([pendingApproval])
    await waitFor(() => expect(screen.getByTestId("approval-card")).toBeInTheDocument())
    const card = screen.getByTestId("approval-card")
    expect(card).toHaveTextContent("Hotel Stari Grad")
    expect(card).toHaveTextContent("pad narudžbi")
    expect(card).toHaveTextContent("Akcija") // register chip — nothing happens silently
    expect(screen.getByTestId("approve-button")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Odbij" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Odgodi" })).toBeInTheDocument()
  })

  it("Odobri fires the decide endpoint and toasts", async () => {
    const onDecide = vi.fn()
    renderPage([pendingApproval], onDecide)
    await waitFor(() => expect(screen.getByTestId("approve-button")).toBeInTheDocument())
    fireEvent.click(screen.getByTestId("approve-button"))
    await waitFor(() => expect(onDecide).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Odobreno.")).toBeInTheDocument())
  })

  it("shows the empty state when nothing is pending", async () => {
    renderPage([])
    await waitFor(() =>
      expect(screen.getByText("Nema stavki koje čekaju odobrenje")).toBeInTheDocument(),
    )
  })
})
