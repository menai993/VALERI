/**
 * Uvoz podataka (data-ingest-ui): admin uploads the 4 ERP export files
 * (kupci/artikli/fakture/stavke) → POST /api/ingest/import → the SQL data-quality
 * report. Templates make the format obvious; a one-click recompute+scan refreshes
 * derived data; the history lists past imports. Admin only.
 */
import { useState } from "react"
import { Download, RefreshCw, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState } from "@/components/widgets/CardState"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { QualityReportView } from "@/components/widgets/QualityReport"
import {
  useImportMutation,
  useImportReport,
  useImportRuns,
  useMe,
  useRecomputeMutation,
  useRunScanMutation,
} from "@/lib/api/queries"
import type { IngestFileKey, ImportRunSummary } from "@/lib/api/types"
import { downloadTemplate } from "@/lib/ingest/templates"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

const FILE_KEYS: IngestFileKey[] = ["kupci", "artikli", "fakture", "stavke"]

export function IngestPage() {
  const t = useT()
  const { data: user } = useMe()
  const isAdmin = user?.role === "admin"

  const [files, setFiles] = useState<Partial<Record<IngestFileKey, File>>>({})
  const [importId, setImportId] = useState<number | null>(null)

  const importMutation = useImportMutation()
  const report = useImportReport(importId)
  const runs = useImportRuns()
  const recompute = useRecomputeMutation()
  const runScan = useRunScanMutation()

  if (user && !isAdmin) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-[26px] font-semibold text-text">{t.ingest.title}</h1>
        <Card className="p-5">
          <EmptyState message={t.app.forbidden} />
        </Card>
      </div>
    )
  }

  const allSelected = FILE_KEYS.every((key) => files[key])

  const startImport = () => {
    if (!allSelected) return
    const payload = Object.fromEntries(FILE_KEYS.map((k) => [k, files[k]])) as Record<
      IngestFileKey,
      File
    >
    importMutation.mutate(payload, { onSuccess: (result) => setImportId(result.import_id) })
  }

  const refreshDerived = () => {
    recompute.mutate(undefined, { onSuccess: () => runScan.mutate() })
  }
  const refreshing = recompute.isPending || runScan.isPending
  const refreshed = recompute.isSuccess && runScan.isSuccess && !refreshing

  const runColumns: Column<ImportRunSummary>[] = [
    { key: "import_id", header: "#", render: (r) => <span className="tnum">{r.import_id}</span> },
    { key: "source", header: t.ingest.col_source, render: (r) => <span className="text-text-2">{r.source}</span> },
    {
      key: "status",
      header: t.ingest.col_status,
      render: (r) => <span className="text-text-2">{t.ingest.status[r.status] ?? r.status}</span>,
    },
    {
      key: "started_at",
      header: t.ingest.col_when,
      align: "right",
      render: (r) => <span className="text-text-2">{formatDate(r.started_at)}</span>,
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">{t.ingest.title}</h1>
        <p className="text-sm text-text-2">{t.ingest.subtitle}</p>
      </div>

      {/* Upload card */}
      <Card className="flex flex-col gap-4 p-5">
        <p className="text-sm text-text-2">{t.ingest.format_hint}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {FILE_KEYS.map((key) => (
            <div key={key} className="flex flex-col gap-1.5 rounded-md border p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-text">{t.ingest.entities[key]}</span>
                <button
                  type="button"
                  onClick={() => downloadTemplate(key)}
                  className="flex items-center gap-1 text-xs text-primary hover:underline"
                  data-testid={`template-${key}`}
                >
                  <Download className="h-3.5 w-3.5" />
                  {t.ingest.template}
                </button>
              </div>
              <input
                type="file"
                accept=".csv,.xlsx"
                data-testid={`file-${key}`}
                onChange={(e) =>
                  setFiles((prev) => ({ ...prev, [key]: e.target.files?.[0] ?? undefined }))
                }
                className="text-xs text-text-2 file:mr-2 file:rounded-sm file:border file:bg-surface-2 file:px-2 file:py-1 file:text-xs"
              />
            </div>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            disabled={!allSelected || importMutation.isPending}
            onClick={startImport}
            data-testid="import-submit"
          >
            <Upload className={`h-4 w-4 ${importMutation.isPending ? "animate-pulse" : ""}`} />
            {t.ingest.import_button}
          </Button>
          {importMutation.isError && (
            <span className="text-sm text-down" data-testid="import-error">
              {importMutation.error instanceof Error
                ? importMutation.error.message
                : t.app.error}
            </span>
          )}
        </div>
      </Card>

      {/* Report + post-import refresh */}
      {importId !== null && (
        <>
          {report.isLoading && <CardSkeleton rows={6} />}
          {report.data && <QualityReportView report={report.data} />}
          <Card className="flex flex-wrap items-center gap-3 p-5">
            <Button disabled={refreshing} onClick={refreshDerived} data-testid="post-import-refresh">
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              {t.ingest.refresh_button}
            </Button>
            <span className="text-sm text-text-2">{t.ingest.refresh_hint}</span>
            {refreshed && (
              <span className="text-sm text-up" data-testid="refresh-done">
                {t.ingest.refresh_done}
              </span>
            )}
          </Card>
        </>
      )}

      {/* History */}
      <Card className="flex flex-col gap-3 p-5">
        <h2 className="text-[17px] font-semibold text-text">{t.ingest.history_title}</h2>
        {runs.isLoading && <CardSkeleton rows={4} />}
        {runs.data && runs.data.items.length === 0 && <EmptyState />}
        {runs.data && runs.data.items.length > 0 && (
          <DataTable columns={runColumns} rows={runs.data.items} rowKey={(r) => r.import_id} />
        )}
      </Card>
    </div>
  )
}
