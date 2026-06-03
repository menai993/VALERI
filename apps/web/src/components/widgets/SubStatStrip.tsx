/**
 * SubStatStrip (ui-design §5): the cells under the combo chart (YTD, avg monthly, …)
 * on a surface-2 strip divided by hairlines.
 */
import { useT } from "@/lib/i18n"
import { formatMoney } from "@/lib/format"

export function SubStatStrip({ stats }: { stats: { key: string; value: string }[] }) {
  const t = useT()
  const labels: Record<string, string> = {
    ytd_prihod: t.dashboard.revenue_chart.ytd_prihod,
    prosjecni_mjesecni: t.dashboard.revenue_chart.prosjecni_mjesecni,
    najbolji_mjesec: t.dashboard.revenue_chart.najbolji_mjesec,
  }

  return (
    <div
      className="grid divide-x divide-border rounded-md bg-surface-2"
      style={{ gridTemplateColumns: `repeat(${stats.length}, 1fr)` }}
      data-testid="substat-strip"
    >
      {stats.map((stat) => (
        <div key={stat.key} className="flex flex-col gap-1 p-3">
          <span className="text-[11.5px] text-text-3">{labels[stat.key] ?? stat.key}</span>
          <span className="tnum text-sm font-semibold text-text">{formatMoney(stat.value)}</span>
        </div>
      ))}
    </div>
  )
}
