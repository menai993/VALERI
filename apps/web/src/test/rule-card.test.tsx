/** M10: the functional RuleCard — dismiss → proposal → apply / auto-applied → undo.
 *
 * The API is mocked at the fetch level; every number shown must be the SQL number
 * from the response (the client never computes), and every state is visible.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RuleCard } from "@/components/widgets/RuleCard"
import { I18nProvider } from "@/lib/i18n"
import type { ApplyResponse, DismissResponse, InsightRow, LearnedRule } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

// ── fixtures ──────────────────────────────────────────────────────────────────

const insight: InsightRow = {
  signal_id: 42,
  rule: "customer_decline",
  customer_id: 7,
  customer_name: "Hotel Stari Grad — Objekat 1",
  segment: "hotel",
  task_id: 11,
  task_title: "Pad prometa: Hotel Stari Grad",
  confidence: "0.870",
  conf_band: "visoka",
  register: "analiza",
  evidence: { metric: "turnover_60d", value: "1200.00", baseline: "4000.00" },
  created_at: "2026-06-03T10:00:00Z",
}

const pendingRule: LearnedRule = {
  id: 5,
  source_signal_id: 42,
  source_message_id: null,
  domain: "sales",
  rule_type: "suppress",
  scope: { kind: "category", rule: "customer_decline", category: "kafić" },
  description: "Ne prijavljuj pad prometa za sve kafiće — sezonska djelatnost.",
  effect_estimate: { window_days: 90, total_signals: 7, by_rule: { customer_decline: 7 } },
  status: "pending_confirm",
  autonomy: "confirmed",
  created_by: 1,
  created_at: "2026-06-03T10:00:00Z",
  expires_at: null,
  suppression_count: 0,
  source_customer_name: "Hotel Stari Grad — Objekat 1",
  created_by_name: "Vlasnik",
  na_provjeri: false,
}

/** A broad (category) proposal → requires the one-tap confirm. */
const pendingResponse: DismissResponse = {
  signal_id: 42,
  proposal: {
    rule_type: "suppress",
    scope: { kind: "category", rule: "customer_decline", category: "kafić" },
    description: pendingRule.description,
    interpretation_confidence: 0.85,
  },
  effect_estimate: { window_days: 90, total_signals: 7, by_rule: { customer_decline: 7 } },
  requires_confirm: true,
  applied: false,
  learned_rule: pendingRule,
  decision_id: null,
  register: "preporuka",
}

/** A narrow (entity) proposal → auto-applied, reversible. */
const appliedResponse: DismissResponse = {
  signal_id: 42,
  proposal: {
    rule_type: "suppress",
    scope: { kind: "entity", rule: "customer_decline", entity_type: "customer" },
    description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac kupovine.",
    interpretation_confidence: 0.9,
  },
  effect_estimate: { window_days: 90, total_signals: 1, by_rule: { customer_decline: 1 } },
  requires_confirm: false,
  applied: true,
  learned_rule: {
    ...pendingRule,
    id: 6,
    scope: { kind: "entity", rule: "customer_decline", entity_type: "customer", entity_id: 7 },
    description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac kupovine.",
    status: "active",
    autonomy: "auto_applied",
  },
  decision_id: 11,
  register: "akcija",
}

const applyResponse: ApplyResponse = {
  learned_rule: { ...pendingRule, status: "active" },
  decision: {
    id: 12,
    kind: "suppression",
    actor: "user",
    summary: "Pravilo potvrđeno",
    payload: { learned_rule_id: 5 },
    reversible: true,
    reverted_decision_id: null,
    created_at: "2026-06-03T10:05:00Z",
  },
  register: "akcija",
}

const undoResponse: ApplyResponse = {
  learned_rule: { ...appliedResponse.learned_rule, status: "reverted" },
  decision: {
    id: 13,
    kind: "undo",
    actor: "user",
    summary: "Pravilo poništeno",
    payload: { learned_rule_id: 6, reverted_decision_id: 11 },
    reversible: true,
    reverted_decision_id: 11,
    created_at: "2026-06-03T10:10:00Z",
  },
  register: "akcija",
}

// ── helpers ───────────────────────────────────────────────────────────────────

