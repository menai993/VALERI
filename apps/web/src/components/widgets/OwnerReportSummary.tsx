/**
 * OwnerReportSummary (ui-design §5): mini metric cards + register-tagged
 * narrative bullets from the latest weekly report.
 */
import { Link } from "react-router"

import { RegisterChip } from "./RegisterChip"
import { useT } from "@/lib/i18n"
import { formatNumber } from "@/lib/format"
import type { OwnerReportSummary as Summary } from "@/lib/api/types"

export function OwnerReportSummary({ summary }: { summary: Summary }) {
  const t = useT()

  return (
    <div className="flex flex-col gap-4" data-testid="owner-report-summary">
      <div className="grid grid-cols-2 gap-3">
        {summary.metrics.map((metric) => (
          <div key={metric.label} className="flex flex-col gap-1 rounded-md bg-surface-2 p-3">
            <span className="text-[11.5px] text-text-3">{metric.label}</span>
            <div className="flex items-center gap-2">
              <span className="tnum text-xl font-bold text-text">
                {formatNumber(metric.value)}
              </span>
              <RegisterChip register={metric.register} className="scale-90" />
            </div>
          </div>
        ))}
      </div>

      <ul className="flex flex-col gap-2">
        {summary.bullets.slice(0, 4).map((bullet, index) => (
          <li key={index} className="flex items-start gap-2 text-sm text-text-2">
            <RegisterChip register={bullet.register} className="mt-0.5 shrink-0 scale-90" />
            <span className="line-clamp-2">{bullet.text}</span>
          </li>
        ))}
      </ul>

      <Link to="/ai-report" className="text-sm font-medium text-primary hover:underline">
        {t.dashboard.owner_report.view_full}
      </Link>
    </div>
  )
}
