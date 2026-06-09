/** CI2: RelationshipMap renders the ego graph (nodes) + an evidence legend
 * (each edge labeled with its type, confidence and source). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RelationshipMap } from "@/components/widgets/RelationshipMap"
import { I18nProvider } from "@/lib/i18n"
import type { KbGraph } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const graph: KbGraph = {
  nodes: [
    { customer_id: 7, name: "Hotel Hills", segment: "hotel", risk_band: null },
    { customer_id: 9, name: "Hotel Europe", segment: "hotel", risk_band: "visoka" },
  ],
  edges: [
    {
      from: 7,
      to: 9,
      rel_type: "same_owner",
      source: "stated",
      confidence: "0.800",
      evidence_message_id: 11,
    },
  ],
}

function renderMap(data: KbGraph) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(data), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ),
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <RelationshipMap customerId={7} />
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

describe("RelationshipMap", () => {
  it("renders nodes and a labeled edge with source + confidence", async () => {
    renderMap(graph)
    await waitFor(() => expect(screen.getByTestId("relationship-map")).toBeInTheDocument())
    // Nodes appear (SVG labels).
    expect(screen.getAllByText("Hotel Hills").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Hotel Europe").length).toBeGreaterThan(0)
    // The edge legend carries the rel type (translated), confidence and source.
    const edge = screen.getByTestId("graph-edge")
    expect(edge).toHaveTextContent("isti vlasnik")
    expect(edge).toHaveTextContent("0.800")
    expect(edge).toHaveTextContent("izjavljeno")
  })

  it("renders nothing when there are no confirmed edges", async () => {
    renderMap({ nodes: [{ customer_id: 7, name: "Hotel Hills", segment: "hotel", risk_band: null }], edges: [] })
    // No edges → the map stays hidden (no empty card noise).
    await waitFor(() =>
      expect(screen.queryByTestId("relationship-map")).not.toBeInTheDocument(),
    )
  })
})
