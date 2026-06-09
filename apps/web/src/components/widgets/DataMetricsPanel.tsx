/**
 * Podaci i metrike (admin-recompute-panel): operational control over the derived
 * metrics. Shows per-table row counts + last computed/scan time, and lets an admin
 * recompute the metrics or run a (signals-only, LLM-free) scan on demand.
 */
import { Database, RefreshCw, Search } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ApiRequestError } from "@/lib/api/client"
import { useMetricsStatus, useRecomputeMutation, useRunScanMutation } from "@/lib/api/queries"
import type { MetricsStatus, TableStat } from "@/lib/api/types"
import { formatDate, formatNumber } from "@/lib/format"
import { useT } from "@/lib/i18n"

const ROW_KEYS: (keyof MetricsStatus)[] = [
  "customer_metrics",
  "cust_article_cadence",
  "segment_basket",
  "client_expectation",
  "signals",
  "tasks",
]

export function DataMetricsPanel() {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useMetricsStatus()
  const recompute = useRecomputeMutation()
  const runScan = useRunScanMutation()

  if (isLoading) return <CardSkeleton rows={6} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }
  if (!data) return null

  const computedAt = data.customer_metrics.computed_at
  const busy = recompute.isPending || runScan.isPending

  return (
    <div className="flex flex-col gap-4" data-testid="data-metrics-panel">
      <Card className="flex flex-col gap-4 p-5">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
            <Database className="h-4 w-4" />
          </span>
          <div className="flex flex-col">
            <h2 className="text-[17px] font-semibold text-text">{t.settings.data.title}</h2>
            <p className="text-sm text-text-2">{t.settings.data.subtitle}</p>
          </div>
        </div>

        <p className="text-xs text-text-3" data-testid="data-metrics-computed-at">
          {computedAt
            ? `${t.settings.data.last_computed}: ${formatDate(computedAt)}`
            : t.settings.data.never_computed}
        </p>

        <div className="flex flex-wrap gap-3">
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => recompute.mutate()}
            data-testid="recompute-button"
          >
            <RefreshCw className={`h-4 w-4 ${recompute.isPending ? "animate-spin" : ""}`} />
            {t.settings.data.recompute}
          </Button>
          <Button
            disabled={busy}
            onClick={() => runScan.mutate()}
            data-testid="scan-button"
          >
            <Search className="h-4 w-4" />
            {t.settings.data.run_scan}
          </Button>
        </div>

        {(recompute.isError || runScan.isError) && (
          <p className="text-sm text-down" data-testid="data-metrics-action-error">
            {t.app.error}
          </p>
        )}
        {recompute.isSuccess && !busy && (
          <p className="text-sm text-up" data-testid="data-metrics-action-ok">
            {t.settings.data.done}
          </p>
        )}
        {runScan.isSuccess && !busy && (
          <p className="text-sm text-up" data-testid="data-metrics-scan-ok">
            {t.settings.data.scan_done.replace("{n}", formatNumber(runScan.data.inserted))}
          </p>
        )}
      </Card>

      <Card className="flex flex-col gap-1 p-5" data-testid="data-metrics-table">
        {ROW_KEYS.map((key) => {
          const stat: TableStat = data[key]
          return (
            <div
              key={key}
              className="flex items-center justify-between gap-3 border-b py-2 last:border-b-0"
            >
              <span className="text-sm text-text">{t.settings.data.tables[key]}</span>
              <span className="tnum text-sm font-medium text-text">{formatNumber(stat.rows)}</span>
            </div>
          )
        })}
      </Card>
    </div>
  )
}
