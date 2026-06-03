/**
 * ComboChart (ui-design §5): revenue bars + dashed prior-year line, dual legend.
 */
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { useT } from "@/lib/i18n"
import { formatMonth, formatMoney } from "@/lib/format"

export function ComboChart({
  months,
  revenue,
  secondary,
}: {
  months: string[]
  revenue: string[]
  secondary: string[]
}) {
  const t = useT()
  const data = months.map((month, index) => ({
    month: formatMonth(month),
    revenue: Number.parseFloat(revenue[index]) || 0,
    prior: Number.parseFloat(secondary[index]) || 0,
  }))

  return (
    <div className="h-72 w-full" data-testid="combo-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="month"
            tick={{ fill: "var(--text-3)", fontSize: 11 }}
            axisLine={{ stroke: "var(--border)" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "var(--text-3)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={70}
            tickFormatter={(value: number) => formatMoney(value)}
          />
          <Tooltip
            formatter={(value) => formatMoney(value as number)}
            contentStyle={{
              backgroundColor: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              color: "var(--text)",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--text-2)" }} />
          <Bar
            dataKey="revenue"
            name={t.dashboard.revenue_chart.legend_revenue}
            fill="#bcd4fb"
            radius={[3, 3, 0, 0]}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="prior"
            name={t.dashboard.revenue_chart.legend_prior}
            stroke="var(--down)"
            strokeDasharray="5 4"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
