/** M8 test 15: formatters render Bosnian money/date/delta formats (ui-design §8). */
import { describe, expect, it } from "vitest"

import {
  deltaDirection,
  formatDate,
  formatDelta,
  formatMoney,
  formatPercent,
} from "@/lib/format"

describe("formatMoney", () => {
  it("formats with thousands separators and KM suffix", () => {
    // bs-BA locale uses '.' as the thousands separator.
    expect(formatMoney("142300")).toMatch(/142\.300\s*KM/)
    expect(formatMoney(1500.75)).toMatch(/1\.501\s*KM/)
  })

  it("handles null/undefined/garbage as em-dash", () => {
    expect(formatMoney(null)).toBe("—")
    expect(formatMoney(undefined)).toBe("—")
    expect(formatMoney("nije broj")).toBe("—")
  })

  it("never invents a number (pass-through formatting only)", () => {
    expect(formatMoney("0")).toMatch(/^0\s*KM$/)
  })
})

describe("formatDate", () => {
  it("formats ISO dates as dd.mm.yyyy.", () => {
    expect(formatDate("2026-06-03")).toBe("03.06.2026.")
  })

  it("handles missing dates", () => {
    expect(formatDate(null)).toBe("—")
    expect(formatDate("")).toBe("—")
  })
})

describe("formatDelta", () => {
  it("renders positive deltas with up arrow", () => {
    expect(formatDelta("18")).toBe("↑18%")
  })

  it("renders negative deltas with down arrow and absolute value", () => {
    expect(formatDelta("-55.3")).toBe("↓55.3%")
  })

  it("supports custom units", () => {
    expect(formatDelta(-3, "pp")).toBe("↓3pp")
  })

  it("classifies direction for color tokens", () => {
    expect(deltaDirection("18")).toBe("up")
    expect(deltaDirection("-2")).toBe("down")
    expect(deltaDirection(null)).toBe("neutral")
  })
})

describe("formatPercent", () => {
  it("renders ratios as percentages", () => {
    expect(formatPercent("0.853")).toBe("85%")
    expect(formatPercent(0.5)).toBe("50%")
  })
})
