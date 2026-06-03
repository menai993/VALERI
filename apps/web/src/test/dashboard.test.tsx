/** M8 test 14: DashboardPage with a mocked API — skeletons → all 5 zones render;
 * API error → error state; every AI surface carries the envelope widgets. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { DashboardPage } from "@/features/dashboard/DashboardPage"
import { I18nProvider } from "@/lib/i18n"
import type { DashboardResponse } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const dashboardFixture: DashboardResponse = {
  as_of: "2026-06-03",
  range_days: 30,
  kpis: [
    {
      key: "ukupan_prihod",
      value: "39751.20",
      prior_value: "45000.00",
      delta_pct: "-11.7",
      delta_unit: "%",
      spark: ["1000", "1200", "900", "1100", "1300", "800", "950", "1000"],
    },
    { key: "kupci_u_padu", value: 3, spark: [] },
    { key: "izgubljeni_artikli", value: 4, spark: [] },
    { key: "zadaci_danas", value: 5, spark: [], progress: { done: 2, total: 17 } },
  ],
  revenue_trend: {
    months: ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
             "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
    revenue: ["100", "200", "300", "400", "500", "600", "700", "800", "900", "1000", "1100", "1200"],
    secondary: ["90", "190", "290", "390", "490", "590", "690", "790", "890", "990", "1090", "1190"],
    substats: [
      { key: "ytd_prihod", value: "5700.00" },
      { key: "prosjecni_mjesecni", value: "650.00" },
      { key: "najbolji_mjesec", value: "1200.00" },
    ],
  },
  ai_insights: [
    {
      signal_id: 1,
      rule: "customer_decline",
      customer_id: 7,
      customer_name: "Hotel Stari Grad",
      segment: "hotel",
      task_id: 11,
      task_title: "Pad prometa",
      confidence: "0.870",
      conf_band: "visoka",
      register: "analiza",
      evidence: { metric: "turnover_60d", value: "1200.00", baseline: "4000.00" },
      created_at: "2026-06-03T10:00:00Z",
    },
  ],
  customers_at_risk: [
    {
      signal_id: 1,
      customer_id: 7,
      customer_name: "Hotel Stari Grad",
      segment: "hotel",
      last_order_date: "2026-05-20",
      value: "1200.00",
      baseline: "4000.00",
      delta_pct: "-70.0",
      risk_band: "visok",
      confidence: "0.870",
      conf_band: "visoka",
      register: "analiza",
      evidence: { metric: "turnover_60d", value: "1200.00" },
    },
  ],
  lost_articles: [
    {
      signal_id: 2,
      customer_id: 9,
      customer_name: "Restoran Una",
      segment: "restoran",
      article_id: 55,
      article_name: "Papirni ubrusi 2sl",
      article_code: "PAP-055",
      avg_interval_d: "14.5",
      gap_days: 102,
      last_seen: "2026-02-20",
      confidence: "0.910",
      conf_band: "visoka",
      register: "analiza",
      evidence: { article_code: "PAP-055", gap_days: 102 },
    },
  ],
  rep_activity: null,
  owner_report_summary: {
    week_start: "2026-06-01",
    week_end: "2026-06-07",
    metrics: [
      { label: "Promet sedmice (KM)", value: "9853.00", register: "analiza" },
      { label: "Kupci u padu", value: 3, register: "analiza" },
      { label: "Izgubljeni artikli", value: 4, register: "analiza" },
      { label: "Otvoreni zadaci", value: 17, register: "preporuka" },
    ],
    bullets: [
      { text: "Promet ove sedmice iznosi 9853.00 KM.", register: "analiza" },
      { text: "Tri kupca pokazuju značajan pad prometa.", register: "analiza" },
    ],
  },
  recently_suppressed: [],
  opportunities: null,
  revenue_forecast: null,
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <DashboardPage />
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

function mockFetch(response: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(response))
}

describe("DashboardPage", () => {
  it("shows skeletons while loading, then renders all five dashboard zones", async () => {
    let resolveFetch: (value: Response) => void = () => {}
    mockFetch(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve
        }),
    )

    renderDashboard()

    // Loading: KPI skeletons visible.
    expect(screen.getAllByTestId("card-skeleton").length).toBeGreaterThan(0)

    // Resolve the API call.
    resolveFetch(
      new Response(JSON.stringify(dashboardFixture), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )

    // Zone 1: KPI row (labels can repeat in the owner-report summary → getAllByText).
    await waitFor(() => expect(screen.getByText("Ukupan prihod")).toBeInTheDocument())
    expect(screen.getAllByText("Kupci u padu").length).toBeGreaterThan(0)

    // Zone 2: revenue chart + substats.
    expect(screen.getByText("Prihod")).toBeInTheDocument()
    expect(screen.getByTestId("substat-strip")).toBeInTheDocument()

    // Zone 3: AI uvidi with register + confidence + evidence.
    expect(screen.getByText("AI uvidi za Vas")).toBeInTheDocument()
    expect(screen.getAllByText("Analiza").length).toBeGreaterThan(0)
    expect(screen.getAllByText("pouzdanost: visoka").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Prikaži brojke").length).toBeGreaterThan(0)

    // Zone 4: at-risk + lost-articles tables.
    expect(screen.getByText("Top kupci u riziku")).toBeInTheDocument()
    expect(screen.getAllByText("Izgubljeni artikli").length).toBeGreaterThan(0)
    expect(screen.getByText("Visok")).toBeInTheDocument()
    expect(screen.getByText("Papirni ubrusi 2sl")).toBeInTheDocument()

    // Zone 5: honest empty rep-activity (no data logged) + owner report summary.
    expect(screen.getByText(/Nema evidentiranih aktivnosti/)).toBeInTheDocument()
    expect(screen.getByTestId("owner-report-summary")).toBeInTheDocument()
  })

  it("shows the error state when the API fails", async () => {
    mockFetch(() =>
      Promise.resolve(
        new Response(JSON.stringify({ error: { code: "internal", message: "boom" } }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )

    renderDashboard()

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument())
  })

  it("shows empty states when the API returns no rows", async () => {
    const empty: DashboardResponse = {
      ...dashboardFixture,
      ai_insights: [],
      customers_at_risk: [],
      lost_articles: [],
      owner_report_summary: null,
    }
    mockFetch(() =>
      Promise.resolve(
        new Response(JSON.stringify(empty), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )

    renderDashboard()

    await waitFor(() =>
      expect(screen.getAllByTestId("empty-state").length).toBeGreaterThanOrEqual(3),
    )
    expect(screen.getByText("Nema novih AI uvida")).toBeInTheDocument()
    // M11: no suppressions → the quiet list stays hidden entirely (no noise).
    expect(screen.queryByTestId("recently-suppressed")).not.toBeInTheDocument()
  })

  it("renders the recently-suppressed list when learned rules hid signals (M11)", async () => {
    const withSuppressed: DashboardResponse = {
      ...dashboardFixture,
      recently_suppressed: [
        {
          hit_id: 31,
          learned_rule_id: 5,
          description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac.",
          rule: "customer_decline",
          customer_id: 7,
          customer_name: "Hotel Stari Grad",
          suppressed_at: "2026-06-03T06:00:00Z",
        },
        {
          hit_id: 30,
          learned_rule_id: 5,
          description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac.",
          rule: "customer_decline",
          customer_id: 7,
          customer_name: "Hotel Stari Grad",
          suppressed_at: "2026-06-02T06:00:00Z",
        },
      ],
    }
    mockFetch(() =>
      Promise.resolve(
        new Response(JSON.stringify(withSuppressed), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )

    renderDashboard()

    await waitFor(() => expect(screen.getByTestId("recently-suppressed")).toBeInTheDocument())
    const list = screen.getByTestId("recently-suppressed")
    expect(list).toHaveTextContent("Nedavno potisnuto")
    expect(list).toHaveTextContent("Hotel Stari Grad")
    expect(list).toHaveTextContent("Pogledajte naučena pravila →")
  })

  it("renders rep activity + revenue-vs-plan once logged/targeted (C-CRM2)", async () => {
    const withCrm2: DashboardResponse = {
      ...dashboardFixture,
      rep_activity: {
        as_of: "2026-06-03",
        reps: [
          {
            sales_rep_id: 1,
            name: "Amela Hodžić",
            total: 5,
            done: 3,
            completion: "0.6000",
            by_kind: { meeting: 2, call: 1, offer: 1, follow_up: 1, analysis: 0 },
          },
        ],
      },
      revenue_forecast: {
        period: "2026-06",
        actual_mtd: "12000.00",
        target: "120000.00",
        variance: "-108000.00",
        forecast: "120000.00",
        days_elapsed: 3,
        days_in_month: 30,
      },
    }
    mockFetch(() =>
      Promise.resolve(
        new Response(JSON.stringify(withCrm2), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    )

    renderDashboard()

    // Rep-activity widget: the rep row + its completion (numbers from SQL).
    await waitFor(() => expect(screen.getByTestId("rep-activity")).toBeInTheDocument())
    const repBlock = screen.getByTestId("rep-activity")
    expect(repBlock).toHaveTextContent("Amela Hodžić")
    expect(repBlock).toHaveTextContent("60% završeno")
    // by_kind summary shows the non-zero kinds, hides analysis (0).
    expect(repBlock).toHaveTextContent("2 sastanci")
    expect(repBlock).not.toHaveTextContent("0 analize")

    // Revenue-vs-plan tile: actual / target / forecast / variance, all from SQL/Python.
    expect(screen.getByTestId("forecast-actual")).toHaveTextContent("12.000")
    expect(screen.getByTestId("forecast-target")).toHaveTextContent("120.000")
    expect(screen.getByTestId("forecast-projection")).toHaveTextContent("120.000")
    expect(screen.getByTestId("forecast-variance")).toBeInTheDocument()
  })
})
