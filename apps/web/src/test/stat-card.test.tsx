/** M8 test 13: StatCard renders value/delta/progress; delta color follows sign. */
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { StatCard } from "@/components/widgets/StatCard"
import { I18nProvider } from "@/lib/i18n"
import { useLanguageStore } from "@/store/ui"

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

describe("StatCard", () => {
  it("renders the label and the SQL value verbatim", () => {
    withI18n(<StatCard label="Ukupan prihod" value="142.300 KM" />)
    expect(screen.getByText("Ukupan prihod")).toBeInTheDocument()
    expect(screen.getByText("142.300 KM")).toBeInTheDocument()
  })

  it("colors a negative delta with the down token", () => {
    withI18n(<StatCard label="Prihod" value="100 KM" delta="-12.5" />)
    const delta = screen.getByTestId("stat-delta")
    expect(delta).toHaveTextContent("↓12.5%")
    expect(delta.className).toContain("text-down")
  })

  it("colors a positive delta with the up token", () => {
    withI18n(<StatCard label="Prihod" value="100 KM" delta="8" />)
    const delta = screen.getByTestId("stat-delta")
    expect(delta).toHaveTextContent("↑8%")
    expect(delta.className).toContain("text-up")
  })

  it("renders task progress as 'done / total'", () => {
    withI18n(
      <StatCard label="Zadaci danas" value="5" progress={{ done: 3, total: 17 }} />,
    )
    expect(screen.getByText(/3 \/ 17/)).toBeInTheDocument()
  })
})
