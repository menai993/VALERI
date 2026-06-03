/**
 * InvestigationReport (frontend-spec §4, M13): the agent's stored report —
 * Bosnian narrative + findings (each with confidence) + recommended next step +
 * the collapsible full step trace. Numbers come from SQL tools; the trace proves it.
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import type { ConfBand, InvestigationReportData, InvestigationStep } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

/** Display band for a 0-1 confidence (presentation only — the value comes from the API). */
function confidenceBand(confidence: number): ConfBand {
  if (confidence >= 0.75) return "visoka"
  if (confidence >= 0.5) return "srednja"
  return "niska"
}

export function InvestigationReport({
  report,
  steps,
}: {
  report: InvestigationReportData
  steps: InvestigationStep[]
}) {
  const t = useT()
  const [showTrace, setShowTrace] = useState(false)

  return (
    <div className="flex flex-col gap-4" data-testid="investigation-report">
      {/* narrative (analiza) */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <RegisterChip register={report.register} />
          <ConfidenceLabel band={confidenceBand(report.confidence)} />
          {report.narrative_source === "template" && (
            <Badge variant="outline">template</Badge>
          )}
        </div>
        <p className="whitespace-pre-line text-sm text-text" data-testid="report-narrative">
          {report.narrative}
        </p>
        {report.budget_exhausted && (
          <p
            className="rounded-md bg-risk-mid/10 p-3 text-xs text-risk-mid"
            data-testid="budget-note"
          >
            {t.investigations.budget_note}
          </p>
        )}
      </div>

      {/* findings — each carries its own confidence */}
      <div className="flex flex-col gap-2" data-testid="report-findings">
        <h3 className="text-[15px] font-semibold text-text">{t.investigations.findings}</h3>
        {report.findings.map((finding, index) => (
          <div
            key={index}
            className="flex flex-col gap-1 rounded-md bg-surface-2 p-3"
            data-testid="report-finding"
          >
            <div className="flex flex-wrap items-center gap-2">
              <RegisterChip register={finding.register} />
              <ConfidenceLabel band={confidenceBand(finding.confidence)} />
            </div>
            <p className="text-sm text-text-2">{finding.text}</p>
          </div>
        ))}
      </div>

      {/* recommended next step (preporuka) */}
      <div className="flex flex-col gap-2" data-testid="report-next-step">
        <h3 className="text-[15px] font-semibold text-text">{t.investigations.next_step}</h3>
        <div className="flex flex-col gap-1 rounded-md bg-surface-2 p-3">
          <RegisterChip register={report.next_step_register ?? "preporuka"} />
          <p className="text-sm text-text-2">{report.next_step}</p>
        </div>
      </div>

      {/* the full step trace — every node + tool call, evidence one tap away */}
      <button
        type="button"
        onClick={() => setShowTrace((value) => !value)}
        className="self-start text-sm font-medium text-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        data-testid="trace-toggle"
      >
        {showTrace ? t.investigations.hide_trace : t.investigations.show_trace}
      </button>

      {showTrace && (
        <div className="flex flex-col gap-2" data-testid="investigation-trace">
          {steps.map((step) => (
            <div
              key={step.id}
              className="flex flex-col gap-1 rounded-md border p-3"
              data-testid="trace-step"
            >
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="tnum font-medium text-text-3">#{step.step_no}</span>
                <Badge variant="outline">{step.node}</Badge>
                {step.tool && <Badge>{step.tool}</Badge>}
                <span className="tnum ml-auto text-[11.5px] text-text-3">
                  {formatDate(step.at)}
                </span>
              </div>
              {step.output && <EvidenceExpander evidence={step.output} />}
            </div>
          ))}
          <p className="text-[11.5px] text-text-3">{t.app.sql_footer}</p>
        </div>
      )}
    </div>
  )
}
