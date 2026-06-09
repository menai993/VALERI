/** CI1: the review queue (Zabilješke) renders proposed records + a clarification
 * with tappable options; confirming a fact posts to the confirm endpoint. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReviewQueuePage } from "@/features/kb/ReviewQueuePage"
import { I18nProvider } from "@/lib/i18n"
import type { KbPendingQueue } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const queue: KbPendingQueue = {
  facts: [
    {
      item_type: "fact",
      id: 5,
      customer_id: null,
      customer_name: null,
      mentioned_name: "Fupupu",
      title: "payment_late · status",
      detail: { status: "late" },
      register: "analiza",
      source: "stated",
      confidence: "0.860",
      conf_band: "visoka",
      status: "proposed",
      evidence_text: "kupac Fupupu kasni s plaćanjem",
      source_message_id: 12,
      created_at: "2026-06-03T10:00:00Z",
    },
  ],
  events: [],
  relationships: [],
  clarifications: [
    {
      id: 8,
      kind: "entity",
      question: "Da li „Fupupu“ znači kupca Fupy (kafić), ili je to novi kupac?",
      options: [
        { label: "Da, Fupy", action: "link", customer_id: 142 },
        { label: "Nije — drugi kupac", action: "pick_other" },
        { label: "Novi kupac „Fupupu“", action: "create_prospect" },
      ],
      target_record_ref: "client_fact:5",
      status: "pending",
      created_at: "2026-06-03T10:00:00Z",
    },
  ],
}

function renderQueue() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <ReviewQueuePage />
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

describe("ReviewQueuePage", () => {
  it("renders a proposed fact and a clarification with tappable options", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify(queue), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    )

    renderQueue()

    await waitFor(() => expect(screen.getByTestId("clarification-card")).toBeInTheDocument())
    // The clarification question + its tappable options.
    expect(screen.getByText(/Da li „Fupupu“ znači kupca Fupy/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Da, Fupy" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Novi kupac/ })).toBeInTheDocument()
    // The proposed fact with its evidence (the source sentence).
    expect(screen.getByText("payment_late · status")).toBeInTheDocument()
    expect(screen.getByText(/kupac Fupupu kasni s plaćanjem/)).toBeInTheDocument()
  })

  it("posts to the confirm endpoint when a fact is confirmed", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("/confirm")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true, decision_id: 1 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify(queue), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
    })
    vi.stubGlobal("fetch", fetchMock)

    renderQueue()

    await waitFor(() => expect(screen.getByText("payment_late · status")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", { name: "Potvrdi" }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).includes("/api/kb/items/5/confirm?item_type=fact"),
        ),
      ).toBe(true),
    )
  })
})
