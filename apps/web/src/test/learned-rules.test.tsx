/** M11: the "Šta je VALERI naučio" tab — every learned rule with origin/effect/status/
 * Na provjeri, viewable "what it hid" evidence, Undo/Zadrži actions, and the decision feed.
 *
 * The API is mocked at the fetch level; every number/name shown must come from the
 * mocked SQL responses (the client never computes).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LearnedTab } from "@/features/ai-report/LearnedTab"
import { I18nProvider } from "@/lib/i18n"
import type { ApplyResponse, Decision, LearnedRule, LearnedRuleDetail } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

// ── fixtures (what the SQL-backed API returns) ────────────────────────────────

const activeRule: LearnedRule = {
  id: 1,
  source_signal_id: 42,
  source_message_id: null,
  domain: "sales",
  rule_type: "suppress",
  scope: { kind: "entity", rule: "customer_decline", entity_type: "customer", entity_id: 7 },
  description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac kupovine.",
  effect_estimate: { window_days: 90, total_signals: 1, by_rule: { customer_decline: 1 } },
  status: "active",
  autonomy: "auto_applied",
  created_by: 1,
  created_at: "2026-06-01T10:00:00Z",
  expires_at: null,
  suppression_count: 3,
  source_customer_name: "Hotel Stari Grad — Objekat 1",
  created_by_name: "Vlasnik",
  na_provjeri: false,
}

const flaggedRule: LearnedRule = {
  ...activeRule,
  id: 2,
  scope: { kind: "category", rule: "customer_decline", category: "kafić" },
  description: "Ne prijavljuj pad prometa za sve kafiće — sezonska djelatnost.",
  autonomy: "confirmed",
  suppression_count: 9,
  source_customer_name: null,
  na_provjeri: true,
}

const revertedRule: LearnedRule = {
  ...activeRule,
  id: 3,
  description: "Poništeno pravilo za testiranje statusa.",
  status: "reverted",
  suppression_count: 0,
  na_provjeri: false,
}

const detailResponse: LearnedRuleDetail = {
  rule: activeRule,
  hits: [
    {
      id: 11,
      learned_rule_id: 1,
      signal_id: 101,
      suppressed_at: "2026-06-02T06:00:00Z",
      rule: "customer_decline",
      customer_id: 7,
      customer_name: "Hotel Stari Grad — Objekat 1",
      evidence: { metric: "turnover_60d", value: "1200.00", baseline: "4000.00", ratio: "0.30" },
      confidence: 0.87,
      conf_band: "visoka",
    },
    {
      id: 12,
      learned_rule_id: 1,
      signal_id: 101,
      suppressed_at: "2026-06-03T06:00:00Z",
      rule: "customer_decline",
      customer_id: 7,
      customer_name: "Hotel Stari Grad — Objekat 1",
      evidence: { metric: "turnover_60d", value: "900.00", baseline: "4000.00", ratio: "0.22" },
      confidence: 0.91,
      conf_band: "visoka",
    },
  ],
  decisions: [],
}

const decisions: Decision[] = [
  {
    id: 21,
    kind: "suppression",
    actor: "valeri",
    summary: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac kupovine.",
    payload: { learned_rule_id: 1 },
    reversible: true,
    reverted_decision_id: null,
    created_at: "2026-06-01T10:00:00Z",
  },
  {
    id: 22,
    kind: "reactivation",
    actor: "valeri",
    summary: "Na provjeri: potisnuti obrazac se značajno pogoršao.",
    payload: { learned_rule_id: 2, review: true },
    reversible: true,
    reverted_decision_id: null,
    created_at: "2026-06-03T02:00:00Z",
  },
  {
    id: 23,
    kind: "undo",
    actor: "user",
    summary: "Poništeno pravilo: testno pravilo.",
    payload: { learned_rule_id: 3 },
    reversible: false,
    reverted_decision_id: 21,
    created_at: "2026-06-03T09:00:00Z",
  },
]

const undoResponse: ApplyResponse = {
  learned_rule: { ...activeRule, status: "reverted" },
  decision: decisions[2],
  register: "akcija",
}

const keepResponse: ApplyResponse = {
  learned_rule: { ...flaggedRule, na_provjeri: false },
  decision: {
    id: 24,
    kind: "approval",
    actor: "user",
    summary: "Pravilo zadržano nakon provjere.",
    payload: { learned_rule_id: 2 },
    reversible: true,
    reverted_decision_id: null,
    created_at: "2026-06-03T10:00:00Z",
  },
  register: "akcija",
}

// ── helpers ───────────────────────────────────────────────────────────────────

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <LearnedTab />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

/** Route fetch calls by URL substring, first match wins (insertion order). */
function mockApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      for (const [route, body] of Object.entries(routes)) {
        if (path.includes(route)) {
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

/** The default routes (specific paths first — substring matching). */
function defaultRoutes(): Record<string, unknown> {
  return {
    "/api/learned-rules/1/undo": undoResponse,
    "/api/learned-rules/2/keep": keepResponse,
    "/api/learned-rules/1": detailResponse,
    "/api/learned-rules": { items: [activeRule, flaggedRule, revertedRule] },
    "/api/audit/decisions": { items: decisions },
  }
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── tests ─────────────────────────────────────────────────────────────────────

describe("LearnedTab (M11) — rules list", () => {
  it("renders every rule with origin, effect count, status and the Na provjeri flag", async () => {
    mockApi(defaultRoutes())
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("learned-rule-card")).toHaveLength(3))
    const cards = screen.getAllByTestId("learned-rule-card")

    // Origin: source customer + creator (rehydrated names) on the first card.
    expect(cards[0]).toHaveTextContent("Iz odbačenog signala")
    expect(cards[0]).toHaveTextContent("Hotel Stari Grad — Objekat 1")
    expect(cards[0]).toHaveTextContent("kreirao Vlasnik")

    // Effect: the SQL hit count + the predicted estimate + the SQL footer.
    expect(cards[0]).toHaveTextContent("Sakriveno signala: 3")
    expect(cards[0]).toHaveTextContent("Predviđeno: 1")
    expect(cards[0]).toHaveTextContent("brojke iz baze · SQL")

    // Status badges per rule.
    expect(cards[0]).toHaveTextContent("Aktivno")
    expect(cards[0]).toHaveTextContent("Automatski primijenjeno")
    expect(cards[2]).toHaveTextContent("Poništeno")

    // The Na provjeri flag appears ONLY on the flagged rule.
    expect(cards[1].querySelector('[data-testid="na-provjeri-flag"]')).not.toBeNull()
    expect(cards[0].querySelector('[data-testid="na-provjeri-flag"]')).toBeNull()
    expect(cards[1]).toHaveTextContent("Na provjeri")
  })

  it("shows the honest empty state when no rules exist", async () => {
    mockApi({
      "/api/learned-rules": { items: [] },
      "/api/audit/decisions": { items: [] },
    })
    renderTab()

    await waitFor(() =>
      expect(screen.getByText(/VALERI još nije naučio nijedno pravilo/)).toBeInTheDocument(),
    )
  })

  it("'Šta je sakriveno' loads and shows the suppressed signals' evidence", async () => {
    const user = userEvent.setup()
    mockApi(defaultRoutes())
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("learned-rule-card")).toHaveLength(3))
    const toggles = screen.getAllByTestId("show-hidden-toggle")
    await user.click(toggles[0])

    await waitFor(() => expect(screen.getByTestId("hidden-signals")).toBeInTheDocument())
    const hidden = screen.getByTestId("hidden-signals")
    // The suppressed signal's customer, confidence and evidence are one tap away.
    expect(hidden).toHaveTextContent("Hotel Stari Grad — Objekat 1")
    expect(hidden).toHaveTextContent("pouzdanost: visoka")
    // Each hit carries its EvidenceExpander ("Prikaži brojke" → the SQL evidence).
    expect(hidden).toHaveTextContent("Prikaži brojke")
  })
})

