/** M8 test 16: bs is the default; the EN toggle swaps the catalog (frontend-spec §8). */
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { I18nProvider, useT } from "@/lib/i18n"
import { bs } from "@/lib/i18n/bs"
import { en } from "@/lib/i18n/en"
import { useLanguageStore } from "@/store/ui"

function NavLabel() {
  const t = useT()
  return <span>{t.nav.pocetna}</span>
}

describe("i18n", () => {
  beforeEach(() => {
    useLanguageStore.setState({ language: "bs" })
  })

  it("defaults to Bosnian", () => {
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    )
    expect(screen.getByText("Početna")).toBeInTheDocument()
  })

  it("switches to English via the language store (EN toggle)", () => {
    useLanguageStore.setState({ language: "en" })
    render(
      <I18nProvider>
        <NavLabel />
      </I18nProvider>,
    )
    expect(screen.getByText("Home")).toBeInTheDocument()
  })

  it("keeps both catalogs structurally identical (no missing keys)", () => {
    function keysOf(value: object, prefix = ""): string[] {
      return Object.entries(value).flatMap(([key, item]) =>
        typeof item === "object" && item !== null
          ? keysOf(item, `${prefix}${key}.`)
          : [`${prefix}${key}`],
      )
    }
    expect(keysOf(en).sort()).toEqual(keysOf(bs).sort())
  })

  it("uses correct Bosnian diacritics in the catalog", () => {
    expect(bs.dashboard.insights.title).toContain("uvidi")
    expect(bs.tasks.status.done).toBe("Završen")
    expect(bs.ai_report.tab_learned).toBe("Šta je VALERI naučio")
  })
})
