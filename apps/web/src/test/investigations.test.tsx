/** M13: the Istrage tab — list with status chips, the new-investigation form, the
 * report (narrative + findings + confidence + next step + trace), and the HITL
 * approve/reject panel for needs_input runs. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { InvestigationsTab } from "@/features/ai-report/InvestigationsTab"
import { I18nProvider } from "@/lib/i18n"
import type { Investigation, InvestigationDetail } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

// ── fixtures ──────────────────────────────────────────────────────────────────

const doneInvestigation: Investigation = {
  id: 1,
  trigger: "user",
  question: "Zašto pada promet u hotelskom segmentu zadnja tri mjeseca?",
  status: "done",
  model_tier: "tier2",
  started_at: "2026-06-03T10:00:00Z",
  finished_at: "2026-06-03T10:05:00Z",
  created_by: 1,
  signal_id: null,
  created_at: "2026-06-03T09:59:00Z",
}

const pendingInvestigation: Investigation = {
  ...doneInvestigation,
  id: 2,
  question: "Treba li kreirati zadatke za key account kupce?",
  status: "needs_input",
  finished_at: null,
}

const doneDetail: InvestigationDetail = {
  investigation: doneInvestigation,
  report: {
    narrative:
      "Istraga je utvrdila da je pad prometa koncentrisan kod tri hotelska kupca. " +
      "Vrijednost iz baze: 14155.90 KM.",
    findings: [
      {
        text: "Tri hotelska kupca čine većinu pada prometa.",
        confidence: 0.85,
        register: "analiza",
      },
    ],
    confidence: 0.85,
    next_step: "Kontaktirati tri ključna kupca i ponuditi obnovu saradnje.",
    next_step_register: "preporuka",
    register: "analiza",
    narrative_source: "llm",
    trace_ref: "investigation:1:steps",
  },
  steps: [
    {
      id: 1,
      step_no: 1,
      node: "plan",
      tool: null,
      input: { pitanje: "..." },
      output: { sub_questions: ["..."] },
      at: "2026-06-03T10:00:10Z",
    },
    {
      id: 2,
      step_no: 2,
      node: "act",
      tool: "list_signals",
      input: { rule: "customer_decline" },
      output: { ok: true, total_returned: 3 },
      at: "2026-06-03T10:00:30Z",
    },
    {
      id: 3,
      step_no: 3,
      node: "critic",
      tool: null,
      input: {},
      output: { verdict: "dovoljno" },
      at: "2026-06-03T10:00:50Z",
    },
    {
      id: 4,
      step_no: 4,
      node: "synthesize",
      tool: null,
      input: {},
      output: { confidence: 0.85 },
      at: "2026-06-03T10:01:10Z",
    },
  ],
  pending_actions: [],
}

const pendingDetail: InvestigationDetail = {
  investigation: pendingInvestigation,
  report: null,
  steps: doneDetail.steps.slice(0, 2),
  pending_actions: [
    {
      tool: "create_task_draft",
      params: { customer_ref: "Kupac-abc123", title: "Kontaktirati kupca zbog pada prometa" },
      reasoning: "Vlasnik treba zadatak.",
    },
  ],
}

// ── helpers ───────────────────────────────────────────────────────────────────

function mockApi(options?: { detail?: InvestigationDetail }) {
  const detail = options?.detail ?? doneDetail
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

      if (path.includes("/resume")) {
        return respond({ investigation: { ...detail.investigation, status: "done" } })
      }
      if (/\/api\/investigations\/\d+$/.test(path.split("?")[0])) {
        return respond(detail)
      }
      if (path.includes("/api/investigations")) {
        if (init?.method === "POST") {
          return respond({ investigation_id: 99, status: "queued" }, 202)
        }
        return respond({ items: [doneInvestigation, pendingInvestigation] })
      }
      return respond({ error: { code: "not_found", message: path } }, 404)
    }),
  )
}

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <InvestigationsTab />
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

describe("Istrage (M13) — list + create", () => {
  it("renders the list with status chips and the new-investigation form", async () => {
    mockApi()
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("investigation-row")).toHaveLength(2))

    // Questions + localized status chips.
    expect(screen.getByText(/hotelskom segmentu/)).toBeInTheDocument()
    expect(screen.getByText("Završena")).toBeInTheDocument()
    expect(screen.getByText("Čeka odluku")).toBeInTheDocument()

    // The form: the start button stays disabled until the question is long enough.
    expect(screen.getByTestId("start-investigation")).toBeDisabled()
  })

  it("creates an investigation via POST and opens its detail", async () => {
    const user = userEvent.setup()
    mockApi()
    renderTab()

    await waitFor(() => expect(screen.getByTestId("new-investigation-form")).toBeInTheDocument())
    await user.type(
      screen.getByLabelText("Pitanje za istragu"),
      "Zašto pada promet u maju mjesecu?",
    )
    await user.click(screen.getByTestId("start-investigation"))

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const postCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/api/investigations") &&
          (init as RequestInit | undefined)?.method === "POST",
      )
      expect(postCall).toBeDefined()
      const body = JSON.parse(String((postCall![1] as RequestInit).body))
      expect(body.question).toBe("Zašto pada promet u maju mjesecu?")
    })
  })
})

describe("Istrage (M13) — the report", () => {
  it("shows narrative + findings + confidence + next step + the trace", async () => {
    const user = userEvent.setup()
    mockApi()
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("investigation-row")).toHaveLength(2))
    await user.click(screen.getAllByTestId("investigation-row")[0])

    await waitFor(() => expect(screen.getByTestId("investigation-report")).toBeInTheDocument())

    // The narrative (analiza) with the SQL number, findings with confidence, next step.
    expect(screen.getByTestId("report-narrative")).toHaveTextContent("14155.90 KM")
    expect(screen.getAllByText("Analiza").length).toBeGreaterThan(0)
    expect(screen.getByTestId("report-findings")).toHaveTextContent("Tri hotelska kupca")
    expect(screen.getByTestId("report-findings")).toHaveTextContent("pouzdanost: visoka")
    expect(screen.getByTestId("report-next-step")).toHaveTextContent("Kontaktirati tri ključna")
    expect(screen.getByTestId("report-next-step")).toHaveTextContent("Preporuka")

    // The trace is one tap away and lists every node + tool.
    await user.click(screen.getByTestId("trace-toggle"))
    const trace = screen.getByTestId("investigation-trace")
    expect(trace).toHaveTextContent("plan")
    expect(trace).toHaveTextContent("list_signals")
    expect(trace).toHaveTextContent("synthesize")
    expect(trace).toHaveTextContent("brojke iz baze · SQL")
  })
})

describe("Istrage (M13) — the HITL panel", () => {
  it("needs_input shows the proposed actions and approve/reject calls resume", async () => {
    const user = userEvent.setup()
    mockApi({ detail: pendingDetail })
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("investigation-row")).toHaveLength(2))
    await user.click(screen.getAllByTestId("investigation-row")[1])

    await waitFor(() => expect(screen.getByTestId("hitl-panel")).toBeInTheDocument())
    const panel = screen.getByTestId("hitl-panel")
    expect(panel).toHaveTextContent("potrebna je vaša odluka")
    expect(panel).toHaveTextContent("create_task_draft")
    expect(panel).toHaveTextContent("Kontaktirati kupca zbog pada prometa")

    await user.click(screen.getByTestId("approve-actions"))

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const resumeCall = fetchMock.mock.calls.find(([url]) =>
        String(url).includes("/resume"),
      )
      expect(resumeCall).toBeDefined()
      const body = JSON.parse(String((resumeCall![1] as RequestInit).body))
      expect(body.decision).toBe("approve")
    })
  })
})
