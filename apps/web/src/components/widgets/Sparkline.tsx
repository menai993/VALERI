/**
 * Sparkline (ui-design §5): Recharts mini line/bar chart inside a StatCard footer.
 */
import { Bar, BarChart, Line, LineChart, ResponsiveContainer } from "recharts"

export function Sparkline({
  data,
  type = "line",
}: {
  data: string[]
  type?: "line" | "bar"
}) {
  const points = data.map((value, index) => ({ index, value: Number.parseFloat(value) || 0 }))
  if (points.length === 0) return null

  return (
    <div className="h-10 w-full" data-testid="sparkline">
      <ResponsiveContainer width="100%" height="100%">
        {type === "bar" ? (
          <BarChart data={points}>
            <Bar dataKey="value" fill="var(--primary)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        ) : (
          <LineChart data={points}>
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--primary)"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
