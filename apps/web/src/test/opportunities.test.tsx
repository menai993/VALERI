/** C-CRM1: the Prilike screen — weighted-value header + kanban by stage + table;
 * creating an opportunity POSTs; changing a card's stage PATCHes. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { OpportunitiesPage } from "@/features/opportunities/OpportunitiesPage"
import { I18nProvider } from "@/lib/i18n"
import type { Opportunity, PipelineResponse } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

// ── fixtures ──────────────────────────────────────────────────────────────────

function opp(id: number, stage: Opportunity["stage"], over: Partial<Opportunity> = {}): Opportunity {
  return {
    id,
    customer_id: 7,
    customer_name: "Hotel Stari Grad",
    title: `Prilika ${id}`,
    value: "10000.00",
    probability: null,
    stage,
    source: "referral",
    expected_close: "2026-08-01",
    owner_rep_id: 1,
    owner_rep_name: "Amir",
    effective_probability: "0.5000",
    weighted_value: "5000.00",
    created_at: "2026-06-01T10:00:00Z",
    ...over,
  }
}

const pipeline: PipelineResponse = {
  stages: [
    { stage: "lead", count: 1, value: "3000.00", weighted_value: "300.00", opportunities: [opp(1, "lead")] },
    { stage: "qualified", count: 0, value: "0.00", weighted_value: "0.00", opportunities: [] },
    { stage: "proposal", count: 1, value: "12000.00", weighted_value: "6000.00", opportunities: [opp(2, "proposal")] },
    { stage: "negotiation", count: 0, value: "0.00", weighted_value: "0.00", opportunities: [] },
    { stage: "won", count: 1, value: "15400.00", weighted_value: "15400.00", opportunities: [opp(3, "won")] },
    { stage: "lost", count: 1, value: "4100.00", weighted_value: "0.00", opportunities: [opp(4, "lost")] },
  ],
  total_weighted_value: "6300.00",
  conversion_rate: "0.5000",
  open_count: 2,
}

// ── helpers ───────────────────────────────────────────────────────────────────

function mockApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request, init?: RequestInit) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      const respond = (body: unknown, status = 200) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          }),
        )
      if (path.includes("/api/opportunities/pipeline")) return respond(pipeline)
      if (path.includes("/api/opportunities")) {
        if (init?.method === "POST") return respond(opp(99, "lead"), 201)
        return respond({ items: [] })
      }
      if (path.includes("/api/customers")) {
        return respond({ items: [{ id: 7, name: "Hotel Stari Grad", segment: "hotel" }], next_cursor: null })
      }
      if (path.match(/\/api\/opportunities\/\d+$/) && init?.method === "PATCH") {
        return respond(opp(1, "qualified"))
      }
      return respond({ error: { code: "not_found", message: path } }, 404)
    }),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <OpportunitiesPage />
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

// ── tests ─────────────────────────────────────────────────────────────────────

describe("Prilike (C-CRM1)", () => {
  it("renders the weighted-value header, conversion, and kanban columns by stage", async () => {
    mockApi()
    renderPage()

    await waitFor(() => expect(screen.getByTestId("weighted-value")).toBeInTheDocument())
    // The weighted value + conversion come straight from the API (SQL numbers).
    expect(screen.getByTestId("weighted-value")).toHaveTextContent("6.300")
    expect(screen.getByTestId("conversion-rate")).toHaveTextContent("50")

    // Six kanban columns, one per stage; cards render in their column.
    const columns = screen.getAllByTestId("kanban-column")
    expect(columns).toHaveLength(6)
    expect(screen.getAllByTestId("opportunity-card").length).toBeGreaterThanOrEqual(4)
    // Each stage label appears (column headers + card stage selects → at least once).
    expect(screen.getAllByText("Lead").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Dobijeno").length).toBeGreaterThan(0)
  })

  it("creating an opportunity POSTs to /api/opportunities", async () => {
    const user = userEvent.setup()
    mockApi()
    renderPage()

    await waitFor(() => expect(screen.getByTestId("open-new-opp")).toBeInTheDocument())
    await user.click(screen.getByTestId("open-new-opp"))
    await waitFor(() => expect(screen.getByTestId("new-opportunity-dialog")).toBeInTheDocument())

    await user.type(screen.getByLabelText("Naziv prilike"), "Nova testna prilika")
    // The customer select is a Radix combobox; we drive the create via the value
    // already loaded — pick the seeded customer.
    await user.click(screen.getByTestId("opp-customer-select"))
    await user.click(await screen.findByRole("option", { name: "Hotel Stari Grad" }))

    await user.click(screen.getByTestId("submit-opportunity"))

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const postCall = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).endsWith("/api/opportunities") &&
          (init as RequestInit | undefined)?.method === "POST",
      )
      expect(postCall).toBeDefined()
      const body = JSON.parse(String((postCall![1] as RequestInit).body))
      expect(body.title).toBe("Nova testna prilika")
      expect(body.customer_id).toBe(7)
    })
  })

  it("changing a card's stage PATCHes the opportunity", async () => {
    const user = userEvent.setup()
    mockApi()
    renderPage()

    await waitFor(() => expect(screen.getByTestId("stage-select-1")).toBeInTheDocument())
    await user.click(screen.getByTestId("stage-select-1"))
    await user.click(await screen.findByRole("option", { name: "Kvalifikovano" }))

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const patchCall = fetchMock.mock.calls.find(
        ([u, init]) =>
          String(u).includes("/api/opportunities/1") &&
          (init as RequestInit | undefined)?.method === "PATCH",
      )
      expect(patchCall).toBeDefined()
      expect(JSON.parse(String((patchCall![1] as RequestInit).body)).stage).toBe("qualified")
    })
  })
})
