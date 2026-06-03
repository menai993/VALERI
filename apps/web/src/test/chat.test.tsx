/** M9 (web): ChatMessage renders the full envelope; the task-draft card is visible.
 * M10: the inline rule-proposal card (register + description + one-tap confirm). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { ChatMessage } from "@/features/chat/ChatMessage"
import { I18nProvider } from "@/lib/i18n"
import { useLanguageStore } from "@/store/ui"

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

/** The M10 rule-proposal card mounts a mutation hook → needs a QueryClientProvider. */
function withProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>{ui}</I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

describe("ChatMessage", () => {
  it("renders an assistant reply with register chip + tool provenance", () => {
    withI18n(
      <ChatMessage
        role="assistant"
        content="Ukupan promet u zadnjih 30 dana iznosi 39751.20 KM."
        register="analiza"
        toolCalls={[
          {
            tool: "query_metric",
            params: { metric: "turnover" },
            ok: true,
            error_code: null,
            narration_source: "llm",
          },
        ]}
      />,
    )

    // The register chip (principle 9) and the narrative.
    expect(screen.getByText("Analiza")).toBeInTheDocument()
    expect(
      screen.getByText("Ukupan promet u zadnjih 30 dana iznosi 39751.20 KM."),
    ).toBeInTheDocument()

    // Tool provenance: which tool ran + the SQL footer (principle 1, visible).
    const provenance = screen.getByTestId("tool-calls")
    expect(provenance).toHaveTextContent("query_metric")
    expect(provenance).toHaveTextContent("brojke iz baze · SQL")
  })

  it("renders a user message without AI chrome", () => {
    withI18n(<ChatMessage role="user" content="Koliki je promet?" />)
    expect(screen.getByText("Koliki je promet?")).toBeInTheDocument()
    expect(screen.queryByText("Analiza")).not.toBeInTheDocument()
    expect(screen.queryByTestId("tool-calls")).not.toBeInTheDocument()
  })

  it("renders the inline task-draft card with akcija register + status", () => {
    withI18n(
      <ChatMessage
        role="assistant"
        content="Zadatak je kreiran i dodijeljen komercijalisti."
        register="akcija"
        card={{
          card_type: "task_draft",
          payload: { task_id: 42, title: "Nazvati kupca", status: "open" },
        }}
      />,
    )

    const card = screen.getByTestId("task-draft-card")
    expect(card).toHaveTextContent("Nazvati kupca")
    expect(card).toHaveTextContent("open")
    // Both the message register and the card's akcija chip are present.
    expect(screen.getAllByText("Akcija").length).toBeGreaterThanOrEqual(1)
  })

  it("shows the thinking state while streaming", () => {
    withI18n(<ChatMessage role="assistant" content="" pending register={null} />)
    expect(screen.getByText("VALERI analizira…")).toBeInTheDocument()
  })

  it("renders the inline rule-proposal card (M10): pending → preporuka + Primijeni", () => {
    withProviders(
      <ChatMessage
        role="assistant"
        content="Predloženo pravilo: Ne prijavljuj pad prometa za kafiće. Potrebna je vaša potvrda."
        register="preporuka"
        card={{
          card_type: "rule_proposal",
          payload: {
            applied: false,
            requires_confirm: true,
            learned_rule_id: 5,
            description: "Ne prijavljuj pad prometa za kafiće — sezonska djelatnost.",
            effect_estimate: { window_days: 90, total_signals: 7, by_rule: {} },
            interpretation_confidence: 0.85,
            register: "preporuka",
            decision_id: null,
          },
        }}
      />,
    )

    const card = screen.getByTestId("rule-proposal-card")
    expect(card).toHaveTextContent("Ne prijavljuj pad prometa za kafiće")
    expect(card).toHaveTextContent("Čeka potvrdu")
    // The SQL blast radius is shown verbatim with provenance.
    expect(card).toHaveTextContent("7")
    expect(card).toHaveTextContent("90")
    expect(card).toHaveTextContent("brojke iz baze · SQL")
    // The one-tap confirm is offered (nothing applied silently).
    expect(screen.getByTestId("chat-apply-rule")).toBeEnabled()
  })

  it("renders the inline rule-proposal card (M10): auto-applied → akcija, no confirm button", () => {
    withProviders(
      <ChatMessage
        role="assistant"
        content="Pravilo je primijenjeno (reverzibilno)."
        register="akcija"
        card={{
          card_type: "rule_proposal",
          payload: {
            applied: true,
            requires_confirm: false,
            learned_rule_id: 6,
            description: "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac.",
            effect_estimate: { window_days: 90, total_signals: 1, by_rule: {} },
            interpretation_confidence: 0.9,
            register: "akcija",
            decision_id: 11,
          },
        }}
      />,
    )

    const card = screen.getByTestId("rule-proposal-card")
    expect(card).toHaveTextContent("Primijenjeno (reverzibilno)")
    expect(card).toHaveTextContent("poništiti")
    expect(screen.queryByTestId("chat-apply-rule")).not.toBeInTheDocument()
  })
})
