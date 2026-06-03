/** M8 test 11: the trust-critical widgets — register, confidence, risk, evidence.
 *
 * Every AI surface must show register + confidence + evidence (principles 2/3/9);
 * chips always carry text, never color alone (ui-design §8).
 */
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it } from "vitest"

import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { RiskBadge } from "@/components/widgets/RiskBadge"
import { I18nProvider } from "@/lib/i18n"
import { useLanguageStore } from "@/store/ui"

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

describe("RegisterChip", () => {
  it("renders text for every register value (never color alone)", () => {
    withI18n(
      <>
        <RegisterChip register="analiza" />
        <RegisterChip register="preporuka" />
        <RegisterChip register="akcija" />
      </>,
    )
    expect(screen.getByText("Analiza")).toBeInTheDocument()
    expect(screen.getByText("Preporuka")).toBeInTheDocument()
    expect(screen.getByText("Akcija")).toBeInTheDocument()
  })
})

describe("ConfidenceLabel", () => {
  it("renders 'pouzdanost: <band>' for each band", () => {
    withI18n(
      <>
        <ConfidenceLabel band="visoka" />
        <ConfidenceLabel band="niska" />
      </>,
    )
    expect(screen.getByText("pouzdanost: visoka")).toBeInTheDocument()
    expect(screen.getByText("pouzdanost: niska")).toBeInTheDocument()
  })
})

describe("RiskBadge", () => {
  it("renders the Bosnian risk band text", () => {
    withI18n(
      <>
        <RiskBadge band="visok" />
        <RiskBadge band="srednji" />
        <RiskBadge band="nizak" />
      </>,
    )
    expect(screen.getByText("Visok")).toBeInTheDocument()
    expect(screen.getByText("Srednji")).toBeInTheDocument()
    expect(screen.getByText("Nizak")).toBeInTheDocument()
  })
})

describe("EvidenceExpander", () => {
  const evidence = {
    metric: "turnover_60d",
    value: "1234.56",
    baseline: "4000.00",
    delta_pct: "-69.1",
  }

  it("hides the numbers until 'Prikaži brojke' is clicked, then shows them + the SQL footer", async () => {
    const user = userEvent.setup()
    withI18n(<EvidenceExpander evidence={evidence} />)

    // Hidden initially.
    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument()

    // Click to reveal.
    await user.click(screen.getByText("Prikaži brojke"))
    expect(screen.getByTestId("evidence-panel")).toBeInTheDocument()

    // Every SQL value renders verbatim (the API's exact strings).
    expect(screen.getByText("1234.56")).toBeInTheDocument()
    expect(screen.getByText("4000.00")).toBeInTheDocument()
    expect(screen.getByText("-69.1")).toBeInTheDocument()

    // The provenance footer (principle 1 visible to the user).
    expect(screen.getByText("brojke iz baze · SQL")).toBeInTheDocument()

    // Toggles back off.
    await user.click(screen.getByText("Sakrij brojke"))
    expect(screen.queryByTestId("evidence-panel")).not.toBeInTheDocument()
  })
})
