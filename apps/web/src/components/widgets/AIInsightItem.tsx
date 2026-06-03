/**
 * AIInsightItem (ui-design §5): one "AI uvidi za Vas" list row —
 * icon chip + register chip + title + context line + confidence + Dokaz +
 * "Zanemari" (opens the RuleCard, M10 applies it).
 */
import { AlertTriangle, Moon, PackageX, ShoppingBasket, TrendingDown } from "lucide-react"

import { RegisterChip } from "./RegisterChip"
import { ConfidenceLabel } from "./ConfidenceLabel"
import { EvidenceExpander } from "./EvidenceExpander"
import { useT } from "@/lib/i18n"
import type { InsightRow } from "@/lib/api/types"

const ruleIcons: Record<string, typeof TrendingDown> = {
  customer_decline: TrendingDown,
  lost_article: PackageX,
  lost_category: PackageX,
  sleeping_customer: Moon,
  narrow_basket: ShoppingBasket,
}

export function AIInsightItem({
  insight,
  onDismiss,
}: {
  insight: InsightRow
  onDismiss: (insight: InsightRow) => void
}) {
  const t = useT()
  const Icon = ruleIcons[insight.rule] ?? AlertTriangle
  const ruleLabel = t.rules[insight.rule as keyof typeof t.rules] ?? insight.rule

  return (
    <div className="group flex flex-col gap-2 py-3" data-testid="ai-insight-item">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-soft">
          <Icon className="h-4 w-4 text-primary" />
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <RegisterChip register={insight.register} />
            <span className="truncate text-[15px] font-medium text-text">{ruleLabel}</span>
          </div>
          <span className="truncate text-sm text-text-2">{insight.customer_name}</span>
          <ConfidenceLabel band={insight.conf_band} />
        </div>

        <button
          type="button"
          onClick={() => onDismiss(insight)}
          data-testid="dismiss-insight"
          className="text-xs text-text-3 opacity-0 transition-opacity hover:text-down focus:opacity-100 focus:outline-none group-hover:opacity-100"
        >
          {t.dashboard.insights.dismiss}
        </button>
      </div>

      <div className="pl-11">
        <EvidenceExpander evidence={insight.evidence} />
      </div>
    </div>
  )
}
