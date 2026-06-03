/**
 * ConfidenceLabel (ui-design §4): "pouzdanost: visoka/srednja/niska".
 * Required on every AI conclusion (principle 3).
 */
import { cn } from "@/lib/utils"
import { useT } from "@/lib/i18n"
import type { ConfBand } from "@/lib/api/types"

export function ConfidenceLabel({ band, className }: { band: ConfBand; className?: string }) {
  const t = useT()
  return (
    <span className={cn("text-[11.5px] text-text-3", className)}>
      {t.confidence.label}: {t.confidence[band]}
    </span>
  )
}