describe("LearnedTab (M11) — actions", () => {
  it("Undo calls POST /learned-rules/{id}/undo", async () => {
    const user = userEvent.setup()
    mockApi(defaultRoutes())
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("learned-rule-card")).toHaveLength(3))
    // Active rules expose Undo; the reverted rule does not.
    const undoButtons = screen.getAllByTestId("undo-rule-button")
    expect(undoButtons).toHaveLength(2)

    await user.click(undoButtons[0])

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const undoCall = fetchMock.mock.calls.find(([url]) =>
        String(url).includes("/api/learned-rules/1/undo"),
      )
      expect(undoCall).toBeDefined()
    })
  })

  it("Zadrži appears only on flagged rules and calls POST /learned-rules/{id}/keep", async () => {
    const user = userEvent.setup()
    mockApi(defaultRoutes())
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("learned-rule-card")).toHaveLength(3))
    // Only the flagged rule offers Zadrži.
    const keepButtons = screen.getAllByTestId("keep-rule-button")
    expect(keepButtons).toHaveLength(1)

    await user.click(keepButtons[0])

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const keepCall = fetchMock.mock.calls.find(([url]) =>
        String(url).includes("/api/learned-rules/2/keep"),
      )
      expect(keepCall).toBeDefined()
    })
  })
})

describe("LearnedTab (M11) — decision feed", () => {
  it("renders every decision with kind, actor, summary and reversibility", async () => {
    mockApi(defaultRoutes())
    renderTab()

    await waitFor(() => expect(screen.getAllByTestId("decision-row")).toHaveLength(3))
    const feed = screen.getByTestId("decision-feed")

    // Kinds are localized labels, never raw enum values.
    expect(feed).toHaveTextContent("Potiskivanje")
    expect(feed).toHaveTextContent("Reaktivacija")
    expect(feed).toHaveTextContent("Poništenje")

    // Actors: the system vs the human are always distinguishable.
    expect(feed).toHaveTextContent("VALERI")
    expect(feed).toHaveTextContent("Korisnik")

    // Summaries (Bosnian) + reversibility marker.
    expect(feed).toHaveTextContent("Na provjeri: potisnuti obrazac se značajno pogoršao.")
    expect(feed).toHaveTextContent("reverzibilno")
  })

  it("shows the empty state when there are no decisions", async () => {
    mockApi({
      "/api/learned-rules": { items: [] },
      "/api/audit/decisions": { items: [] },
    })
    renderTab()

    await waitFor(() =>
      expect(screen.getByText("Još nema zabilježenih odluka.")).toBeInTheDocument(),
    )
  })
})
