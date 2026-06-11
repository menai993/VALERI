/** P3: the 'Troškovi AI' panel renders spend-vs-budget, breakdown rows, and the
 * recent expensive calls; an admin editing the budget fires the PATCH. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LlmCostPanel } from "@/components/widgets/LlmCostPanel"
import { I18nProvider } from "@/lib/i18n"
import type { LlmRecentCall, LlmUsage } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const usage: LlmUsage = {
  total: { cost_usd: "12.50", input_tokens: 100000, output_tokens: 40000, calls: 320 },
  groups: [
    { key: "investigation", cost_usd: "8.00", calls: 12, input_tokens: 60000, output_tokens: 30000 },
    { key: "narration", cost_usd: "4.50", calls: 308, input_tokens: 40000, output_tokens: 10000 },
  ],
  trend: [{ day: "2026-06-10", cost_usd: "12.50" }],
  budget: { period: "2026-06", limit_usd: "50.00", alert_pct: 80, spent_usd: "12.50", pct: 25.0 },
  cost_per_useful_task: { cost_usd: "12.50", useful_tasks: 25, value: 0.5 },
}

const recent: { items: LlmRecentCall[] } = {
  items: [
    {
      id: 1,
      created_at: "2026-06-10T10:00:00Z",
      model: "claude-opus-4-8",
      tier: "tier2_strong",
      feature: "investigation",
      user_id: 2,
      input_tokens: 1000,
      output_tokens: 1000,
      cached: false,
      batched: false,
      cost_usd: "0.030000",
      latency_ms: 1200,
    },
  ],
}

let patchBody: unknown = null

function mockApi(usageOverride?: Partial<LlmUsage>) {
  patchBody = null
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
      if (path.includes("/api/admin/llm/usage")) return respond({ ...usage, ...usageOverride })
      if (path.includes("/api/admin/llm/recent")) return respond(recent)
      if (path.includes("/api/admin/llm/budget")) {
        patchBody = init?.body ? JSON.parse(init.body as string) : null
        return respond({ ...usage.budget, limit_usd: "120.00" })
      }
      return respond({ error: { code: "not_found", message: path } }, 404)
    }),
  )
}

function renderPanel(isAdmin: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <LlmCostPanel isAdmin={isAdmin} />
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

describe("LlmCostPanel", () => {
  it("renders spend, budget percent, breakdown rows and recent calls", async () => {
    mockApi()
    renderPanel(false)
    await waitFor(() => expect(screen.getByTestId("llm-spend")).toBeInTheDocument())

    expect(screen.getByTestId("llm-spend")).toHaveTextContent("$12.50")
    expect(screen.getByTestId("llm-spend")).toHaveTextContent("25%")
    await waitFor(() => expect(screen.getAllByTestId("llm-group-row")).toHaveLength(2))
    expect(screen.getByTestId("llm-breakdown")).toHaveTextContent("investigation")
    expect(screen.getByTestId("llm-cput")).toHaveTextContent("$0.50")
    await waitFor(() => expect(screen.getByTestId("llm-recent")).toBeInTheDocument())
  })

  it("hides the budget editor for a non-admin owner", async () => {
    mockApi()
    renderPanel(false)
    await waitFor(() => expect(screen.getByTestId("llm-spend")).toBeInTheDocument())
    expect(screen.queryByTestId("llm-edit-budget")).not.toBeInTheDocument()
  })

  it("lets an admin edit the budget and fires the PATCH", async () => {
    mockApi()
    renderPanel(true)
    await waitFor(() => expect(screen.getByTestId("llm-edit-budget")).toBeInTheDocument())

    fireEvent.click(screen.getByTestId("llm-edit-budget"))
    const inputs = screen.getByTestId("llm-budget-form").querySelectorAll("input")
    fireEvent.change(inputs[0], { target: { value: "120.00" } })
    fireEvent.click(screen.getByTestId("llm-save-budget"))

    await waitFor(() => expect(patchBody).toEqual({ limit_usd: "120.00", alert_pct: 80 }))
  })
})
