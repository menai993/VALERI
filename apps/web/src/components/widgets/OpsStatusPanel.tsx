/**
 * Stanje sistema (P2): the platform's self-report behind the bell's alerts
 * entry — per-job ledger rollups, data freshness, and active alert conditions.
 * Owner/admin only (the endpoint 403s everyone else). All values are SQL facts.
 */
import { AlertTriangle, CheckCircle2 } from "lucide-react"

import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ApiRequestError } from "@/lib/api/client"
import { useOpsStatus } from "@/lib/api/queries"
import type { OpsJobStatus } from "@/lib/api/types"
import { formatDate, formatNumber } from "@/lib/format"
import { useT } from "@/lib/i18n"

export function OpsStatusPanel() {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useOpsStatus()

  if (isLoading) return <CardSkeleton rows={6} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }
  if (!data) return null

  const ops = t.settings.ops
  const jobLabel = (job: string) => ops.jobs[job] ?? job
  const statusLabel = (status: string | null) =>
    status === null ? ops.never : (ops.statuses[status] ?? status)
  const statusColor = (status: string | null) =>
    status === "failed" ? "text-down" : status === "ok" ? "text-up" : "text-text-2"

  return (
    <div className="flex flex-col gap-4" data-testid="ops-status-panel">
      {/* Active alerts — the detail behind the bell's `alerts` count. */}
      <Card className="flex flex-col gap-3 p-5" data-testid="ops-alerts">
        <h2 className="text-[17px] font-semibold text-text">{ops.alerts_title}</h2>
        {data.alerts.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-up">
            <CheckCircle2 className="h-4 w-4" />
            {ops.no_alerts}
          </p>
        ) : (
          data.alerts.map((alert) => (
            <p
              key={alert.kind}
              className="flex items-start gap-2 text-sm text-text"
              data-testid="ops-alert"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-down" />
              {alert.message}
            </p>
          ))
        )}
      </Card>

      {/* Data freshness — the scanner skips (and alerts) when this goes stale. */}
      <Card className="flex flex-wrap items-center justify-between gap-3 p-5" data-testid="ops-freshness">
        <div className="flex flex-col">
          <h2 className="text-[17px] font-semibold text-text">{ops.freshness}</h2>
          <p className="text-sm text-text-2">
            {ops.last_invoice}:{" "}
            {data.data_freshness.last_invoice_date
              ? formatDate(data.data_freshness.last_invoice_date)
              : ops.never}
          </p>
        </div>
        <span
          className={`text-sm font-medium ${data.data_freshness.stale ? "text-down" : "text-up"}`}
        >
          {data.data_freshness.stale ? ops.stale : ops.fresh}
        </span>
      </Card>

      {/* Per-job ledger rollup. */}
      <Card className="flex flex-col gap-1 p-5" data-testid="ops-jobs">
        <div className="grid grid-cols-[1.5fr_1fr_1fr_1fr_auto] gap-3 border-b pb-2 text-xs text-text-3">
          <span>{ops.col_job}</span>
          <span>{ops.col_status}</span>
          <span>{ops.col_last_run}</span>
          <span>{ops.col_last_ok}</span>
          <span className="text-right">{ops.col_failures}</span>
        </div>
        {data.jobs.map((row: OpsJobStatus) => (
          <div
            key={row.job}
            className="grid grid-cols-[1.5fr_1fr_1fr_1fr_auto] items-center gap-3 border-b py-2 text-sm last:border-b-0"
            data-testid="ops-job-row"
          >
            <span className="font-medium text-text">{jobLabel(row.job)}</span>
            <span className={statusColor(row.last_status)}>{statusLabel(row.last_status)}</span>
            <span className="text-text-2">
              {row.last_run_at ? formatDate(row.last_run_at) : ops.never}
            </span>
            <span className="text-text-2">
              {row.last_ok_at ? formatDate(row.last_ok_at) : ops.never}
            </span>
            <span className="tnum text-right text-text">
              {formatNumber(row.consecutive_failures)}
            </span>
          </div>
        ))}
      </Card>
    </div>
  )
}
