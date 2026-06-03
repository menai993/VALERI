/** C-CRM2: RepActivityRow renders a rep's name, count, by-kind summary, and the
 * completion bar — every figure passed through from SQL, never computed here. */
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { RepActivityRow } from "@/components/widgets/RepActivityRow"
import { I18nProvider } from "@/lib/i18n"
import type { RepActivityRow as RepActivityRowData } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

function withI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

const rep: RepActivityRowData = {
  sales_rep_id: 1,
  name: "Amela Hodžić",
  total: 5,
  done: 3,
  completion: "0.6000",
  by_kind: { meeting: 2, call: 1, offer: 1, follow_up: 1, analysis: 0 },
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

describe("RepActivityRow", () => {
  it("renders the rep name and the total count chip", () => {
    withI18n(<RepActivityRow rep={rep} />)
    const row = screen.getByTestId("rep-activity-row")
    expect(row).toHaveTextContent("Amela Hodžić")
    expect(row).toHaveTextContent("5")
  })

  it("summarizes only the non-zero kinds (hides analysis at 0)", () => {
    withI18n(<RepActivityRow rep={rep} />)
    const row = screen.getByTestId("rep-activity-row")
    expect(row).toHaveTextContent("2 sastanci")
    expect(row).toHaveTextContent("1 pozivi")
    expect(row).not.toHaveTextContent("analize")
  })

  it("renders completion from the SQL ratio (done/total)", () => {
    withI18n(<RepActivityRow rep={rep} />)
    expect(screen.getByText(/60% završeno/)).toBeInTheDocument()
  })

  it("shows the empty hint when a rep logged nothing", () => {
    withI18n(
      <RepActivityRow
        rep={{
          sales_rep_id: 2,
          name: "Tarik Begić",
          total: 0,
          done: 0,
          completion: "0.0000",
          by_kind: { meeting: 0, call: 0, offer: 0, follow_up: 0, analysis: 0 },
        }}
      />,
    )
    expect(screen.getByText(/0% završeno/)).toBeInTheDocument()
  })
})
