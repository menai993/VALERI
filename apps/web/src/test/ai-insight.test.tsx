/** M8 test 12: AIInsightItem shows the full envelope; dismiss opens the RuleCard
 * preview (apply disabled until M10, D3). */
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { AIInsightItem } from "@/components/widgets/AIInsightItem"
import { RuleCard } from "@/components/widgets/RuleCard"
import { I18nProvider } from "@/lib/i18n"
import type { InsightRow } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

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

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

describe("AIInsightItem", () => {
  it("shows register chip + customer + confidence + evidence expander", () => {
    withI18n(<AIInsightItem insight={insight} onDismiss={() => {}} />)

    expect(screen.getByText("Analiza")).toBeInTheDocument()
    expect(screen.getByText("Pad prometa")).toBeInTheDocument()
    expect(screen.getByText("Hotel Stari Grad — Objekat 1")).toBeInTheDocument()
    expect(screen.getByText("pouzdanost: visoka")).toBeInTheDocument()
    expect(screen.getByText("Prikaži brojke")).toBeInTheDocument()
  })

  it("calls onDismiss with the insight when 'Zanemari' is clicked", async () => {
    const user = userEvent.setup()
    const onDismiss = vi.fn()
    withI18n(<AIInsightItem insight={insight} onDismiss={onDismiss} />)

    await user.click(screen.getByTestId("dismiss-insight"))
    expect(onDismiss).toHaveBeenCalledWith(insight)
  })
})

describe("RuleCard (M8 preview, D3)", () => {
  it("opens with the insight scope and a DISABLED apply button + M10 note", () => {
    withI18n(<RuleCard insight={insight} open onClose={() => {}} />)

    expect(screen.getByTestId("rule-card")).toBeInTheDocument()
    expect(screen.getByText("Zanemari ovaj uvid")).toBeInTheDocument()

    // Scope chips: rule + customer.
    expect(screen.getByText("Pad prometa")).toBeInTheDocument()
    expect(screen.getByText("Hotel Stari Grad — Objekat 1")).toBeInTheDocument()

    // The apply call lands in M10 — the button must be disabled with the note.
    expect(screen.getByTestId("apply-rule-button")).toBeDisabled()
    expect(screen.getByTestId("m10-note")).toBeInTheDocument()
  })

  it("renders nothing when no insight is selected", () => {
    withI18n(<RuleCard insight={null} open onClose={() => {}} />)
    expect(screen.queryByTestId("rule-card")).not.toBeInTheDocument()
  })
})
