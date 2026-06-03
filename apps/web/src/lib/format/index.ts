/**
 * Number/date/delta formatters (ui-design.md §8).
 *
 * The API sends SQL-computed values as exact strings; these helpers only FORMAT
 * them for display — they never compute new business numbers.
 */

/** "142300.50" → "142.300,50 KM" (Bosnian locale, tabular-ready). */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const amount = typeof value === "number" ? value : Number.parseFloat(value)
  if (Number.isNaN(amount)) return "—"
  const formatted = new Intl.NumberFormat("bs-BA", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount)
  return `${formatted} KM`
}

/** "2026-06-03" → "03.06.2026." */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  const day = String(date.getDate()).padStart(2, "0")
  const month = String(date.getMonth() + 1).padStart(2, "0")
  return `${day}.${month}.${date.getFullYear()}.`
}

/** "2026-06" → "jun 2026." (month label for chart axes). */
export function formatMonth(value: string): string {
  const months = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"]
  const [year, month] = value.split("-")
  const index = Number.parseInt(month, 10) - 1
  return months[index] ? `${months[index]} ${year}.` : value
}

/** Delta as "↑18%" / "↓3%" with sign semantics; null → "—". */
export function formatDelta(
  value: string | number | null | undefined,
  unit: string = "%",
): string {
  if (value === null || value === undefined || value === "") return "—"
  const delta = typeof value === "number" ? value : Number.parseFloat(value)
  if (Number.isNaN(delta)) return "—"
  const arrow = delta > 0 ? "↑" : delta < 0 ? "↓" : "·"
  return `${arrow}${Math.abs(delta)}${unit}`
}

/** Is a delta positive/negative/neutral (drives the --up/--down token). */
export function deltaDirection(
  value: string | number | null | undefined,
): "up" | "down" | "neutral" {
  if (value === null || value === undefined || value === "") return "neutral"
  const delta = typeof value === "number" ? value : Number.parseFloat(value)
  if (Number.isNaN(delta) || delta === 0) return "neutral"
  return delta > 0 ? "up" : "down"
}

/** "0.853" → "85%" (confidence and prevalence displays). */
export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const ratio = typeof value === "number" ? value : Number.parseFloat(value)
  if (Number.isNaN(ratio)) return "—"
  return `${Math.round(ratio * 100)}%`
}

/** Plain numeric display with Bosnian thousands separators. */
export function formatNumber(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—"
  const amount = typeof value === "number" ? value : Number.parseFloat(value)
  if (Number.isNaN(amount)) return "—"
  return new Intl.NumberFormat("bs-BA").format(amount)
}
