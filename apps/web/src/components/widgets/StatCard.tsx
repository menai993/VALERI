/**
 * StatCard (ui-design §5): one KPI card — label + icon chip, big tabular value,
 * delta vs prior period, sparkline or progress footer.
 */
import type { LucideIcon } from "lucide-react"

import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { useT } from "@/lib/i18n"
import { deltaDirection, formatDelta } from "@/lib/format"
import { cn } from "@/lib/utils"

import { Sparkline } from "./Sparkline"

export interface StatCardProps {
  label: string
  value: string
  delta?: string | null
  deltaUnit?: string | null
  spark?: string[]
  progress?: { done: number; total: number } | null
  icon?: LucideIcon
}

export function StatCard({ label, value, delta, deltaUnit, spark, progress, icon: Icon }: StatCardProps) {
  const t = useT()
  const direction = deltaDirection(delta)

  return (
    <Card className="flex flex-col gap-3 p-5" data-testid="stat-card">
      <div className="flex items-center justify-between">
        <span className="text-sm text-text-2">{label}</span>
        {Icon && (
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-soft">
            <Icon className="h-4 w-4 text-primary" />
          </span>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <span className="tnum text-3xl font-bold leading-none text-text">{value}</span>
        {delta !== null && delta !== undefined && (
          <span
            data-testid="stat-delta"
            className={cn(
              "tnum text-sm font-medium",
              direction === "up" && "text-up",
              direction === "down" && "text-down",
              direction === "neutral" && "text-text-3",
            )}
          >
            {formatDelta(delta, deltaUnit ?? "%")}
          </span>
        )}
      </div>
      {delta !== null && delta !== undefined && (
        <span className="-mt-2 text-[11.5px] text-text-3">{t.dashboard.kpi.vs_prior}</span>
      )}

      {spark && spark.length > 0 && <Sparkline data={spark} type="bar" />}

      {progress && progress.total > 0 && (
        <div className="flex flex-col gap-1">
          <Progress value={(progress.done / progress.total) * 100} />
          <span className="tnum text-[11.5px] text-text-3">
            {progress.done} / {progress.total} {t.dashboard.kpi.done_of}
          </span>
        </div>
      )}
    </Card>
  )
}
