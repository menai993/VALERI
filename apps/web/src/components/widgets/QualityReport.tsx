/**
 * QualityReport (data-ingest-ui): renders the 6 SQL data-quality sections from an
 * import. Every number comes from the backend report (no client computation).
 */
import { AlertTriangle, CheckCircle2 } from "lucide-react"

import { Card } from "@/components/ui/card"
import type { ImportReport } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

export function QualityReportView({ report }: { report: ImportReport }) {
  const t = useT()
  const q = report.quality
  const stats = report.stats

  const sections: { key: string; count: number; rows: string[] }[] = q
    ? [
        {
          key: "duplicate_customer_codes",
          count: q.duplicate_customer_codes.length,
          rows: q.duplicate_customer_codes.map((r) => `${r.code}: ${r.names.join(" / ")}`),
        },
        {
          key: "duplicate_article_codes",
          count: q.duplicate_article_codes.length,
          rows: q.duplicate_article_codes.map((r) => `${r.code}: ${r.names.join(" / ")}`),
        },
        {
          key: "renamed_articles",
          count: q.renamed_articles.length,
          rows: q.renamed_articles.map((r) => `${r.code}: ${r.old_name} → ${r.new_name}`),
        },
        {
          key: "code_swap_candidates",
          count: q.code_swap_candidates.length,
          rows: q.code_swap_candidates.map(
            (r) => `${r.old_code} → ${r.new_code} (${r.name})${r.already_mapped ? " ✓" : ""}`,
          ),
        },
        {
          key: "missing_segments",
          count: q.missing_segments.length,
          rows: q.missing_segments.map((r) => `${r.customer_code}: ${r.name}`),
        },
        {
          key: "orphan_lines",
          count: q.orphan_lines.length,
          rows: q.orphan_lines.map((r) => `#${r.row_no} ${r.broj_fakture ?? "—"} (${r.reason})`),
        },
      ]
    : []

  return (
    <Card className="flex flex-col gap-4 p-5" data-testid="quality-report">
      <div className="flex items-center justify-between">
        <h2 className="text-[17px] font-semibold text-text">
          {t.ingest.report_title} #{report.import_id}
        </h2>
        <span className="text-sm text-text-2">{t.ingest.status[report.status] ?? report.status}</span>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(["kupci", "artikli", "fakture", "stavke"] as const).map((entity) => {
            const s = stats[entity]
            return (
              <div key={entity} className="rounded-md bg-surface-2 p-3">
                <p className="text-xs text-text-3">{t.ingest.entities[entity]}</p>
                <p className="tnum text-sm font-medium text-text">
                  +{s.created} / ~{"updated" in s ? s.updated : s.replaced}
                </p>
              </div>
            )
          })}
        </div>
      )}

      <div className="flex flex-col gap-2">
        {sections.map((section) => (
          <div key={section.key} className="rounded-md border p-3" data-testid={`quality-${section.key}`}>
            <div className="flex items-center gap-2">
              {section.count === 0 ? (
                <CheckCircle2 className="h-4 w-4 text-up" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-risk-mid" />
              )}
              <span className="text-sm font-medium text-text">
                {t.ingest.quality[section.key as keyof typeof t.ingest.quality]}
              </span>
              <span className="tnum ml-auto text-sm text-text-2">{section.count}</span>
            </div>
            {section.rows.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1 pl-6 text-xs text-text-2">
                {section.rows.slice(0, 10).map((row, index) => (
                  <li key={index} className="font-mono">
                    {row}
                  </li>
                ))}
                {section.rows.length > 10 && <li>… (+{section.rows.length - 10})</li>}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}
