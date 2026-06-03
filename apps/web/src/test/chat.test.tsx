/** M9 (web): ChatMessage renders the full envelope; the task-draft card is visible. */
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { ChatMessage } from "@/features/chat/ChatMessage"
import { I18nProvider } from "@/lib/i18n"
import { useLanguageStore } from "@/store/ui"

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
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
})
