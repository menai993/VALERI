/**
 * RiskBadge (ui-design §5): the Visok/Srednji/Nizak pill with tinted background.
 */
import { cn } from "@/lib/utils"
import { useT } from "@/lib/i18n"
import type { RiskBand } from "@/lib/api/types"

const styles: Record<RiskBand, string> = {
  visok: "bg-risk-high/10 text-risk-high",
  srednji: "bg-risk-mid/10 text-risk-mid",
  nizak: "bg-risk-low/10 text-risk-low",
}

export function RiskBadge({ band, className }: { band: RiskBand; className?: string }) {
  const t = useT()
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium",
        styles[band],
        className,
      )}
    >
      {t.risk[band]}
    </span>
  )
}