function renderCard(onClose: () => void = () => {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RuleCard insight={insight} open onClose={onClose} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

/** Route fetch calls by URL substring → JSON response (or a 500 sentinel). */
function mockApi(routes: Record<string, unknown | "error">) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      for (const [route, body] of Object.entries(routes)) {
        if (path.includes(route)) {
          if (body === "error") {
            return Promise.resolve(
              new Response(JSON.stringify({ error: { code: "llm_failed", message: "boom" } }), {
                status: 502,
                headers: { "Content-Type": "application/json" },
              }),
            )
          }
          return Promise.resolve(
            new Response(JSON.stringify(body), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          )
        }
      }
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: path } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
}

async function submitReason(user: ReturnType<typeof userEvent.setup>, reason: string) {
  await user.type(screen.getByLabelText(/Razlog/), reason)
  await user.click(screen.getByTestId("submit-dismiss-button"))
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── tests ─────────────────────────────────────────────────────────────────────

describe("RuleCard (M10) — compose phase", () => {
  it("disables submit until a reason is entered", async () => {
    const user = userEvent.setup()
    mockApi({})
    renderCard()

    // Scope chips for the insight being dismissed.
    expect(screen.getByText("Pad prometa")).toBeInTheDocument()
    expect(screen.getByText("Hotel Stari Grad — Objekat 1")).toBeInTheDocument()

    const submit = screen.getByTestId("submit-dismiss-button")
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(/Razlog/), "Sezonski kupac")
    expect(submit).toBeEnabled()
  })
})

describe("RuleCard (M10) — pending proposal (requires confirm)", () => {
  it("dismissal sends the reason and shows the proposal: description, scope, SQL blast radius", async () => {
    const user = userEvent.setup()
    mockApi({ "/dismiss": pendingResponse })
    renderCard()

    await submitReason(user, "Svi kafići su sezonski")

    await waitFor(() => expect(screen.getByTestId("rule-proposal")).toBeInTheDocument())

    // The request carried the reason as reason_text.
    const fetchMock = vi.mocked(fetch)
    const dismissCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/signals/42/dismiss"),
    )
    expect(dismissCall).toBeDefined()
    expect(JSON.parse(String(dismissCall![1]!.body))).toEqual({
      reason_text: "Svi kafići su sezonski",
    })

    // The Bosnian description + register + status.
    expect(screen.getByTestId("rule-description")).toHaveTextContent(
      "Ne prijavljuj pad prometa za sve kafiće",
    )
    expect(screen.getByText("Preporuka")).toBeInTheDocument()
    expect(screen.getByText("Čeka potvrdu")).toBeInTheDocument()

    // The blast radius shows the SQL numbers verbatim, with the SQL footer.
    const effect = screen.getByTestId("effect-estimate")
    expect(effect).toHaveTextContent("7")
    expect(effect).toHaveTextContent("90")
    expect(effect).toHaveTextContent("brojke iz baze · SQL")

    // Interpretation confidence + the pending note + the confirm button.
    expect(screen.getByText(/pouzdanost tumačenja/)).toBeInTheDocument()
    expect(screen.getByTestId("status-note")).toHaveTextContent("potrebna je vaša potvrda")
    expect(screen.getByTestId("apply-rule-button")).toBeEnabled()
  })

  it("Primijeni calls /api/rules/apply and switches to the applied state with Undo", async () => {
    const user = userEvent.setup()
    mockApi({ "/dismiss": pendingResponse, "/rules/apply": applyResponse })
    renderCard()

    await submitReason(user, "Svi kafići su sezonski")
    await waitFor(() => expect(screen.getByTestId("apply-rule-button")).toBeInTheDocument())

    await user.click(screen.getByTestId("apply-rule-button"))

    await waitFor(() => expect(screen.getByTestId("undo-rule-button")).toBeInTheDocument())
    expect(screen.getByText("Akcija")).toBeInTheDocument()
    expect(screen.getByText("Primijenjeno (reverzibilno)")).toBeInTheDocument()
    expect(screen.getByTestId("status-note")).toHaveTextContent("poništiti")

    // The apply call carried the learned rule id.
    const fetchMock = vi.mocked(fetch)
    const applyCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/rules/apply"),
    )
    expect(JSON.parse(String(applyCall![1]!.body))).toEqual({ learned_rule_id: 5 })
  })
})

describe("RuleCard (M10) — auto-applied proposal", () => {
  it("a narrow proposal auto-applies: Akcija + reversible note + Undo, no confirm button", async () => {
    const user = userEvent.setup()
    mockApi({ "/dismiss": appliedResponse })
    renderCard()

    await submitReason(user, "Sezonski kupac, ne treba signal")

    await waitFor(() => expect(screen.getByTestId("rule-proposal")).toBeInTheDocument())
    expect(screen.getByText("Akcija")).toBeInTheDocument()
    expect(screen.getByText("Primijenjeno (reverzibilno)")).toBeInTheDocument()
    expect(screen.getByTestId("undo-rule-button")).toBeInTheDocument()
    expect(screen.queryByTestId("apply-rule-button")).not.toBeInTheDocument()
    expect(screen.getByTestId("status-note")).toHaveTextContent("poništiti")
  })

  it("Undo calls /api/learned-rules/{id}/undo and shows the undone note", async () => {
    const user = userEvent.setup()
    mockApi({ "/dismiss": appliedResponse, "/undo": undoResponse })
    renderCard()

    await submitReason(user, "Sezonski kupac, ne treba signal")
    await waitFor(() => expect(screen.getByTestId("undo-rule-button")).toBeInTheDocument())

    await user.click(screen.getByTestId("undo-rule-button"))

    await waitFor(() => expect(screen.getByTestId("undone-note")).toBeInTheDocument())
    expect(screen.getByTestId("undone-note")).toHaveTextContent("poništeno")

    // The undo endpoint was hit for the right rule.
    const fetchMock = vi.mocked(fetch)
    const undoCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/learned-rules/6/undo"),
    )
    expect(undoCall).toBeDefined()
  })
})

describe("RuleCard (M10) — errors", () => {
  it("shows an error (and no proposal) when the dismissal fails", async () => {
    const user = userEvent.setup()
    mockApi({ "/dismiss": "error" })
    renderCard()

    await submitReason(user, "Sezonski kupac")

    await waitFor(() => expect(screen.getByTestId("rule-card-error")).toBeInTheDocument())
    expect(screen.queryByTestId("rule-proposal")).not.toBeInTheDocument()
  })
})
