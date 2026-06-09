/** CI1: KnowledgePanel ("Šta VALERI zna") renders profile + facts (source +
 * confidence chips) + an events timeline + relationships. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { KnowledgePanel } from "@/components/widgets/KnowledgePanel"
import { I18nProvider } from "@/lib/i18n"
import type { KbKnowledge } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const knowledge: KbKnowledge = {
  profile: {
    customer_id: 7,
    summary: "Kupac uredno posluje i širi nabavku na hemiju.",
    decision_maker: null,
    preferences: null,
    updated_at: "2026-06-03T10:00:00Z",
  },
  facts: [
    {
      item_type: "fact",
      id: 1,
      customer_id: 7,
      customer_name: "Hotel Hills",
      mentioned_name: null,
      title: "intent · category_expansion",
      detail: { category: "hemija" },
      register: "analiza",
      source: "stated",
      confidence: "0.850",
      conf_band: "visoka",
      status: "active",
      evidence_text: "kreću i s hemijom od idućeg mjeseca",
      source_message_id: 11,
      created_at: "2026-06-03T10:00:00Z",
    },
  ],
  events: [
    {
      item_type: "event",
      id: 2,
      customer_id: 7,
      customer_name: "Hotel Hills",
      mentioned_name: null,
      title: "deal · Godišnji ugovor",
      detail: { kind: "deal", value: "72000.00" },
      register: "analiza",
      source: "stated",
      confidence: "0.900",
      conf_band: "visoka",
      status: "active",
      evidence_text: "Zaključio sam godišnji ugovor",
      source_message_id: 11,
      created_at: "2026-05-30T10:00:00Z",
    },
  ],
  relationships: [
    {
      item_type: "relationship",
      id: 3,
      from_customer_id: 7,
      from_name: "Hotel Hills",
      to_customer_id: 9,
      to_name: "Hotel Europe",
      rel_type: "same_owner",
      register: "preporuka",
      source: "stated",
      confidence: "0.800",
      conf_band: "visoka",
      status: "active",
      evidence_text: "isti vlasnik",
      created_at: "2026-05-30T10:00:00Z",
    },
  ],
}

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <KnowledgePanel customerId={7} />
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

describe("KnowledgePanel", () => {
  it("renders profile summary, facts with source+confidence, events and relationships", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(knowledge), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    )

    renderPanel()

    await waitFor(() =>
      expect(screen.getByTestId("kb-profile-summary")).toBeInTheDocument(),
    )
    // Profile summary.
    expect(screen.getByText(/širi nabavku na hemiju/)).toBeInTheDocument()
    // Fact with source + confidence chips and its evidence.
    expect(screen.getByText("intent · category_expansion")).toBeInTheDocument()
    expect(screen.getByText("izjavljeno")).toBeInTheDocument()
    expect(screen.getAllByText("pouzdanost: visoka").length).toBeGreaterThan(0)
    expect(screen.getByText(/kreću i s hemijom/)).toBeInTheDocument()
    // Event timeline + relationship.
    expect(screen.getByText("deal · Godišnji ugovor")).toBeInTheDocument()
    expect(screen.getByTestId("kb-relationship")).toHaveTextContent("isti vlasnik")
  })

  it("shows the empty state when there is no knowledge", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({ profile: null, facts: [], events: [], relationships: [] }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        ),
      ),
    )
    renderPanel()
    await waitFor(() =>
      expect(screen.getByText(/još nema zabilježeno znanje/)).toBeInTheDocument(),
    )
  })
})
